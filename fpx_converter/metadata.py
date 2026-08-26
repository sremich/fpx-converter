"""Metadata extraction engine and raw JSON sidecar generator.

Extracts all 10 standard FlashPix property sets, extension storages
(`viewprmlog` edit log and Kodak pedigree), and derived metadata (dimensions,
colour space, viewing transforms, camera identity, resolved timestamps, IPTC
keywords, captions).

Emits complete `.fpx.json` sidecar dumps for every manifest entry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import olefile

from . import config, decoder, naming, propset, timestamps

# Standard property set streams present in FlashPix files
STANDARD_PROPERTY_SETS = [
    ("\x05SummaryInformation", propset.FMTID_SUMMARY_INFORMATION),
    ("\x05Global Info", propset.FMTID_GLOBAL_INFO),
    ("\x05Extension List", propset.FMTID_EXTENSION_LIST),
    ("\x05Operation 000001", propset.FMTID_OPERATION),
    ("\x05Transform 000001", propset.FMTID_TRANSFORM),
    ("\x05Data Object 000001", propset.FMTID_DATA_OBJECT),
    ("\x05Data Object 000002", propset.FMTID_DATA_OBJECT),
    ("Data Object Store 000001/\x05Image Contents", propset.FMTID_IMAGE_CONTENTS),
    ("Data Object Store 000001/\x05Image Info", propset.FMTID_IMAGE_INFO),
    (
        "Data Object Store 000001/\x05SummaryInformation",
        propset.FMTID_SUMMARY_INFORMATION,
    ),
]


@dataclass
class ExtractedMetadata:
    sha256: str
    store_name: str
    stream_inventory: list[str]
    property_sets: dict[str, Any]
    extension_storages: dict[str, Any]
    derived: dict[str, Any]
    errors: list[str] = field(default_factory=list)


def extract_fpx_metadata(
    fpx_path: Path,
    manifest_entry: dict[str, Any] | None = None,
    default_tz: str = timestamps.DEFAULT_TZ,
    tz_overrides: dict[str, str] | None = None,
) -> ExtractedMetadata:
    """Extract all metadata from an `.fpx` file into a structured ExtractedMetadata."""
    sha = manifest_entry.get("sha256", "") if manifest_entry else ""
    store_name = (
        manifest_entry.get("store_name", fpx_path.name) if manifest_entry else fpx_path.name
    )
    inventory: list[str] = []
    parsed_psets: dict[str, Any] = {}
    ext_storages: dict[str, Any] = {
        "viewpedigree_log": None,
        "kodak_pedigree": None,
    }
    errors: list[str] = []

    try:
        with olefile.OleFileIO(str(fpx_path)) as ole:
            inventory = ["/".join(p) for p in ole.listdir(streams=True, storages=True)]

            # 1. Parse standard property sets
            for stream_name, _expected_fmtid in STANDARD_PROPERTY_SETS:
                # OleFileIO.openstream expects a list of parts or slash-separated path
                stream_parts = stream_name.split("/")
                if ole.exists(stream_parts):
                    try:
                        with ole.openstream(stream_parts) as stream_handle:
                            raw_bytes = stream_handle.read()
                        pset = propset.parse_propset(raw_bytes, stream_name=stream_name)
                        parsed_psets[stream_name] = _serialize_propset(pset)
                        if pset.errors:
                            errors.extend([f"{stream_name}: {e}" for e in pset.errors])
                    except Exception as exc:  # noqa: BLE001
                        err_msg = f"failed to read stream {stream_name}: {exc}"
                        errors.append(err_msg)
                        parsed_psets[stream_name] = {"error": err_msg}

            # 2. Extract extension storages if present
            # 2a. viewpedigree edit log
            for item in inventory:
                if "viewprmlog" in item:
                    try:
                        with ole.openstream(item.split("/")) as log_handle:
                            log_bytes = log_handle.read()
                        log_text = log_bytes.decode("latin-1", "replace")
                        ext_storages["viewpedigree_log"] = {
                            "stream_name": item,
                            "length": len(log_bytes),
                            "content": log_text,
                        }
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"failed to read edit log {item}: {exc}")

                # 2b. Kodak pedigree property set
                if "Kodak_Pedigree Image Info" in item:
                    try:
                        with ole.openstream(item.split("/")) as ped_handle:
                            ped_bytes = ped_handle.read()
                        ped_pset = propset.parse_propset(ped_bytes, stream_name=item)
                        ext_storages["kodak_pedigree"] = _serialize_propset(ped_pset)
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"failed to read pedigree pset {item}: {exc}")

    except Exception as exc:  # noqa: BLE001
        errors.append(f"OLE error opening {fpx_path.name}: {exc}")

    # 3. Compute derived metadata
    derived = _derive_metadata(
        parsed_psets,
        manifest_entry,
        default_tz=default_tz,
        tz_overrides=tz_overrides,
    )

    return ExtractedMetadata(
        sha256=sha,
        store_name=store_name,
        stream_inventory=sorted(inventory),
        property_sets=parsed_psets,
        extension_storages=ext_storages,
        derived=derived,
        errors=errors,
    )


def _sanitize_value(val: Any) -> Any:
    """Sanitize property values for JSON serialization, omitting binary buffers."""
    if isinstance(val, bytes):
        return val.hex()
    if isinstance(val, dict):
        return {k: _sanitize_value(v) for k, v in val.items() if k != "raw_bytes"}
    if isinstance(val, list):
        return [_sanitize_value(v) for v in val]
    return val


def _serialize_propset(pset: propset.ParsedPropertySet) -> dict[str, Any]:
    """Convert a ParsedPropertySet into a clean JSON-serializable dictionary."""
    sections_list: list[dict[str, Any]] = []
    for sec in pset.sections:
        props_dict: dict[str, Any] = {}
        for _pid, prop in sec.properties.items():
            props_dict[prop.name] = {
                "pid": prop.pid,
                "pid_hex": prop.pid_hex,
                "name": prop.name,
                "type_id": prop.type_id,
                "type_name": prop.type_name,
                "raw_value": _sanitize_value(prop.raw_value),
                "decoded_value": _sanitize_value(prop.decoded_value),
            }
        sections_list.append(
            {
                "fmtid": sec.fmtid,
                "cb": sec.cb,
                "cprops": sec.cprops,
                "codepage": sec.codepage,
                "errors": sec.errors,
                "properties": props_dict,
            }
        )
    return {
        "stream_name": pset.stream_name,
        "errors": pset.errors,
        "sections": sections_list,
    }


def _get_prop_decoded(
    psets: dict[str, Any],
    stream_name: str,
    prop_name: str,
) -> Any:
    """Retrieve decoded_value for a property from serialized property sets."""
    stream_dict = psets.get(stream_name, {})
    sections = stream_dict.get("sections", [])
    for sec in sections:
        props = sec.get("properties", {})
        if prop_name in props:
            return props[prop_name].get("decoded_value")
    return None


def _get_prop_raw(
    psets: dict[str, Any],
    stream_name: str,
    prop_name: str,
) -> Any:
    """Retrieve raw_value for a property from serialized property sets."""
    stream_dict = psets.get(stream_name, {})
    sections = stream_dict.get("sections", [])
    for sec in sections:
        props = sec.get("properties", {})
        if prop_name in props:
            return props[prop_name].get("raw_value")
    return None


def _derive_metadata(
    psets: dict[str, Any],
    entry: dict[str, Any] | None,
    default_tz: str = timestamps.DEFAULT_TZ,
    tz_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Derive standard image dimensions, colour space, transforms, and timestamps."""
    img_contents_stream = "Data Object Store 000001/\x05Image Contents"
    img_info_stream = "Data Object Store 000001/\x05Image Info"
    transform_stream = "\x05Transform 000001"
    summary_stream = "\x05SummaryInformation"
    data_obj1_stream = "\x05Data Object 000001"

    # Dimensions
    num_res = _get_prop_decoded(psets, img_contents_stream, "NumberOfResolutions") or 0
    full_w = _get_prop_decoded(psets, img_contents_stream, "HighestResolutionWidth")
    full_h = _get_prop_decoded(psets, img_contents_stream, "HighestResolutionHeight")
    if full_w is None:
        full_w = _get_prop_decoded(psets, data_obj1_stream, "ImageWidth")
    if full_h is None:
        full_h = _get_prop_decoded(psets, data_obj1_stream, "ImageHeight")

    resolutions: list[dict[str, int]] = []
    if isinstance(num_res, int) and num_res > 0:
        for r in range(num_res):
            rw = _get_prop_decoded(psets, img_contents_stream, f"Res{r}_SubimageWidth")
            rh = _get_prop_decoded(psets, img_contents_stream, f"Res{r}_SubimageHeight")
            if rw is not None and rh is not None:
                resolutions.append({"resolution": r, "width": rw, "height": rh})

    dims_dict = {
        "declared_width": full_w,
        "declared_height": full_h,
        "num_resolutions": num_res,
        "resolutions": resolutions,
    }

    # Colour Space
    col_blob = _get_prop_decoded(psets, img_contents_stream, "Res0_SubimageColor")
    if isinstance(col_blob, dict) and col_blob.get("blob_type") == "SubimageColor":
        colour_dict = {
            "colour_space": col_blob.get("colour_space", "UNKNOWN"),
            "uncalibrated": col_blob.get("uncalibrated", True),
            "channel_count": col_blob.get("channel_count", 3),
            "channel_ids": col_blob.get("channel_ids", []),
        }
    else:
        colour_dict = {
            "colour_space": "NIF_RGB",  # 99.7% default
            "uncalibrated": True,
            "channel_count": 3,
            "channel_ids": ["0x00030000", "0x00030001", "0x00030002"],
        }

    # Viewing Transform
    matrix_16 = _get_prop_decoded(psets, transform_stream, "SpatialOrientationMatrix")
    color_twist = _get_prop_decoded(psets, transform_stream, "ColorTwistMatrix")
    aspect_ratio = _get_prop_decoded(psets, transform_stream, "ResultAspectRatio")
    roi = _get_prop_decoded(psets, transform_stream, "RectangleOfInterest")
    filtering = _get_prop_decoded(psets, transform_stream, "FilteringValue")
    contrast = _get_prop_decoded(psets, transform_stream, "ContrastAdjustment")

    transform_status = decoder.TRANSFORM_ABSENT
    transform_note = ""
    if isinstance(matrix_16, list) and len(matrix_16) == 16:
        transform_status, transform_note = decoder.classify_orientation_matrix(
            [float(x) for x in matrix_16]
        )
    is_rotation_90_ccw = transform_status == decoder.TRANSFORM_ROTATE_90_CCW

    # `has_transform` used to compare the ROI against [0, 0, 1, 1] and so was
    # True for every file in the corpus: the full-frame ROI of a 4:3 image is
    # [0, 0, 1.333, 1], because FlashPix normalises height to 1 and expresses
    # width as the aspect ratio. A flag that is always set answers nothing.
    # The ROI is a crop only when it does not cover the whole frame.
    roi_is_full_frame = True
    if isinstance(roi, list) and len(roi) == 4:
        declared_aspect = (
            dims_dict["declared_width"] / dims_dict["declared_height"]
            if dims_dict.get("declared_height")
            else 0.0
        )
        x, y, roi_w, roi_h = (float(v) for v in roi)
        roi_is_full_frame = (
            abs(x) < 1e-3
            and abs(y) < 1e-3
            and abs(roi_h - 1.0) < 1e-3
            and abs(roi_w - declared_aspect) < 1e-2
        )

    has_transform = transform_status not in (
        decoder.TRANSFORM_ABSENT,
        decoder.TRANSFORM_IDENTITY,
    ) or not roi_is_full_frame

    transform_dict = {
        "has_transform": has_transform,
        "transform_status": transform_status,
        "transform_note": transform_note,
        "roi_is_full_frame": roi_is_full_frame,
        "is_rotation_90_ccw": is_rotation_90_ccw,
        "aspect_ratio": aspect_ratio,
        "rectangle_of_interest": roi,
        "filtering_value": filtering,
        "spatial_orientation_matrix": matrix_16,
        "color_twist_matrix": color_twist,
        "contrast_adjustment": contrast,
    }

    # Camera & Acquisition
    cam_make = _get_prop_decoded(psets, img_info_stream, "CameraManufacturerName")
    cam_model = _get_prop_decoded(psets, img_info_stream, "CameraModelName")
    app_name = _get_prop_decoded(psets, summary_stream, "PIDSI_APPNAME")
    file_src = _get_prop_decoded(psets, img_info_stream, "FileSource")

    cam_dict = {
        "make": cam_make,
        "model": cam_model,
        "software": app_name,
        "file_source": file_src,
    }

    # Scanner info (for film scans)
    scanner_dict: dict[str, Any] | None = None
    scanner_make = _get_prop_decoded(psets, img_info_stream, "ScannerManufacturer")
    if scanner_make:
        scanner_dict = {
            "manufacturer": scanner_make,
            "model": _get_prop_decoded(psets, img_info_stream, "ScannerModel"),
            "serial": _get_prop_decoded(psets, img_info_stream, "ScannerSerialNumber"),
            "software_revision": _get_prop_decoded(psets, img_info_stream, "ScanSoftwareRevision"),
            "service_bureau": _get_prop_decoded(psets, img_info_stream, "ServiceBureauOrgName"),
            "operator_id": _get_prop_decoded(psets, img_info_stream, "ScanOperatorID"),
            "scan_time": _get_prop_decoded(psets, img_info_stream, "ScanTime"),
            "pixel_size_um": _get_prop_decoded(psets, img_info_stream, "ScannerPixelSize"),
            "film_brand": _get_prop_decoded(psets, img_info_stream, "FilmBrand"),
            "film_size": _get_prop_decoded(psets, img_info_stream, "FilmSize"),
        }

    # Timestamps
    import_ft_raw = _get_prop_raw(psets, summary_stream, "PIDSI_CREATE_DTM")
    import_ft = import_ft_raw.get("filetime") if isinstance(import_ft_raw, dict) else None

    # Embedded scan date (PhotoCD 1998 files: 0x28000008 or 0x2300000A)
    scan_dt = None
    scan_time_iso = _get_prop_decoded(psets, img_info_stream, "ScanTime")
    if scan_time_iso is None:
        scan_time_iso = _get_prop_decoded(psets, img_info_stream, "ContentDescriptionDate")
    if isinstance(scan_time_iso, str):
        try:
            scan_dt = timestamps.datetime.datetime.fromisoformat(scan_time_iso)
        except Exception:  # noqa: BLE001
            scan_dt = None

    primary_album = ""
    if entry and entry.get("albums"):
        # Select first non-empty album from album list
        for a in entry["albums"]:
            if a:
                primary_album = a
                break

    resolved_ts = timestamps.resolve_file_timestamps(
        import_ft=import_ft,
        scan_time_dt=scan_dt,
        primary_album=primary_album,
        default_tz=default_tz,
        tz_overrides=tz_overrides,
    )

    ts_dict = {
        "import_timestamp_raw": resolved_ts.import_timestamp_raw,
        "import_datetime": (
            resolved_ts.import_datetime.isoformat() if resolved_ts.import_datetime else None
        ),
        "embedded_scan_datetime": (
            resolved_ts.embedded_scan_datetime.isoformat()
            if resolved_ts.embedded_scan_datetime
            else None
        ),
        "folder_date": (
            resolved_ts.folder_date.isoformat() if resolved_ts.folder_date else None
        ),
        "folder_precision": resolved_ts.folder_precision,
        "date_source": resolved_ts.date_source,
        "date_precision": resolved_ts.date_precision,
        "sort_datetime": (
            resolved_ts.sort_datetime.isoformat() if resolved_ts.sort_datetime else None
        ),
        "datetime_digitized_exif": resolved_ts.datetime_digitized_exif,
        "datetime_original_exif": resolved_ts.datetime_original_exif,
        "timezone_name": resolved_ts.timezone_name,
        "offset_time_digitized": resolved_ts.offset_time_digitized,
        "offset_time_original": resolved_ts.offset_time_original,
    }

    # IPTC Keywords & Captions
    albums_list = entry.get("albums", []) if entry else []
    iptc_keywords = sorted({a for a in albums_list if a})
    caption_title: str | None = None
    if entry and entry.get("preferred_name_is_human_authored"):
        caption_title = naming.strip_fpx_suffix(entry.get("preferred_name", ""))

    return {
        "image_dimensions": dims_dict,
        "colour_space": colour_dict,
        "viewing_transform": transform_dict,
        "camera": cam_dict,
        "scanner": scanner_dict,
        "timestamps": ts_dict,
        "iptc_keywords": iptc_keywords,
        "caption_title": caption_title,
    }


def build_sidecar_dict(
    extracted: ExtractedMetadata,
    manifest_entry: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the complete raw JSON sidecar document matching requirement 17."""
    return {
        "sidecar_version": 1,
        "sha256": manifest_entry.get("sha256", extracted.sha256),
        "size": manifest_entry.get("size", 0),
        "store_name": manifest_entry.get("store_name", extracted.store_name),
        "preferred_name": manifest_entry.get("preferred_name", extracted.store_name),
        "preferred_relpath": manifest_entry.get("preferred_relpath", extracted.store_name),
        "preferred_name_is_human_authored": manifest_entry.get(
            "preferred_name_is_human_authored", False
        ),
        "albums": manifest_entry.get("albums", []),
        "trees": manifest_entry.get("trees", []),
        "duplicate_count": manifest_entry.get("duplicate_count", 1),
        "contributing_sources": manifest_entry.get("sources", []),
        "stream_inventory": extracted.stream_inventory,
        "property_sets": extracted.property_sets,
        "extension_storages": extracted.extension_storages,
        "derived_metadata": extracted.derived,
        "extraction_errors": extracted.errors,
    }


@dataclass
class SidecarDumpReport:
    total_entries: int
    written: int
    skipped: int
    failures: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def dump_sidecars(
    manifest: dict[str, Any],
    *,
    fpx_dir: Path,
    output_dir: Path,
    source_root: Path,
    dry_run: bool = False,
    default_tz: str = timestamps.DEFAULT_TZ,
    tz_overrides: dict[str, str] | None = None,
) -> SidecarDumpReport:
    """Extract metadata and write `.fpx.json` sidecars for all entries in manifest."""
    output_dir = config.ensure_outside_source(output_dir, source_root, "sidecar output directory")
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    entries = manifest.get("entries", [])
    report = SidecarDumpReport(total_entries=len(entries), written=0, skipped=0)

    for entry in entries:
        store_name = entry["store_name"]
        fpx_path = fpx_dir / store_name
        sidecar_path = output_dir / f"{store_name}.json"

        if not fpx_path.is_file():
            # Try finding via preferred_relpath under source_root
            alt_path = source_root / entry["preferred_relpath"]
            if alt_path.is_file():
                fpx_path = alt_path
            else:
                report.failures.append((store_name, f"source .fpx not found at {fpx_path}"))
                continue

        try:
            extracted = extract_fpx_metadata(
                fpx_path,
                manifest_entry=entry,
                default_tz=default_tz,
                tz_overrides=tz_overrides,
            )
            sidecar_dict = build_sidecar_dict(extracted, entry)

            if not dry_run:
                sidecar_path.write_text(
                    json.dumps(sidecar_dict, indent=2, ensure_ascii=True) + "\n",
                    encoding="utf-8",
                )
            report.written += 1

        except Exception as exc:  # noqa: BLE001
            report.failures.append((store_name, f"extraction failed: {exc}"))

    return report
