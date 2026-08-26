"""Dual output writer: archival Deflate TIFF and shareable q95 4:4:4 JPEG.

Embeds full EXIF, XMP, and IPTC metadata via ExifTool, applies filesystem
modified times, copies original `.fpx` and `.fpx.json` sidecars into `archive/`,
and validates outputs independently with pyexiv2.
"""

from __future__ import annotations

import datetime
import functools
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import ImageCms

from . import config, decoder, metadata, naming, validator

#: ExifTool is located from `FPX_EXIFTOOL` or from PATH -- never from a
#: hardcoded absolute path. The previous fallback pointed at one developer's
#: home directory, which meant this module could not be told ExifTool was
#: missing on the machine that had it installed there: every attempt to test
#: the missing-tool path silently found the real binary instead.


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
    #: Non-fatal, but the file is not a faithful derivative: an orientation
    #: matrix that was read and not applied, or a transform stream that would
    #: not parse. These do not fail the conversion -- the pixels are still
    #: the source pixels -- but they must not disappear either.
    warnings: list[str] = field(default_factory=list)
    transform_status: str = ""


@functools.lru_cache(maxsize=1)
def srgb_icc_profile() -> bytes:
    """The sRGB ICC profile to embed in both outputs. Built once per run."""
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def resolve_exiftool_path(explicit_path: str | Path | None = None) -> str | None:
    """Locate the ExifTool executable, or `None` if it cannot be found.

    In order: an explicit argument, `FPX_EXIFTOOL` from the environment or
    `.env`, then PATH -- which is what a standard
    `winget install --id OliverBetz.ExifTool` provides.
    """
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.is_file():
            return str(candidate)

    env_path = os.environ.get("FPX_EXIFTOOL") or config.load_env().get("FPX_EXIFTOOL")
    if env_path and Path(env_path).is_file():
        return env_path

    return shutil.which("exiftool")


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


def primary_album(entry: dict[str, Any]) -> str:
    """The album folder an entry is filed under. `Root` when it has none."""
    for album in entry.get("albums", []):
        if album:
            return str(album)
    return "Root"


def build_output_relpath(
    entry: dict[str, Any],
    derived: dict[str, Any],
    ext: str,
    stem: str | None = None,
) -> Path:
    """Construct the `<album>/<YYYY-MM-DD_HHMMSS>_<originalname>.<ext>` relative path.

    `stem` overrides the name taken from the manifest entry, and is how
    `naming.assign_output_stems` keeps two same-named photos in one album
    from resolving to the same file. Callers converting more than one entry
    should always pass it.
    """
    album_name = primary_album(entry)
    date_prefix, _is_undated = format_date_prefix(derived.get("timestamps", {}))
    base_stem = (
        stem
        if stem is not None
        else naming.strip_fpx_suffix(entry.get("preferred_name", "image.fpx"))
    )
    return Path(album_name) / f"{date_prefix}_{base_stem}.{ext}"


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
    stem: str | None = None,
    claimed: set[Path] | None = None,
) -> OutputItemResult:
    """Convert a single .fpx entry to dual output (TIFF and JPEG) with sidecar and tags.

    `stem` comes from `naming.assign_output_stems`; `claimed` is a set the
    caller carries across the batch so a path collision raises instead of
    quietly overwriting a photo that was already converted.
    """
    output_root = config.ensure_outside_source(output_root, source_root, "output root")
    store_name = entry["store_name"]
    pref_name = entry.get("preferred_name", store_name)

    # 1. Extract metadata and decode pixels
    meta = metadata.extract_fpx_metadata(fpx_path, manifest_entry=entry)
    decoded = decoder.decode_fpx(fpx_path, apply_transform=True)
    derived = meta.derived

    # 2. Compute relative and absolute file paths
    tif_rel = build_output_relpath(entry, derived, "tif", stem)
    jpg_rel = build_output_relpath(entry, derived, "jpg", stem)
    fpx_rel = build_output_relpath(entry, derived, "fpx", stem)
    sidecar_rel = build_output_relpath(entry, derived, "fpx.json", stem)

    archive_dir = output_root / "archive"
    sharing_dir = output_root / "sharing"

    tif_path = archive_dir / tif_rel
    jpg_path = sharing_dir / jpg_rel
    fpx_copy_path = archive_dir / fpx_rel
    sidecar_path = archive_dir / sidecar_rel

    _date_pfx, is_undated = format_date_prefix(derived.get("timestamps", {}))
    date_source = derived.get("timestamps", {}).get("date_source", "none")
    errors: list[str] = []
    warnings: list[str] = []

    if decoded.transform_status in (decoder.TRANSFORM_UNSUPPORTED, decoder.TRANSFORM_PARSE_ERROR):
        warnings.append(f"{decoded.transform_status}: {decoded.transform_note}")

    # 2b. Refuse to write over a path this run already produced. The stems
    # assigned from the manifest should make this unreachable; it is here
    # because the failure it guards against is silent, and losing a photo to
    # a name clash is not a failure this archive can notice later.
    if claimed is not None:
        for path in (tif_path, jpg_path, fpx_copy_path, sidecar_path):
            if path in claimed:
                raise WriterError(
                    f"output path collision: {path} was already written by another "
                    f"entry in this run (this entry is {entry.get('sha256', '?')[:8]}). "
                    f"Refusing to overwrite it."
                )
        claimed.update({tif_path, jpg_path, fpx_copy_path, sidecar_path})

    if not dry_run:
        tif_path.parent.mkdir(parents=True, exist_ok=True)
        jpg_path.parent.mkdir(parents=True, exist_ok=True)

        # 3. Save Deflate TIFF and q95 4:4:4 JPEG, both tagged sRGB.
        #
        # The ICC profile is not decoration. Both outputs are sRGB by
        # construction -- the decoder converts PhotoYCC on the way through --
        # but an untagged TIFF is interpreted as whatever the viewer assumes,
        # and "assume sRGB" is a convention rather than a guarantee. An
        # archival file should say what its numbers mean.
        icc = srgb_icc_profile()
        decoded.image.save(tif_path, format="TIFF", compression="tiff_deflate", icc_profile=icc)
        decoded.image.save(
            jpg_path, format="JPEG", quality=95, subsampling=0, icc_profile=icc
        )

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
        warnings=warnings,
        transform_status=decoded.transform_status,
    )
