"""Dual output writer: archival Deflate TIFF and shareable q95 4:4:4 JPEG.

Embeds full EXIF, XMP, and IPTC metadata via ExifTool, applies filesystem
modified times, copies original `.fpx` and `.fpx.json` sidecars into `archive/`,
and validates outputs independently with pyexiv2.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config, decoder, metadata, naming, validator

# Default ExifTool fallback locations on Windows
DEFAULT_WINDOWS_EXIFTOOL = Path(
    r"C:\Users\Stevie\AppData\Local\Programs\ExifTool\ExifTool.exe"
)


class WriterError(RuntimeError):
    """Raised when dual output writing or tag embedding fails."""


@dataclass
class OutputItemResult:
    store_name: str
    preferred_name: str
    tif_path: Path
    jpg_path: Path
    sidecar_path: Path
    fpx_copy_path: Path
    date_source: str
    is_undated: bool
    validation_ok: bool
    errors: list[str] = field(default_factory=list)


def resolve_exiftool_path(explicit_path: str | Path | None = None) -> str | None:
    """Find the ExifTool executable path on system PATH or configured location."""
    if explicit_path:
        p = Path(explicit_path)
        if p.is_file():
            return str(p)

    env_path = os.environ.get("FPX_EXIFTOOL")
    if env_path and Path(env_path).is_file():
        return env_path

    which_path = shutil.which("exiftool")
    if which_path:
        return which_path

    if DEFAULT_WINDOWS_EXIFTOOL.is_file():
        return str(DEFAULT_WINDOWS_EXIFTOOL)

    return None


def format_date_prefix(ts_dict: dict[str, Any]) -> tuple[str, bool]:
    """Format the `<YYYY-MM-DD_HHMMSS>` filename prefix. Returns (prefix, is_undated).

    Every component the evidence does not support is written as zeros, so the
    name says exactly how much is known and still sorts chronologically:

        2002-07-04_000000   a folder that named the day
        1998-01-07_131721   an embedded scan timestamp, precise to the second
        2000-08-00_000000   a folder that named only the month
        2001-00-00_000000   a folder that named only the year or a span
        0000-00-00_000000   nothing datable at all

    A zeroed day is deliberately not the same string as a real 1st of the
    month: `2000-08-01` would claim a day this archive cannot support for
    ~151 of its files. The prefix is a browsing affordance and is allowed to
    use a coarse folder date; EXIF `DateTimeOriginal` is not.
    """
    dt_orig_exif = ts_dict.get("datetime_original_exif")
    if dt_orig_exif:
        m = re.match(r"^(\d{4}):(\d{2}):(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$", dt_orig_exif)
        if m:
            y, mo, d, h, mi, s = m.groups()
            return f"{y}-{mo}-{d}_{h}{mi}{s}", False

    folder_iso = ts_dict.get("folder_date")
    precision = ts_dict.get("folder_precision", "none")
    if folder_iso and precision in ("month", "season", "year"):
        try:
            fdt = datetime.date.fromisoformat(folder_iso)
        except ValueError:
            fdt = None
        if fdt is not None:
            # 'season' keeps its opening month: 'Summer 2000' is genuinely
            # narrower than '2000', and the zeroed day still refuses to name
            # a date.
            month = fdt.month if precision in ("month", "season") else 0
            return f"{fdt.year:04d}-{month:02d}-00_000000", True

    return "0000-00-00_000000", True


def build_output_relpath(
    entry: dict[str, Any],
    derived: dict[str, Any],
    ext: str,
) -> Path:
    """Construct <album>/<YYYY-MM-DD_HHMMSS>_<originalname>.<ext> relative path."""
    # 1. Primary album folder
    albums = entry.get("albums", [])
    album_name = "Root"
    for a in albums:
        if a:
            album_name = a
            break

    # 2. Date prefix
    ts_dict = derived.get("timestamps", {})
    date_prefix, _is_undated = format_date_prefix(ts_dict)

    # 3. Base original name (stripped of .fpx suffix)
    pref_name = entry.get("preferred_name", "image.fpx")
    base_stem = naming.strip_fpx_suffix(pref_name)

    filename = f"{date_prefix}_{base_stem}.{ext}"
    return Path(album_name) / filename


def build_exiftool_args(
    derived: dict[str, Any],
    target_paths: list[Path],
) -> list[str]:
    """Construct command-line arguments for embedding metadata tags via ExifTool."""
    args = [
        "-overwrite_original",
        "-m",
        "-charset",
        "iptc=UTF8",
        "-charset",
        "filename=UTF8",
    ]

    cam = derived.get("camera", {})
    ts = derived.get("timestamps", {})

    # Camera metadata
    if cam.get("make"):
        args.append(f"-EXIF:Make={cam['make']}")
        args.append(f"-XMP-tiff:Make={cam['make']}")
    if cam.get("model"):
        args.append(f"-EXIF:Model={cam['model']}")
        args.append(f"-XMP-tiff:Model={cam['model']}")
    if cam.get("software"):
        args.append(f"-EXIF:Software={cam['software']}")
        args.append(f"-XMP-tiff:Software={cam['software']}")

    # Scanner acquisition metadata (film scans)
    scanner = derived.get("scanner")
    if scanner and scanner.get("manufacturer") and not cam.get("make"):
        args.append(f"-EXIF:Make={scanner['manufacturer']}")
        args.append(f"-XMP-tiff:Make={scanner['manufacturer']}")
    if scanner and scanner.get("model") and not cam.get("model"):
        args.append(f"-EXIF:Model={scanner['model']}")
        args.append(f"-XMP-tiff:Model={scanner['model']}")

    # Timestamps
    # DateTimeDigitized / CreateDate (import batch stamp)
    if ts.get("datetime_digitized_exif"):
        args.append(f"-EXIF:CreateDate={ts['datetime_digitized_exif']}")
        args.append(f"-XMP-xmp:CreateDate={ts['datetime_digitized_exif']}")
    if ts.get("offset_time_digitized"):
        args.append(f"-EXIF:OffsetTimeDigitized={ts['offset_time_digitized']}")

    # DateTimeOriginal (ONLY if defensible date is present)
    if ts.get("datetime_original_exif"):
        args.append(f"-EXIF:DateTimeOriginal={ts['datetime_original_exif']}")
        args.append(f"-XMP-photoshop:DateCreated={ts['datetime_original_exif']}")
        if ts.get("offset_time_original"):
            args.append(f"-EXIF:OffsetTimeOriginal={ts['offset_time_original']}")

    # IPTC Keywords / XMP Subject (all unique album names)
    keywords = derived.get("iptc_keywords", [])
    for kw in keywords:
        args.append(f"-IPTC:Keywords={kw}")
        args.append(f"-XMP-dc:Subject={kw}")

    # Human-authored captions / titles
    caption = derived.get("caption_title")
    if caption:
        args.append(f"-XMP-dc:Title={caption}")
        args.append(f"-IPTC:ObjectName={caption}")
        args.append(f"-EXIF:ImageDescription={caption}")

    # Add target files
    args.extend([str(p) for p in target_paths])
    return args


def compute_mtime_epoch(derived: dict[str, Any]) -> float | None:
    """Epoch seconds for the filesystem mtime, or `None` to leave mtime alone.

    Uses `sort_datetime` -- the best available ordering key, which the
    timestamp resolver has already picked from the capture date, the folder
    range, or the import stamp in that order.

    Returns `None` rather than falling back to the current time. A file
    stamped with the moment of conversion looks exactly like a file stamped
    with a real date, and this archive has no way to tell the two apart
    afterwards.
    """
    ts = derived.get("timestamps", {})

    sort_iso = ts.get("sort_datetime")
    if sort_iso:
        try:
            return datetime.datetime.fromisoformat(sort_iso).timestamp()
        except ValueError:
            pass

    # Older sidecars predate `sort_datetime`; fall back through the same
    # order it encodes rather than failing on them.
    dt_orig_iso = ts.get("datetime_original_exif")
    if dt_orig_iso:
        try:
            return datetime.datetime.strptime(dt_orig_iso, "%Y:%m:%d %H:%M:%S").timestamp()
        except ValueError:
            pass

    imp_iso = ts.get("import_datetime")
    if imp_iso:
        try:
            return datetime.datetime.fromisoformat(imp_iso).timestamp()
        except ValueError:
            pass

    return None


def write_single_entry_dual_output(
    fpx_path: Path,
    entry: dict[str, Any],
    *,
    output_root: Path,
    source_root: Path,
    exiftool_path: str | Path | None = None,
    dry_run: bool = False,
) -> OutputItemResult:
    """Convert a single .fpx entry to dual output (TIFF and JPEG) with sidecar and tags."""
    output_root = config.ensure_outside_source(output_root, source_root, "output root")
    store_name = entry["store_name"]
    pref_name = entry.get("preferred_name", store_name)

    # 1. Extract metadata and decode pixels
    meta = metadata.extract_fpx_metadata(fpx_path, manifest_entry=entry)
    decoded = decoder.decode_fpx(fpx_path, apply_transform=True)
    derived = meta.derived

    # 2. Compute relative and absolute file paths
    tif_rel = build_output_relpath(entry, derived, "tif")
    jpg_rel = build_output_relpath(entry, derived, "jpg")
    fpx_rel = build_output_relpath(entry, derived, "fpx")
    sidecar_rel = build_output_relpath(entry, derived, "fpx.json")

    archive_dir = output_root / "archive"
    sharing_dir = output_root / "sharing"

    tif_path = archive_dir / tif_rel
    jpg_path = sharing_dir / jpg_rel
    fpx_copy_path = archive_dir / fpx_rel
    sidecar_path = archive_dir / sidecar_rel

    _date_pfx, is_undated = format_date_prefix(derived.get("timestamps", {}))
    date_source = derived.get("timestamps", {}).get("date_source", "none")
    errors: list[str] = []

    if not dry_run:
        tif_path.parent.mkdir(parents=True, exist_ok=True)
        jpg_path.parent.mkdir(parents=True, exist_ok=True)

        # 3. Save Deflate TIFF and q95 4:4:4 JPEG
        decoded.image.save(tif_path, format="TIFF", compression="tiff_deflate")
        decoded.image.save(jpg_path, format="JPEG", quality=95, subsampling=0)

        # 4. Copy original .fpx and emit .fpx.json sidecar into archive/
        shutil.copy2(fpx_path, fpx_copy_path)
        sidecar_dict = metadata.build_sidecar_dict(meta, entry)
        sidecar_path.write_text(
            json.dumps(sidecar_dict, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

        # 5. Embed metadata tags via ExifTool
        tool_bin = resolve_exiftool_path(exiftool_path)
        if tool_bin:
            exiftool_cmd = [tool_bin] + build_exiftool_args(derived, [tif_path, jpg_path])
            proc = subprocess.run(exiftool_cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                errors.append(f"ExifTool failed ({proc.returncode}): {proc.stderr.strip()}")
        else:
            errors.append("ExifTool executable not found; metadata tags not embedded")

        # 6. Apply filesystem modified time (mtime) to all 4 files
        mtime_epoch = compute_mtime_epoch(derived)
        if mtime_epoch is not None:
            for p in (tif_path, jpg_path, fpx_copy_path, sidecar_path):
                if p.is_file():
                    try:
                        os.utime(p, (mtime_epoch, mtime_epoch))
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"Failed to set mtime on {p.name}: {exc}")

        # 7. Independent validation with pyexiv2
        val_res = validator.validate_dual_output(tif_path, jpg_path, derived)
        if not val_res.ok:
            errors.extend(val_res.errors)

    return OutputItemResult(
        store_name=store_name,
        preferred_name=pref_name,
        tif_path=tif_path,
        jpg_path=jpg_path,
        sidecar_path=sidecar_path,
        fpx_copy_path=fpx_copy_path,
        date_source=date_source,
        is_undated=is_undated,
        validation_ok=len(errors) == 0,
        errors=errors,
    )
