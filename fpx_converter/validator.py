"""Independent Pillow validation engine for output files (TIFF and JPEG).

Enforces the binding rule: **validate with a different tool than the one that
wrote.** ExifTool writes the tags; this module reads them back with Pillow,
which shares no code with ExifTool -- a different parser, a different
language, a different author. A tag that ExifTool believes it wrote and
Pillow cannot find is a failure, which is the whole point of the rule.

This used to read back with `pyexiv2`. It no longer does, and it must not
again: `pyexiv2` is GPL-3.0 and bundles a GPL-2.0-or-later `exiv2.dll`, so
importing it from the shipped package would relicense the Windows executable.
`pyexiv2` is still installed for development (`requirements-dev.txt`) and the
tier-2 and tier-3 tests still use it as a *third* opinion on the same files --
that is a test-time dependency and is never packaged. `tests/test_validator.py`
has a test that fails if this module ever imports it again.

The one place the independence is thinner than it looks is the geometry: the
images themselves are written with Pillow and re-opened with Pillow, so the
size and format checks in `_check_image_file` are a same-tool round trip. That
was true before this change too. The *tag* chain -- the part the binding rule
is about -- is genuinely two tools.

Reading XMP needs `defusedxml` (Pillow's `getxmp` uses it and otherwise
returns an empty dict with only a warning). A silently empty XMP dict would
turn every XMP check into a check that cannot fail, so `_read_tags` refuses
it: a file carrying an XMP packet that will not parse is an error, not a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, IptcImagePlugin

from . import outputs

# TIFF compression tag 259 constants: 8 = Adobe Deflate, 32946 = PKZIP Deflate
DEFLATE_COMPRESSION_TAGS = {8, 32946}

#: IFD0 tags, in the pyexiv2-style names the checks below are written against.
#: Keeping the key names means the checks and their error messages did not
#: have to change when the reader did.
_IFD0_TAGS: dict[int, str] = {
    271: "Exif.Image.Make",
    272: "Exif.Image.Model",
    305: "Exif.Image.Software",
}

#: Pointer from IFD0 to the Exif sub-IFD, where the timestamps live.
_EXIF_IFD_POINTER = 0x8769

_EXIF_IFD_TAGS: dict[int, str] = {
    36867: "Exif.Photo.DateTimeOriginal",  # 0x9003
    36868: "Exif.Photo.DateTimeDigitized",  # 0x9004
    36881: "Exif.Photo.OffsetTimeOriginal",  # 0x9011
    36882: "Exif.Photo.OffsetTimeDigitized",  # 0x9012
}

#: IIM dataset numbers within IPTC record 2 (Application2).
_IPTC_KEYWORDS = (2, 25)


class MetadataReadbackError(RuntimeError):
    """A tag store was present but could not be read back.

    Raised rather than returning an empty dict: an unreadable store that
    reads as "no tags" makes every tag check pass vacuously, which is the
    exact shape of the two defects this project has already shipped.
    """


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def _text(value: Any) -> Any:
    """One EXIF/IPTC scalar as the checks expect it: a `str`, NUL-trimmed.

    Only the NUL padding EXIF ASCII fields carry is removed. Whitespace is
    left alone -- a caption is human-authored text and trimming it here would
    silently compare something other than what was written.
    """
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value.rstrip("\x00")
    return value


def _read_exif(img: Image.Image) -> dict[str, Any]:
    """The six EXIF tags this project writes, keyed by their pyexiv2 names.

    Absent tags are absent from the dict rather than present-and-`None`: the
    undated-photo check asks whether `Exif.Photo.DateTimeOriginal` *exists*,
    and a `None` placeholder would answer "yes" for every file.
    """
    exif = img.getexif()
    out: dict[str, Any] = {}
    for tag, name in _IFD0_TAGS.items():
        if tag in exif:
            out[name] = _text(exif[tag])
    sub = exif.get_ifd(_EXIF_IFD_POINTER)
    for tag, name in _EXIF_IFD_TAGS.items():
        if tag in sub:
            out[name] = _text(sub[tag])
    return out


def _xmp_packet_present(img: Image.Image) -> bool:
    """Whether the file carries an XMP packet at all.

    JPEG keeps it in an APP1 segment, which Pillow surfaces as `info["xmp"]`;
    TIFF keeps it in tag 700 (XMLPacket).
    """
    if img.info.get("xmp"):
        return True
    tags = getattr(img, "tag_v2", None)
    return bool(tags is not None and tags.get(700))


def _rdf_descriptions(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """The `rdf:Description` blocks out of Pillow's parsed XMP tree.

    ExifTool writes one block per schema, so this is normally a list; a file
    with a single block gives a bare dict.
    """
    rdf = (parsed.get("xmpmeta") or {}).get("RDF") or {}
    desc = rdf.get("Description")
    if isinstance(desc, dict):
        return [desc]
    if isinstance(desc, list):
        return [d for d in desc if isinstance(d, dict)]
    return []


def _bag_items(value: Any) -> list[str]:
    """`dc:subject` as a flat list of strings.

    Pillow collapses a one-item `rdf:Bag` to a bare string, so a single-album
    photo and a multi-album one arrive in different shapes.
    """
    if isinstance(value, dict):
        container = value.get("Bag") or value.get("Seq") or value.get("Alt") or {}
        value = container.get("li") if isinstance(container, dict) else container
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v if isinstance(v, str) else str(v.get("text", v)) for v in value]
    return [str(value)]


def _alt_default(value: Any) -> str | None:
    """The `x-default` alternative out of an `rdf:Alt`, e.g. `dc:title`."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    container = value.get("Alt")
    items = container.get("li") if isinstance(container, dict) else value.get("li")
    if isinstance(items, dict):
        items = [items]
    if isinstance(items, str):
        return items
    if not isinstance(items, list):
        return None
    fallback: str | None = None
    for item in items:
        if isinstance(item, str):
            fallback = fallback if fallback is not None else item
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if item.get("lang") == "x-default":
            return text
        if fallback is None:
            fallback = text
    return fallback


def _read_xmp(img: Image.Image) -> dict[str, Any]:
    """`Xmp.dc.subject` and `Xmp.dc.title` in the shapes the checks expect.

    The title comes back as pyexiv2 shaped it, `{'lang="x-default"': text}`,
    so `_validate_xmp_tags` did not have to learn a second layout.
    """
    try:
        parsed = img.getxmp()
    except Exception as exc:  # noqa: BLE001 -- any parse failure, uniformly
        raise MetadataReadbackError(f"the XMP packet could not be parsed: {exc}") from exc
    if not parsed and _xmp_packet_present(img):
        # The quiet failure mode: Pillow's `getxmp` returns `{}` and merely
        # warns when defusedxml is missing. Every XMP check would then pass
        # without checking anything.
        raise MetadataReadbackError(
            "an XMP packet is present but parsed to nothing -- Pillow needs "
            "defusedxml to read XMP, and without it every XMP check would "
            "pass without checking"
        )

    out: dict[str, Any] = {}
    subject: list[str] = []
    for desc in _rdf_descriptions(parsed):
        if "subject" in desc:
            subject.extend(_bag_items(desc["subject"]))
        if "title" in desc:
            title = _alt_default(desc["title"])
            if title is not None:
                out["Xmp.dc.title"] = {'lang="x-default"': title}
    if subject:
        out["Xmp.dc.subject"] = subject
    return out


def _read_iptc(img: Image.Image) -> dict[str, Any]:
    """`Iptc.Application2.Keywords` from the IIM block.

    Pillow finds it in the Photoshop APP13 segment of a JPEG and in TIFF tag
    33723. A single keyword arrives as bare `bytes` rather than a list.
    """
    info = IptcImagePlugin.getiptcinfo(img)
    if not info:
        return {}
    raw = info.get(_IPTC_KEYWORDS)
    if raw is None:
        return {}
    values = raw if isinstance(raw, list) else [raw]
    keywords = []
    for value in values:
        if isinstance(value, bytes):
            try:
                keywords.append(value.decode("utf-8"))
            except UnicodeDecodeError:
                keywords.append(value.decode("latin-1"))
        else:
            keywords.append(str(value))
    return {"Iptc.Application2.Keywords": keywords}


def _read_tags(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """`(exif, xmp, iptc)` for one output file, in one open.

    `getiptcinfo` reads from the open image, so all three come from the same
    handle rather than three separate opens.
    """
    with Image.open(path) as img:
        return _read_exif(img), _read_xmp(img), _read_iptc(img)


def _validate_tags_on(path: Path, expected: dict[str, Any], errors: list[str]) -> None:
    """Read one file back and run every tag check against it."""
    fmt = path.suffix.upper()
    try:
        exif, xmp, iptc = _read_tags(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{fmt} metadata readback failed on {path.name}: {exc}")
        return
    _validate_exif_tags(exif, expected, fmt, errors)
    _validate_xmp_tags(xmp, expected, fmt, errors)
    _validate_iptc_tags(iptc, expected, fmt, errors)


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
    if want is None:
        # A check that silently does not run is worse than no check: it makes
        # an unverified file indistinguishable from a verified one, and this
        # is the only automated proof the project has that a crop applied.
        errors.append(
            f"{path.name} ({spec.label}): no declared size in the metadata, so its "
            "dimensions were not verified against anything"
        )
    elif size != tuple(want):
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
        _validate_tags_on(path, expected_derived, errors)

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
    _validate_tags_on(jpg_path, expected_derived, errors)
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
