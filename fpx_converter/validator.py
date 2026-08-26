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


def validate_dual_output(
    tif_path: Path,
    jpg_path: Path,
    expected_derived: dict[str, Any],
) -> ValidationResult:
    """Validate that TIFF and JPEG output files match in dimensions, compression, and tags."""
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
            # Verify 4:4:4 chroma subsampling (all components sampling (1, 1))
            if hasattr(jpg_img, "layer") and jpg_img.layer:
                # layer format is list of (component_id, h_samp, v_samp, quant_table)
                sampling_factors = [(comp[1], comp[2]) for comp in jpg_img.layer]
                if any(sf != (1, 1) for sf in sampling_factors):
                    errors.append(
                        f"JPEG chroma subsampling is not 4:4:4: sampling={sampling_factors}"
                    )

        if tif_size != jpg_size:
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

    # Scanner Make/Model
    scanner = expected.get("scanner")
    if scanner and scanner.get("manufacturer"):
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
