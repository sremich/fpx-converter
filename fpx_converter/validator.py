"""Independent pyexiv2 validation engine for dual output files (TIFF and JPEG).

Enforces the binding rule: Validate with a different tool than the one that wrote.
ExifTool writes tags; pyexiv2 independently reads back and validates tags on both
TIFF and JPEG formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyexiv2
from PIL import Image

from . import outputs

# TIFF compression tag 259 constants: 8 = Adobe Deflate, 32946 = PKZIP Deflate
DEFLATE_COMPRESSION_TAGS = {8, 32946}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)



def _declared_sizes(
    expected: dict[str, Any],
) -> tuple[tuple[int, int] | None, tuple[int, int, int, int] | None]:
    """`(expected_tiff_size, crop_box)` from the metadata, not from the pixels.

    These come from `metadata.py`'s reading of the `.fpx` property sets, so
    they are independent of the decode that produced the files on disk.

    **They are not independent of the geometry.** `metadata.py` resolves them
    by calling `decoder.output_geometry`, which is the same function the
    decode path calls. So this catches a crop that failed to *apply* -- the
    output would then disagree with an expectation derived from the file --
    but it cannot catch a crop *derived* wrongly, because expectation and
    output would be wrong together. The only genuinely independent geometry
    oracle this project has is the embedded DIB thumbnail, and it is not
    wired in here; it is run by hand at tier 3.

    The size is the *post-rotation* one. For the 22 rotated files the TIFF is
    864x1152 while the file declares 1152x864, so checking against the raw
    declared size would have failed every correctly rotated photo.
    """
    transform = expected.get("viewing_transform") or {}

    size = transform.get("tiff_size")
    if size and len(size) == 2:
        declared = (int(size[0]), int(size[1]))
    else:
        dims = expected.get("image_dimensions") or {}
        width = dims.get("declared_width")
        height = dims.get("declared_height")
        declared = (int(width), int(height)) if width and height else None

    box = transform.get("crop_box")
    crop = tuple(int(v) for v in box) if box and len(box) == 4 else None
    return declared, crop  # type: ignore[return-value]


def _check_image_file(
    path: Path,
    spec: outputs.OutputSpec,
    declared: tuple[int, int] | None,
    crop_box: tuple[int, int, int, int] | None,
    errors: list[str],
) -> tuple[int, int] | None:
    """Format-specific header checks for one output. Returns its pixel size."""
    with Image.open(path) as img:
        size = img.size

        if spec.fmt == "tiff":
            comp_tag = img.tag_v2.get(259) if hasattr(img, "tag_v2") else None
            if comp_tag not in DEFLATE_COMPRESSION_TAGS and img.info.get("compression") not in (
                "tiff_adobe_deflate",
                "tiff_deflate",
            ):
                errors.append(
                    f"{path.name}: TIFF compression is not Deflate: "
                    f"tag_259={comp_tag}, info={img.info}"
                )
        else:
            # An unreadable sampling table is an error, not a pass. This check
            # used to sit behind `if img.layer:`, so a JPEG whose factors
            # could not be read validated clean -- and a 4:2:0 file would have
            # been indistinguishable from a 4:4:4 one.
            layer = getattr(img, "layer", None)
            if not layer:
                errors.append(
                    f"{path.name}: JPEG chroma subsampling could not be verified: "
                    "Pillow reported no component sampling table"
                )
            else:
                sampling = [(comp[1], comp[2]) for comp in layer]
                if any(sf != (1, 1) for sf in sampling):
                    errors.append(
                        f"{path.name}: JPEG chroma subsampling is not 4:4:4: {sampling}"
                    )

    want = spec.expected_size(declared, crop_box)
    if want is not None and size != tuple(want):
        errors.append(f"{path.name} ({spec.label}) is {size}, expected {tuple(want)}")
    if (
        spec.framing == "cropped"
        and crop_box is not None
        and declared is not None
        and size == tuple(declared)
    ):
        errors.append(
            f"{path.name}: a crop {crop_box} is declared but the output is still "
            f"the full frame {size}"
        )
    return size


def validate_outputs(
    targets: list[tuple[Path, outputs.OutputSpec]],
    expected_derived: dict[str, Any],
) -> ValidationResult:
    """Validate every written output against the metadata that describes it.

    Sizes are checked against `expected_derived` -- the metadata read from the
    `.fpx`, computed independently of the decode that produced these files.
    Deriving the expectation from the decoded object instead would make the
    check unfalsifiable: if a crop silently failed to apply, that object would
    report the full frame, the expectation would match the output, and the
    validation would pass.

    See `_declared_sizes` for the limit of that independence: this proves the
    crop was applied, not that the box was right.
    """
    errors: list[str] = []
    missing = [str(path) for path, _ in targets if not path.is_file()]
    if missing:
        return ValidationResult(ok=False, errors=[f"output file missing: {m}" for m in missing])

    declared, crop_box = _declared_sizes(expected_derived)
    try:
        for path, spec in targets:
            _check_image_file(path, spec, declared, crop_box, errors)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Image header validation failed: {exc}")

    # Tags, read back with a different tool than the one that wrote them.
    for path, _spec in targets:
        fmt = path.suffix.upper()
        try:
            with pyexiv2.Image(str(path)) as meta:
                _validate_exif_tags(meta.read_exif(), expected_derived, fmt, errors)
                _validate_xmp_tags(meta.read_xmp(), expected_derived, fmt, errors)
                _validate_iptc_tags(meta.read_iptc(), expected_derived, fmt, errors)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fmt} pyexiv2 readback failed on {path.name}: {exc}")

    return ValidationResult(ok=len(errors) == 0, errors=errors)


def validate_dual_output(
    tif_path: Path,
    jpg_path: Path,
    expected_derived: dict[str, Any],
    expected_jpeg_size: tuple[int, int] | None = None,
) -> ValidationResult:
    """The default pair -- a full-frame Deflate TIFF and a cropped q95 JPEG.

    Kept because it names the shipped output shape, which is still what
    `convert` writes when nothing else is asked for. `validate_outputs` is the
    general form and takes whatever set was actually requested.

    `expected_jpeg_size` overrides the JPEG expectation for callers with no
    metadata to hand. It is an override for a reason: derive the expectation
    from the decoded object and the check stops being able to fail.
    """
    targets = [
        (tif_path, outputs.OutputSpec("archive", "tiff", "full")),
        (jpg_path, outputs.OutputSpec("sharing", "jpeg", "cropped")),
    ]
    if expected_jpeg_size is None:
        return validate_outputs(targets, expected_derived)

    result = validate_outputs(targets[:1], expected_derived)
    errors = list(result.errors)
    if not jpg_path.is_file():
        errors.append(f"output file missing: {jpg_path}")
        return ValidationResult(ok=False, errors=errors)
    with Image.open(jpg_path) as jpg_img:
        jpg_size = jpg_img.size
    if jpg_size != tuple(expected_jpeg_size):
        errors.append(f"{jpg_path.name} is {jpg_size}, expected {tuple(expected_jpeg_size)}")
    fmt = jpg_path.suffix.upper()
    try:
        with pyexiv2.Image(str(jpg_path)) as meta:
            _validate_exif_tags(meta.read_exif(), expected_derived, fmt, errors)
            _validate_xmp_tags(meta.read_xmp(), expected_derived, fmt, errors)
            _validate_iptc_tags(meta.read_iptc(), expected_derived, fmt, errors)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{fmt} pyexiv2 readback failed on {jpg_path.name}: {exc}")
    return ValidationResult(ok=len(errors) == 0, errors=errors)


def _validate_exif_tags(
    exif: dict[str, Any],
    expected: dict[str, Any],
    fmt: str,
    errors: list[str],
) -> None:
    cam = expected.get("camera", {})
    ts = expected.get("timestamps", {})

    # Camera Make/Model/Software
    if cam.get("make") and exif.get("Exif.Image.Make") != cam["make"]:
        actual_make = exif.get("Exif.Image.Make")
        errors.append(f"{fmt} EXIF Make mismatch: got '{actual_make}', exp '{cam['make']}'")

    if cam.get("model") and exif.get("Exif.Image.Model") != cam["model"]:
        actual_model = exif.get("Exif.Image.Model")
        errors.append(f"{fmt} EXIF Model mismatch: got '{actual_model}', exp '{cam['model']}'")

    if cam.get("software") and exif.get("Exif.Image.Software") != cam["software"]:
        actual_sw = exif.get("Exif.Image.Software")
        errors.append(f"{fmt} EXIF Software mismatch: got '{actual_sw}', exp '{cam['software']}'")

    # Scanner Make/Model.
    #
    # Only when the writer would actually have written it: it falls back to
    # the scanner manufacturer only where there is no camera make. Checking
    # unconditionally would fail any file carrying both, and count a correct
    # conversion as a failure.
    scanner = expected.get("scanner")
    if scanner and scanner.get("manufacturer") and not cam.get("make"):
        act_scn = exif.get("Exif.Image.Make")
        if act_scn != scanner["manufacturer"]:
            errors.append(
                f"{fmt} EXIF Scanner Make mismatch: "
                f"got '{act_scn}', exp '{scanner['manufacturer']}'"
            )

    # DateTimeDigitized
    exp_dig = ts.get("datetime_digitized_exif")
    act_dig = exif.get("Exif.Photo.DateTimeDigitized")
    if exp_dig and act_dig != exp_dig:
        errors.append(f"{fmt} EXIF DateTimeDigitized mismatch: got '{act_dig}', exp '{exp_dig}'")

    exp_off_dig = ts.get("offset_time_digitized")
    act_off_dig = exif.get("Exif.Photo.OffsetTimeDigitized")
    if exp_off_dig and act_off_dig != exp_off_dig:
        errors.append(
            f"{fmt} EXIF OffsetTimeDigitized mismatch: got '{act_off_dig}', exp '{exp_off_dig}'"
        )

    # DateTimeOriginal
    exp_orig = ts.get("datetime_original_exif")
    if exp_orig:
        act_orig = exif.get("Exif.Photo.DateTimeOriginal")
        if act_orig != exp_orig:
            errors.append(
                f"{fmt} EXIF DateTimeOriginal mismatch: got '{act_orig}', exp '{exp_orig}'"
            )
        exp_off_orig = ts.get("offset_time_original")
        act_off_orig = exif.get("Exif.Photo.OffsetTimeOriginal")
        if exp_off_orig and act_off_orig != exp_off_orig:
            errors.append(
                f"{fmt} EXIF OffsetTimeOriginal mismatch: "
                f"got '{act_off_orig}', exp '{exp_off_orig}'"
            )
    else:
        # Crucial check: DateTimeOriginal must NOT exist on undated photos
        if "Exif.Photo.DateTimeOriginal" in exif:
            present_dt = exif.get("Exif.Photo.DateTimeOriginal")
            errors.append(f"{fmt} EXIF DateTimeOriginal present on undated photo: {present_dt}")


def _validate_xmp_tags(
    xmp: dict[str, Any],
    expected: dict[str, Any],
    fmt: str,
    errors: list[str],
) -> None:
    exp_keywords = expected.get("iptc_keywords", [])
    if exp_keywords:
        actual_subject = xmp.get("Xmp.dc.subject", [])
        if isinstance(actual_subject, str):
            actual_subject = [actual_subject]
        for kw in exp_keywords:
            if kw not in actual_subject:
                errors.append(f"{fmt} XMP Subject missing keyword '{kw}': got {actual_subject}")

    caption = expected.get("caption_title")
    if caption:
        title_dict = xmp.get("Xmp.dc.title", {})
        actual_title = (
            title_dict.get('lang="x-default"')
            if isinstance(title_dict, dict)
            else str(title_dict)
        )
        if actual_title != caption:
            errors.append(f"{fmt} XMP Title mismatch: got '{actual_title}', exp '{caption}'")


def _validate_iptc_tags(
    iptc: dict[str, Any],
    expected: dict[str, Any],
    fmt: str,
    errors: list[str],
) -> None:
    exp_keywords = expected.get("iptc_keywords", [])
    if exp_keywords:
        actual_keywords = iptc.get("Iptc.Application2.Keywords", [])
        if isinstance(actual_keywords, str):
            actual_keywords = [actual_keywords]
        for kw in exp_keywords:
            if kw not in actual_keywords:
                errors.append(f"{fmt} IPTC Keywords missing '{kw}': got {actual_keywords}")
