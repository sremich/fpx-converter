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

# TIFF compression tag 259 constants: 8 = Adobe Deflate, 32946 = PKZIP Deflate
DEFLATE_COMPRESSION_TAGS = {8, 32946}


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)



def _declared_sizes(
    expected: dict[str, Any],
) -> tuple[tuple[int, int] | None, tuple[int, int, int, int] | None]:
    """`(expected_tiff_size, crop_box)` from the metadata, independent of the decode.

    These come from `metadata.py`'s reading of the `.fpx` property sets, so
    comparing outputs against them is a real check. Comparing against
    anything the decoder returned would only confirm the decoder agrees with
    itself.

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


def validate_dual_output(
    tif_path: Path,
    jpg_path: Path,
    expected_derived: dict[str, Any],
    expected_jpeg_size: tuple[int, int] | None = None,
) -> ValidationResult:
    """Validate the TIFF and JPEG against each other and against the metadata.

    Both sizes are checked against `expected_derived` -- the metadata read
    from the `.fpx`, which is computed independently of the decode that
    produced these files. The TIFF must equal the declared image size; the
    JPEG must equal the crop box when one is declared, and the declared size
    otherwise.

    Deriving the expectation from the decoded object instead would make the
    check unfalsifiable: if the crop silently failed to apply, that object
    would report the full frame, the expectation would match the output, and
    the validation would pass. `expected_jpeg_size` is therefore accepted
    only as an override for callers that have no metadata to hand.
    """
    errors: list[str] = []

    if not tif_path.is_file():
        return ValidationResult(ok=False, errors=[f"TIFF file missing: {tif_path}"])
    if not jpg_path.is_file():
        return ValidationResult(ok=False, errors=[f"JPEG file missing: {jpg_path}"])

    # 1. Image dimensions & compression checks via Pillow
    try:
        with Image.open(tif_path) as tif_img:
            tif_size = tif_img.size
            comp_tag = tif_img.tag_v2.get(259) if hasattr(tif_img, "tag_v2") else None
            if comp_tag not in DEFLATE_COMPRESSION_TAGS and tif_img.info.get("compression") not in (
                "tiff_adobe_deflate",
                "tiff_deflate",
            ):
                errors.append(
                    f"TIFF compression is not Deflate: tag_259={comp_tag}, info={tif_img.info}"
                )

        with Image.open(jpg_path) as jpg_img:
            jpg_size = jpg_img.size
            # Verify 4:4:4 chroma subsampling (all components sampling (1, 1)).
            #
            # An unreadable sampling table is an error, not a pass. This
            # check used to sit behind `if jpg_img.layer:`, so a JPEG whose
            # factors could not be read validated clean -- and a 4:2:0 file
            # would have been indistinguishable from a 4:4:4 one.
            layer = getattr(jpg_img, "layer", None)
            if not layer:
                errors.append(
                    "JPEG chroma subsampling could not be verified: Pillow reported "
                    "no component sampling table for this file"
                )
            else:
                # layer format is list of (component_id, h_samp, v_samp, quant_table)
                sampling_factors = [(comp[1], comp[2]) for comp in layer]
                if any(sf != (1, 1) for sf in sampling_factors):
                    errors.append(
                        f"JPEG chroma subsampling is not 4:4:4: sampling={sampling_factors}"
                    )

        declared, crop_box = _declared_sizes(expected_derived)

        if declared is not None and tif_size != declared:
            errors.append(f"TIFF is {tif_size}, but the file declares {declared}")

        want_jpeg = expected_jpeg_size
        if want_jpeg is None:
            if crop_box is not None:
                want_jpeg = (crop_box[2] - crop_box[0], crop_box[3] - crop_box[1])
            else:
                want_jpeg = declared

        if want_jpeg is not None:
            if jpg_size != tuple(want_jpeg):
                errors.append(
                    f"JPEG is {jpg_size}, expected {tuple(want_jpeg)} (TIFF is {tif_size})"
                )
            if crop_box is not None and jpg_size == tif_size:
                errors.append(
                    f"a crop {crop_box} is declared but the JPEG is still the full "
                    f"frame {jpg_size}"
                )
        elif tif_size != jpg_size:
            errors.append(f"Dimensions mismatch: TIFF {tif_size} vs JPEG {jpg_size}")

    except Exception as exc:  # noqa: BLE001
        errors.append(f"Image header validation failed: {exc}")

    # 2. Tag validation via pyexiv2 on both TIFF and JPEG
    for img_path in (tif_path, jpg_path):
        fmt = img_path.suffix.upper()
        try:
            with pyexiv2.Image(str(img_path)) as meta:
                exif = meta.read_exif()
                xmp = meta.read_xmp()
                iptc = meta.read_iptc()

                _validate_exif_tags(exif, expected_derived, fmt, errors)
                _validate_xmp_tags(xmp, expected_derived, fmt, errors)
                _validate_iptc_tags(iptc, expected_derived, fmt, errors)

        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fmt} pyexiv2 readback failed on {img_path.name}: {exc}")

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
