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
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import ImageCms

from . import album_dates as album_dates_mod
from . import config, decoder, layout, metadata, naming, outputs, validator
from . import name_template as name_template_mod

#: ExifTool is located from `FPX_EXIFTOOL` or from PATH -- never from a
#: hardcoded absolute path. The previous fallback pointed at one developer's
#: home directory, which meant this module could not be told ExifTool was
#: missing on the machine that had it installed there: every attempt to test
#: the missing-tool path silently found the real binary instead.


#: Windows' classic path limit. Long-path support is disabled on the machine
#: this archive lives on, so 260 is the real ceiling and not a formality.
WINDOWS_MAX_PATH = 259

#: No limit at all. macOS and Linux have per-*component* limits (255 bytes)
#: rather than a whole-path one anywhere near 260, so applying the Windows
#: ceiling there rejected paths the filesystem would have accepted -- and did
#: it as a per-file conversion failure.
NO_PATH_LIMIT = 0

#: ExifTool does not edit a file in place. It writes the new version to
#: `<path>_exiftool_tmp` in the same directory and renames it over the
#: original once the write succeeded, so the longest path a conversion
#: actually hands to the filesystem is the target path plus this suffix.
EXIFTOOL_TMP_SUFFIX = "_exiftool_tmp"

#: Characters held back from the ceiling for that temporary file.
#:
#: Checking the final path alone left a 13-character window -- a destination
#: of 247 to 259 characters -- that passed the check and then failed inside
#: ExifTool with `Error creating file`, which names neither the path nor the
#: length and arrives after the images have already been written. The reserve
#: is derived from the suffix rather than typed, so it cannot drift from it.
#:
#: It tightens the effective ceiling by design. `--max-path` still sets the
#: ceiling, and `--max-path 0` still turns the whole check off: the reserve is
#: a fact about ExifTool, not about Windows, and it applies to whatever
#: ceiling is in force.
EXIFTOOL_TMP_RESERVE = len(EXIFTOOL_TMP_SUFFIX)


def path_budget(limit: int) -> int:
    """The longest *final* path allowed under a whole-path ceiling of `limit`.

    `NO_PATH_LIMIT` passes straight through: no ceiling means nothing to
    reserve against.
    """
    if limit <= NO_PATH_LIMIT:
        return NO_PATH_LIMIT
    return limit - EXIFTOOL_TMP_RESERVE


def default_max_path(os_name: str | None = None) -> int:
    """The whole-path character limit to enforce on this platform.

    `0` means no limit. Windows keeps its 259, because long-path support is
    off by default there and past the limit the failure is an opaque
    `FileNotFoundError` from deep inside a save.

    `os_name` is a parameter rather than a read of `os.name` so a test can ask
    the other platform's answer without reassigning `os.name` itself, which is
    global and takes `pathlib` with it.
    """
    name = os.name if os_name is None else os_name
    return WINDOWS_MAX_PATH if name == "nt" else NO_PATH_LIMIT


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
    #: The EXIF `DateTimeOriginal` actually written, or "" where none was.
    #: Carried so the audit report and the QA gallery can show what a file
    #: claims without re-reading a sidecar that may not have been dumped.
    date_original: str
    validation_ok: bool
    errors: list[str] = field(default_factory=list)
    #: Non-fatal, but the file is not a faithful derivative: an orientation
    #: matrix that was read and not applied, or a transform stream that would
    #: not parse. These do not fail the conversion -- the pixels are still
    #: the source pixels -- but they must not disappear either.
    warnings: list[str] = field(default_factory=list)
    transform_status: str = ""
    #: The box the shareable JPEG was cut to, in the output image's
    #: coordinates, or None where the JPEG is the full frame. Carried out of
    #: the writer so `convert` can name the files whose two outputs differ --
    #: the owner has to be able to review a crop somebody framed in 2002
    #: without opening 687 sidecars.
    crop_applied: tuple[int, int, int, int] | None = None
    #: Every image written for this entry, with the spec that produced it.
    #: `tif_path`/`jpg_path` name the first archive and sharing outputs and
    #: stay for the default pair; this is what a non-default `--*-format` or
    #: `--*-framing` run actually produced.
    written: list[tuple[Path, outputs.OutputSpec]] = field(default_factory=list)
    #: The `.fpx` copy and its sidecar. Not images and not optional: the
    #: source copy is not a derivative, it is the thing being preserved. They
    #: belong in the resume bookkeeping for exactly that reason -- a resume
    #: that only checked the images restored a deleted TIFF and left the
    #: sidecar missing, reporting "0 failed" over an incomplete archive.
    side_artifacts: list[Path] = field(default_factory=list)


@functools.lru_cache(maxsize=1)
def srgb_icc_profile() -> bytes:
    """The sRGB ICC profile to embed in both outputs. Built once per run."""
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def resolve_exiftool_path(explicit_path: str | Path | None = None) -> str | None:
    """Locate the ExifTool executable, or `None` if it cannot be found.

    In order: an explicit argument, `FPX_EXIFTOOL` from the environment or
    `.env`, then PATH -- which is what a standard
    `winget install --id OliverBetz.ExifTool` provides.

    An explicit argument that is already an executable on PATH (rather than a
    path to a file) is taken as given: the caller resolved it once before the
    batch and there is nothing to look up again.
    """
    if explicit_path:
        candidate = Path(explicit_path)
        if candidate.is_file():
            return str(candidate)
        found = shutil.which(str(explicit_path))
        if found:
            return found

    env_path = os.environ.get("FPX_EXIFTOOL") or config.load_env().get("FPX_EXIFTOOL")
    if env_path and Path(env_path).is_file():
        return env_path

    return shutil.which("exiftool")


#: What to type to get ExifTool, per platform. It is not a Python package and
#: `pip install` cannot supply it, so a first-time user who is only told it is
#: "not found" has nothing to act on.
EXIFTOOL_INSTALL_HINTS: tuple[tuple[str, str], ...] = (
    ("Windows", "winget install --id OliverBetz.ExifTool"),
    ("macOS", "brew install exiftool"),
    ("Linux", "apt install libimage-exiftool-perl"),
)


def exiftool_missing_message() -> str:
    """One clear refusal, with the line this platform needs typed."""
    current = {"nt": "Windows", "posix": "macOS" if sys.platform == "darwin" else "Linux"}.get(
        os.name, ""
    )
    lines = [
        "ExifTool was not found, and every converted image needs it to carry its "
        "metadata. Nothing has been written.",
        "",
        "Install it:",
    ]
    for platform_name, command in EXIFTOOL_INSTALL_HINTS:
        marker = "  ->" if platform_name == current else "    "
        lines.append(f"{marker} {platform_name}: {command}")
    lines += [
        "",
        "Then re-run. If it is installed somewhere off PATH, point at it with "
        "--exiftool /path/to/exiftool or FPX_EXIFTOOL in .env.",
    ]
    return "\n".join(lines)


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


# `primary_album` lived here and returned the FIRST listed album. That is the
# defect 0.5.0 fixed -- most files belong to both an event folder and a flat
# dump they were also copied into, and the dump usually came first, which put
# 52 photographs of one holiday under a folder named after a zip file and cost
# them the date their real album gave for free. `layout.choose_album` picks the
# most descriptive one. The old implementation is deleted rather than left
# unused, because an unused correct-looking function is how a fixed bug gets
# picked up again.


def build_output_relpath(
    entry: dict[str, Any],
    derived: dict[str, Any],
    ext: str,
    stem: str | None = None,
    name_template: str | None = None,
    folder_scheme: str = layout.BY_ALBUM,
    folder_template: str | None = None,
) -> Path:
    """Construct the `<folder>/<filename>.<ext>` relative path.

    `<folder>` comes from `layout.output_folder`: a descriptive source folder
    keeps its name, nested under the year if the name gives one, and a folder
    whose name says nothing is replaced by year-and-month.

    `<filename>` comes from `name_template`, defaulting to what the tool has
    always written: `{year}-{month}-{day}_{time}_{name}`. The template is
    validated once before a run starts rather than per file -- see
    `name_template.validate` -- so this assumes a template it can use.

    `stem` overrides the name taken from the manifest entry, and is how
    `naming.assign_output_stems` keeps two same-named photos in one album
    from resolving to the same file. Callers converting more than one entry
    should always pass it. Note that uniqueness comes from the stem and not
    from the date, so a template with no date fields is no more likely to
    collide than the shipped one.
    """
    folder = layout.output_folder(entry, derived, folder_scheme, folder_template)
    base_stem = (
        stem
        if stem is not None
        else naming.strip_fpx_suffix(entry.get("preferred_name", "image.fpx"))
    )
    filename = name_template_mod.render(
        name_template or name_template_mod.DEFAULT_TEMPLATE,
        ts_dict=derived.get("timestamps", {}),
        name=base_stem,
        album=layout.choose_album(entry),
    )
    return folder / f"{filename}.{ext}"


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


def save_output_images(
    decoded: decoder.DecodedImage,
    targets: list[tuple[Path, outputs.OutputSpec]],
) -> None:
    """Write one file per requested output.

    Format and framing come from the spec, not from which tree the file lands
    in -- the two used to be welded together, so a full-frame JPEG could not
    be asked for at all.

    The ICC profile is not decoration. Every output is sRGB by construction --
    the decoder converts PhotoYCC on the way through -- but an untagged file
    is interpreted as whatever the viewer assumes, and "assume sRGB" is a
    convention rather than a guarantee. An archival file should say what its
    numbers mean.
    """
    icc = srgb_icc_profile()
    for path, spec in targets:
        image = spec.image_from(decoded)
        if spec.fmt == "tiff":
            image.save(path, format="TIFF", compression="tiff_deflate", icc_profile=icc)
        else:
            image.save(path, format="JPEG", quality=95, subsampling=0, icc_profile=icc)


def save_dual_images(
    decoded: decoder.DecodedImage,
    tif_path: Path,
    jpg_path: Path,
) -> None:
    """Write the archival TIFF and the shareable JPEG.

    The TIFF is the preservation copy and always holds the full frame the
    camera captured. The JPEG is the copy people open, so it gets the
    composition somebody framed at the time. Where a file carries no crop
    these are the same pixels; for the 71 that do, both the original framing
    and the intended one survive -- and the `.fpx` itself is copied next to
    the TIFF regardless.

    The ICC profile is not decoration. Both outputs are sRGB by construction
    -- the decoder converts PhotoYCC on the way through -- but an untagged
    TIFF is interpreted as whatever the viewer assumes, and "assume sRGB" is
    a convention rather than a guarantee. An archival file should say what
    its numbers mean.

    A separate function so this can be tested without a cropped `.fpx` to
    hand. All four committed fixtures are identity, and the corpus that has
    the cropped files is personal and cannot be committed, so writing the
    crop inline made "the JPEG is actually cropped" untestable at tier 1 --
    which is where it was.
    """
    paths = (tif_path, jpg_path)
    save_output_images(decoded, list(zip(paths, outputs.DEFAULT_SPECS, strict=True)))


def _no_console() -> dict[str, int]:
    """Keep ExifTool from opening a console window of its own.

    Invisible from a terminal, because the child simply shares the console
    that is already there. From a *windowed* application there is no console
    to share, so Windows creates one -- and a full run then flashes up 687
    console windows, each one taking focus. `CREATE_NO_WINDOW` says run with
    no console at all, which is what a metadata writer needs either way: its
    output is captured, never read off the screen.

    Not testable from pytest, which always has a console for the child to
    share. Found by running the packaged application.
    """
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": flag} if flag else {}


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
    specs: tuple[outputs.OutputSpec, ...] = outputs.DEFAULT_SPECS,
    album_dates: album_dates_mod.AlbumDates | None = None,
    source_copy: bool = False,
    sidecar: bool = False,
    name_template: str | None = None,
    folder_scheme: str = layout.BY_ALBUM,
    folder_template: str | None = None,
    default_tz: str | None = None,
    tz_overrides: dict[str, str] | None = None,
    max_path: int | None = None,
) -> OutputItemResult:
    """Convert a single .fpx entry to dual output (TIFF and JPEG) with sidecar and tags.

    `stem` comes from `naming.assign_output_stems`; `claimed` is a set the
    caller carries across the batch so a path collision raises instead of
    quietly overwriting a photo that was already converted.

    `exiftool_path` should be the one the caller already resolved once, before
    the batch: a missing ExifTool is a fact about the machine, not about this
    file, and discovering it per file wrote 687 images and then reported all
    687 of them failed.

    `max_path` is the whole-path character ceiling; `None` takes the
    platform's own answer and `0` disables the check.
    """
    output_root = config.ensure_outside_source(output_root, source_root, "output root")
    store_name = entry["store_name"]
    pref_name = entry.get("preferred_name", store_name)

    # 1. Extract metadata and decode pixels
    meta = metadata.extract_fpx_metadata(
        fpx_path,
        manifest_entry=entry,
        default_tz=default_tz,
        tz_overrides=tz_overrides,
        album_dates=album_dates,
    )
    decoded = decoder.decode_fpx(fpx_path, apply_transform=True)
    derived = meta.derived

    # 2. Compute relative and absolute file paths
    fpx_rel = build_output_relpath(
        entry, derived, "fpx", stem, name_template, folder_scheme, folder_template
    )
    sidecar_rel = build_output_relpath(
        entry, derived, "fpx.json", stem, name_template, folder_scheme, folder_template
    )

    archive_dir = output_root / "archive"

    targets: list[tuple[Path, outputs.OutputSpec]] = [
        (
            output_root
            / spec.tree
            / build_output_relpath(
                entry,
                derived,
                spec.ext,
                stem,
                name_template,
                folder_scheme,
                folder_template,
            ),
            spec,
        )
        for spec in specs
    ]
    fpx_copy_path = archive_dir / fpx_rel
    sidecar_path = archive_dir / sidecar_rel

    def _extras() -> list[Path]:
        """The non-image files this run was asked for, in path order."""
        wanted: list[Path] = []
        if source_copy:
            wanted.append(fpx_copy_path)
        if sidecar:
            wanted.append(sidecar_path)
        return wanted

    # The `.fpx` and its sidecar live beside the archive image; where no
    # archive output was asked for they still go to `archive/`. Both are
    # off by default: the source archive is read-only and still there, so the
    # copy duplicates something that was never at risk, and the sidecar can be
    # rebuilt from it with `metadata`. Asking for one image and getting four
    # files is a surprise, and the default is what most runs will use.
    def _first(tree: str) -> Path:
        for path, spec in targets:
            if spec.tree == tree:
                return path
        return archive_dir / build_output_relpath(
            entry, derived, "tif", stem, name_template, folder_scheme, folder_template
        )

    tif_path = _first("archive")
    jpg_path = _first("sharing")

    _date_pfx, is_undated = format_date_prefix(derived.get("timestamps", {}))
    stamps = derived.get("timestamps", {})
    date_source = stamps.get("date_source", "none")
    date_original = stamps.get("datetime_original_exif") or ""
    errors: list[str] = []
    warnings: list[str] = []

    if decoded.transform_status in (decoder.TRANSFORM_UNSUPPORTED, decoder.TRANSFORM_PARSE_ERROR):
        warnings.append(f"{decoded.transform_status}: {decoded.transform_note}")

    # A colour space nobody declared is a guess, and a guess that is wrong is
    # invisible in the output: two PhotoYCC files in this corpus were shipped
    # solidly green with 42% of their pixels clipped to zero, past every
    # automated check the project had. The fallback stays -- almost every file
    # really is NIF RGB -- but it now reaches `conversion.log` and the audit
    # report, so the handful it is wrong about can be found and looked at.
    if decoded.colour_space_assumed:
        warnings.append(f"colour-space-assumed: {decoded.colour_space_note}")

    # 2b. Refuse to write over a path this run already produced. The stems
    # assigned from the manifest should make this unreachable; it is here
    # because the failure it guards against is silent, and losing a photo to
    # a name clash is not a failure this archive can notice later.
    if claimed is not None:
        for path in [p for p, _ in targets] + _extras():
            if path in claimed:
                raise WriterError(
                    f"output path collision: {path} was already written by another "
                    f"entry in this run (this entry is {entry.get('sha256', '?')[:8]}). "
                    f"Refusing to overwrite it."
                )
        claimed.update({p for p, _ in targets} | set(_extras()))

    # Windows long-path support is disabled on the dev machine, and the
    # output tree gained a year level plus a most-descriptive album name in
    # 0.5.0. Past the limit the failure is an opaque FileNotFoundError from
    # deep inside a save, recorded as a generic per-file error with nothing
    # pointing at the cause. `ARCHITECTURE.md` makes short paths a rule; this makes
    # something enforce it.
    limit = default_max_path() if max_path is None else max_path
    budget = path_budget(limit)
    for path, spec in targets:
        if limit > NO_PATH_LIMIT and len(str(path)) > budget:
            errors.append(
                f"output path is {len(str(path))} characters, over the {budget} "
                f"available ({spec.label}). The ceiling is {limit}, which Windows "
                f"allows without long-path support, less {EXIFTOOL_TMP_RESERVE} for "
                f"the '{EXIFTOOL_TMP_SUFFIX}' file ExifTool writes beside each image "
                f"before renaming it into place -- that longer path has to fit too, "
                f"and when it does not ExifTool fails with 'Error creating file' "
                f"after the images are already written. Use a shorter --dest, or "
                f"--max-path 0 if long paths work here."
            )
    if errors:
        return OutputItemResult(
            store_name=store_name,
            preferred_name=pref_name,
            tif_path=tif_path,
            jpg_path=jpg_path,
            sidecar_path=sidecar_path,
            fpx_copy_path=fpx_copy_path,
            date_source=date_source,
            is_undated=is_undated,
            date_original=date_original,
            validation_ok=False,
            errors=errors,
            warnings=warnings,
            transform_status=decoded.transform_status,
            crop_applied=decoded.crop_applied,
        )

    if not dry_run:
        for path, _spec in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
        # 3. Save every requested output, all tagged sRGB.
        save_output_images(decoded, targets)

        # 4. Whichever extras were asked for. Both are off by default.
        if source_copy or sidecar:
            fpx_copy_path.parent.mkdir(parents=True, exist_ok=True)
        if source_copy:
            shutil.copy2(fpx_path, fpx_copy_path)
        if sidecar:
            sidecar_dict = metadata.build_sidecar_dict(meta, entry)
            sidecar_path.write_text(
                json.dumps(sidecar_dict, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

        # 5. Embed metadata tags via ExifTool
        tool_bin = resolve_exiftool_path(exiftool_path)
        if tool_bin:
            image_paths = [path for path, _ in targets]
            exiftool_cmd = [tool_bin] + build_exiftool_args(derived, image_paths)
            proc = subprocess.run(
                exiftool_cmd,
                capture_output=True,
                text=True,
                **_no_console(),
            )
            if proc.returncode != 0:
                errors.append(f"ExifTool failed ({proc.returncode}): {proc.stderr.strip()}")
        else:
            errors.append("ExifTool executable not found; metadata tags not embedded")

        # 6. Apply filesystem modified time (mtime) to all 4 files
        mtime_epoch = compute_mtime_epoch(derived)
        if mtime_epoch is not None:
            for p in [path for path, _ in targets] + _extras():
                if p.is_file():
                    try:
                        os.utime(p, (mtime_epoch, mtime_epoch))
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"Failed to set mtime on {p.name}: {exc}")

        # 7. Independent validation with pyexiv2
        # No `expected_jpeg_size` here on purpose. Passing the decoded
        # object's size would compare the output against the very thing that
        # produced it; the validator derives its expectation from the
        # metadata instead, so a crop that failed to apply actually fails.
        val_res = validator.validate_outputs(targets, derived)
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
        date_original=date_original,
        validation_ok=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        transform_status=decoded.transform_status,
        crop_applied=decoded.crop_applied,
        written=targets,
        side_artifacts=[] if dry_run else _extras(),
    )
