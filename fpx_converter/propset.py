"""Custom OLE property-set parser for FlashPix streams.

Productionized from the milestone-0 inventory spike prototype
(`source-files/inventory/md_propset.py`).

Decodes all 10 FlashPix property sets, extension property sets, and composite
types (`VT_VARIANT`, `VT_VECTOR`, `VT_CF`, `VT_BLOB`, `VT_FILETIME`, strings,
numerics) directly from stream bytes with typed error reporting.
"""

from __future__ import annotations

import datetime
import struct
from dataclasses import dataclass, field
from typing import Any

# =============================================================================
# Variant Type (VT) Codes & Type Names
# =============================================================================

VT_EMPTY = 0
VT_NULL = 1
VT_I2 = 2
VT_I4 = 3
VT_R4 = 4
VT_R8 = 5
VT_CY = 6
VT_DATE = 7
VT_BSTR = 8
VT_ERROR = 10
VT_BOOL = 11
VT_VARIANT = 12
VT_I1 = 16
VT_UI1 = 17
VT_UI2 = 18
VT_UI4 = 19
VT_I8 = 20
VT_UI8 = 21
VT_INT = 22
VT_UINT = 23
VT_LPSTR = 30
VT_LPWSTR = 31
VT_FILETIME = 64
VT_BLOB = 65
VT_STREAM = 66
VT_STORAGE = 67
VT_STREAMED_OBJECT = 68
VT_STORED_OBJECT = 69
VT_BLOB_OBJECT = 70
VT_CF = 71
VT_CLSID = 72

VT_VECTOR = 0x1000
VT_ARRAY = 0x2000

VT_NAMES: dict[int, str] = {
    0: "VT_EMPTY",
    1: "VT_NULL",
    2: "VT_I2",
    3: "VT_I4",
    4: "VT_R4",
    5: "VT_R8",
    6: "VT_CY",
    7: "VT_DATE",
    8: "VT_BSTR",
    10: "VT_ERROR",
    11: "VT_BOOL",
    12: "VT_VARIANT",
    16: "VT_I1",
    17: "VT_UI1",
    18: "VT_UI2",
    19: "VT_UI4",
    20: "VT_I8",
    21: "VT_UI8",
    22: "VT_INT",
    23: "VT_UINT",
    30: "VT_LPSTR",
    31: "VT_LPWSTR",
    64: "VT_FILETIME",
    65: "VT_BLOB",
    66: "VT_STREAM",
    67: "VT_STORAGE",
    68: "VT_STREAMED_OBJECT",
    69: "VT_STORED_OBJECT",
    70: "VT_BLOB_OBJECT",
    71: "VT_CF",
    72: "VT_CLSID",
}

FT_EPOCH = datetime.datetime(1601, 1, 1)

#: Windows code page -> Python codec, for decoding VT_LPSTR byte strings.
#:
#: This corpus uses 1252 in 1,374 sections and 1200 (UTF-16LE) in 4,890.
#: Decoding 1252 as latin-1 -- which is what this parser used to do,
#: unconditionally -- is wrong for exactly one byte range, 0x80-0x9F, and
#: that range holds the curly quotes, en and em dashes, and ellipsis that
#: typed text is full of. latin-1 maps them to C1 control characters, which
#: then travel into XMP and IPTC as unprintable junk.
_CODEPAGE_CODECS: dict[int, str] = {
    874: "cp874",
    932: "cp932",
    936: "gbk",
    949: "cp949",
    950: "cp950",
    1200: "utf-16-le",
    1250: "cp1250",
    1251: "cp1251",
    1252: "cp1252",
    1253: "cp1253",
    1254: "cp1254",
    1255: "cp1255",
    1256: "cp1256",
    1257: "cp1257",
    1258: "cp1258",
    10000: "mac_roman",
    65000: "utf-7",
    65001: "utf-8",
}


def codec_for_codepage(codepage: int | None) -> str:
    """Python codec name for an OLE property-set code page.

    Falls back to cp1252 rather than latin-1: an unlabelled property set
    written by Windows software of this era is far more likely to be 1252,
    and 1252 is a superset of the printable latin-1 range anyway.
    """
    if codepage is None:
        return "cp1252"
    # PID 1 is stored as VT_I2, so code pages above 32767 arrive negative.
    if codepage < 0:
        codepage &= 0xFFFF
    return _CODEPAGE_CODECS.get(codepage, "cp1252")


def typename(type_code: int) -> str:
    """Human-readable variant type name including VECTOR and ARRAY flags."""
    base = type_code & 0x0FFF
    name = VT_NAMES.get(base, f"VT_UNKNOWN_{base}")
    if type_code & VT_VECTOR:
        name = f"VT_VECTOR|{name}"
    if type_code & VT_ARRAY:
        name = f"VT_ARRAY|{name}"
    return name


def filetime_to_dt(ft: int) -> datetime.datetime | None:
    """Convert 64-bit FILETIME integer to naive local datetime.

    Returns None for 0 or out-of-range values. FILETIMEs in this corpus are
    local wall-clock time as stored — no timezone conversion is applied.
    """
    if ft <= 0:
        return None
    try:
        return FT_EPOCH + datetime.timedelta(microseconds=ft // 10)
    except (OverflowError, OSError, ValueError):
        return None


# =============================================================================
# Canonical FMTID and Property Name Mappings
# =============================================================================

FMTID_SUMMARY_INFORMATION = "e0859ff2f94f6810ab9108002b27b3d9"
FMTID_GLOBAL_INFO = "006f615654c1ce11855300aa00a1f95b"
FMTID_EXTENSION_LIST = "1060615654c1ce11855300aa00a1f95b"
FMTID_OPERATION = "006e615654c1ce11855300aa00a1f95b"
FMTID_TRANSFORM = "006a615654c1ce11855300aa00a1f95b"
FMTID_DATA_OBJECT = "8060615654c1ce11855300aa00a1f95b"
FMTID_IMAGE_CONTENTS = "0064615654c1ce11855300aa00a1f95b"
FMTID_IMAGE_INFO = "0065615654c1ce11855300aa00a1f95b"
FMTID_KODAK_PEDIGREE = "01020010c06fd011bd0100609719a180"

KNOWN_PROPERTIES: dict[str, dict[int, str]] = {
    FMTID_SUMMARY_INFORMATION: {
        1: "CODEPAGE",
        2: "PIDSI_TITLE",
        3: "PIDSI_SUBJECT",
        4: "PIDSI_AUTHOR",
        5: "PIDSI_KEYWORDS",
        6: "PIDSI_COMMENTS",
        7: "PIDSI_TEMPLATE",
        8: "PIDSI_LASTAUTHOR",
        9: "PIDSI_REVNUMBER",
        10: "PIDSI_EDITTIME",
        11: "PIDSI_LASTPRINTED",
        12: "PIDSI_CREATE_DTM",
        13: "PIDSI_LASTSAVE_DTM",
        14: "PIDSI_PAGECOUNT",
        15: "PIDSI_WORDCOUNT",
        16: "PIDSI_CHARCOUNT",
        17: "PIDSI_THUMBNAIL",
        18: "PIDSI_APPNAME",
        19: "PIDSI_SECURITY",
    },
    FMTID_GLOBAL_INFO: {
        1: "CODEPAGE",
        0x00010100: "LockedPropertyList",
        0x00010101: "TransformedImageTitle",
        0x00010102: "LastModifier",
        0x00010103: "VisibleOutputs",
    },
    FMTID_EXTENSION_LIST: {
        1: "CODEPAGE",
        0x00010001: "ExtensionName",
        0x00010002: "ExtensionClassID",
        0x00010003: "ExtensionPersistence",
        0x00010004: "ExtensionCreationTime",
        0x00010005: "ExtensionModificationTime",
        0x00010006: "CreatingApplication",
        0x00010007: "ExtensionDescription",
        0x00011000: "StorageStreamPathnames",
        0x00013000: "StreamPathnames",
        0x10000000: "FeatureLevelDescriptor",
    },
    FMTID_OPERATION: {
        1: "CODEPAGE",
        0x00010000: "OperationClassID",
    },
    FMTID_TRANSFORM: {
        1: "CODEPAGE",
        0x00010000: "TransformClassID",
        0x00010001: "OperationClassID",
        0x00010006: "CreationTime",
        0x00010007: "ModificationTime",
        0x00010100: "InputDataObjectIDs",
        0x00010101: "OutputDataObjectIDs",
        0x00010102: "OperationNumber",
        0x10000000: "ResultAspectRatio",
        0x10000001: "RectangleOfInterest",
        0x10000002: "FilteringValue",
        0x10000003: "SpatialOrientationMatrix",
        0x10000004: "ColorTwistMatrix",
        0x10000005: "ContrastAdjustment",
    },
    FMTID_DATA_OBJECT: {
        1: "CODEPAGE",
        0x00010000: "DataObjectDataClassID",
        0x00010006: "DataObjectCreationTime",
        0x00010007: "DataObjectModificationTime",
        0x00010100: "DataObjectStatus",
        0x00010101: "CreatingTransform",
        0x00010102: "UsingTransforms",
        0x10000000: "ImageHeight",
        0x10000001: "ImageWidth",
    },
    FMTID_IMAGE_CONTENTS: {
        1: "CODEPAGE",
        0x01000000: "NumberOfResolutions",
        0x01000002: "HighestResolutionWidth",
        0x01000003: "HighestResolutionHeight",
        0x03000002: "DefaultJPEGTableIndex",
        0x03FE0001: "JPEGTables",
    },
    FMTID_IMAGE_INFO: {
        1: "CODEPAGE",
        0x21000000: "FileSource",
        0x21000001: "SceneType",
        0x21000003: "CreationPath",
        0x2300000A: "ContentDescriptionDate",
        0x24000000: "CameraManufacturerName",
        0x24000001: "CameraModelName",
        0x25000000: "CaptureDate",
        0x27000000: "FilmBrand",
        0x27000001: "FilmSize",
        0x28000000: "ScannerManufacturer",
        0x28000001: "ScannerModel",
        0x28000002: "ScannerSerialNumber",
        0x28000003: "ScanSoftwareRevision",
        0x28000005: "ServiceBureauOrgName",
        0x28000006: "ScanOperatorID",
        0x28000008: "ScanTime",
        0x2800000A: "ScannerPixelSize",
        0x29000000: "FilmExtensionData",
        0x29000002: "FilmProductCode",
    },
    FMTID_KODAK_PEDIGREE: {
        1: "CODEPAGE",
        2: "PedigreeDataBlob",
        3: "PedigreeStatus",
    },
}


def get_property_name(fmtid: str, pid: int) -> str:
    """Return the canonical FlashPix property name, or a formatted PID hex."""
    fmtid_clean = fmtid.lower().replace("-", "")
    known = KNOWN_PROPERTIES.get(fmtid_clean, {})
    if pid in known:
        return known[pid]

    # Handle dynamic ImageContents subimage properties: 0x02RRxxxx and 0x03RRxxxx
    if fmtid_clean == FMTID_IMAGE_CONTENTS:
        high = (pid >> 16) & 0xFFFF
        low = pid & 0xFFFF
        if (high & 0xFF00) == 0x0200:
            res_idx = high & 0x00FF
            suffixes = {
                0x0000: "SubimageWidth",
                0x0001: "SubimageHeight",
                0x0002: "SubimageColor",
                0x0003: "SubimageNumericalFormat",
                0x0004: "SubimageDecimationMethod",
            }
            if low in suffixes:
                return f"Res{res_idx}_{suffixes[low]}"
        elif (high & 0xFF00) == 0x0300 and low == 0x0001:
            res_idx = high & 0x00FF
            return f"Res{res_idx}_JPEGTables"

    return f"PID_0x{pid:08X}"


# =============================================================================
# Structured Parser Data Classes
# =============================================================================


@dataclass
class ParsedProperty:
    pid: int
    pid_hex: str
    name: str
    type_id: int
    type_name: str
    raw_value: Any
    decoded_value: Any


@dataclass
class ParsedSection:
    fmtid: str
    cb: int
    cprops: int
    codepage: int | None
    properties: dict[int, ParsedProperty]
    errors: list[str] = field(default_factory=list)


@dataclass
class ParsedPropertySet:
    stream_name: str
    sections: list[ParsedSection]
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and all(not s.errors for s in self.sections)


# =============================================================================
# Low-Level Value Parsing
# =============================================================================


class PropertyParseError(ValueError):
    """Raised when parsing a typed value fails."""


def _parse_scalar(
    data: bytes, off: int, base_type: int, codepage: int | None = None
) -> tuple[Any, Any, int]:
    """Parse one scalar value of type base_type at offset off.

    Returns (raw_value, decoded_value, bytes_consumed).
    """
    length = len(data)
    if off > length:
        raise PropertyParseError(f"offset {off} exceeds section length {length}")

    if base_type in (VT_EMPTY, VT_NULL):
        return None, None, 0

    if base_type == VT_I2:
        if off + 2 > length:
            raise PropertyParseError("truncated VT_I2")
        val = struct.unpack_from("<h", data, off)[0]
        return val, val, 2

    if base_type == VT_UI2:
        if off + 2 > length:
            raise PropertyParseError("truncated VT_UI2")
        val = struct.unpack_from("<H", data, off)[0]
        return val, val, 2

    if base_type in (VT_I4, VT_INT):
        if off + 4 > length:
            raise PropertyParseError("truncated VT_I4")
        val = struct.unpack_from("<i", data, off)[0]
        return val, val, 4

    if base_type in (VT_UI4, VT_UINT, VT_ERROR):
        if off + 4 > length:
            raise PropertyParseError("truncated VT_UI4")
        val = struct.unpack_from("<I", data, off)[0]
        return val, val, 4

    if base_type == VT_R4:
        if off + 4 > length:
            raise PropertyParseError("truncated VT_R4")
        val = struct.unpack_from("<f", data, off)[0]
        return val, val, 4

    if base_type in (VT_R8, VT_DATE):
        if off + 8 > length:
            raise PropertyParseError("truncated VT_R8")
        val = struct.unpack_from("<d", data, off)[0]
        return val, val, 8

    if base_type == VT_CY:
        if off + 8 > length:
            raise PropertyParseError("truncated VT_CY")
        val = struct.unpack_from("<q", data, off)[0] / 10000.0
        return val, val, 8

    if base_type == VT_BOOL:
        if off + 2 > length:
            raise PropertyParseError("truncated VT_BOOL")
        val = struct.unpack_from("<h", data, off)[0] != 0
        return val, val, 2

    if base_type == VT_I1:
        if off + 1 > length:
            raise PropertyParseError("truncated VT_I1")
        val = struct.unpack_from("<b", data, off)[0]
        return val, val, 1

    if base_type == VT_UI1:
        if off + 1 > length:
            raise PropertyParseError("truncated VT_UI1")
        val = struct.unpack_from("<B", data, off)[0]
        return val, val, 1

    if base_type == VT_I8:
        if off + 8 > length:
            raise PropertyParseError("truncated VT_I8")
        val = struct.unpack_from("<q", data, off)[0]
        return val, val, 8

    if base_type == VT_UI8:
        if off + 8 > length:
            raise PropertyParseError("truncated VT_UI8")
        val = struct.unpack_from("<Q", data, off)[0]
        return val, val, 8

    if base_type == VT_FILETIME:
        if off + 8 > length:
            raise PropertyParseError("truncated VT_FILETIME")
        ft = struct.unpack_from("<Q", data, off)[0]
        dt = filetime_to_dt(ft)
        raw = {"filetime": ft}
        decoded = dt.isoformat() if dt is not None else None
        return raw, decoded, 8

    if base_type in (VT_LPSTR, VT_BSTR):
        if off + 4 > length:
            raise PropertyParseError("truncated VT_LPSTR byte count")
        cb = struct.unpack_from("<I", data, off)[0]
        if off + 4 + cb > length:
            raise PropertyParseError(f"VT_LPSTR cb {cb} exceeds bounds at off {off}")
        raw_bytes = data[off + 4 : off + 4 + cb]
        text = raw_bytes.split(b"\x00")[0].decode(codec_for_codepage(codepage), "replace")
        return raw_bytes.hex(), text, 4 + cb

    if base_type == VT_LPWSTR:
        if off + 4 > length:
            raise PropertyParseError("truncated VT_LPWSTR char count")
        cch = struct.unpack_from("<I", data, off)[0]
        byte_len = cch * 2
        if off + 4 + byte_len > length:
            raise PropertyParseError(f"VT_LPWSTR cch {cch} exceeds bounds at off {off}")
        raw_bytes = data[off + 4 : off + 4 + byte_len]
        text = raw_bytes.decode("utf-16-le", "replace").split("\x00")[0]
        return raw_bytes.hex(), text, 4 + byte_len

    if base_type in (VT_BLOB, VT_BLOB_OBJECT):
        if off + 4 > length:
            raise PropertyParseError("truncated VT_BLOB size")
        cb = struct.unpack_from("<I", data, off)[0]
        if off + 4 + cb > length:
            raise PropertyParseError(f"VT_BLOB cb {cb} exceeds bounds at off {off}")
        blob_bytes = data[off + 4 : off + 4 + cb]
        raw = {"size": cb, "hex_preview": blob_bytes[:32].hex(), "raw_bytes": blob_bytes}
        decoded = _decode_blob_content(blob_bytes)
        return raw, decoded, 4 + cb

    if base_type == VT_CF:
        # dwSize (4 bytes), wFormat (4 bytes), then format data
        if off + 4 > length:
            raise PropertyParseError("truncated VT_CF size")
        cb = struct.unpack_from("<I", data, off)[0]
        if off + 4 + cb > length:
            raise PropertyParseError(f"VT_CF cb {cb} exceeds bounds at off {off}")
        cf_bytes = data[off + 4 : off + 4 + cb]
        format_tag = struct.unpack_from("<i", cf_bytes, 0)[0] if cb >= 4 else 0
        raw = {
            "size": cb,
            "format_tag": format_tag,
            "hex_preview": cf_bytes[:32].hex(),
            "raw_bytes": cf_bytes,
        }
        decoded = _decode_cf_content(cf_bytes)
        return raw, decoded, 4 + cb

    if base_type == VT_CLSID:
        if off + 16 > length:
            raise PropertyParseError("truncated VT_CLSID")
        guid_bytes = data[off : off + 16]
        hex_str = guid_bytes.hex()
        return hex_str, hex_str, 16

    if base_type in (VT_STREAM, VT_STORAGE, VT_STREAMED_OBJECT, VT_STORED_OBJECT):
        if off + 4 > length:
            raise PropertyParseError("truncated storage/stream name length")
        cb = struct.unpack_from("<I", data, off)[0]
        if off + 4 + cb > length:
            raise PropertyParseError("storage/stream name exceeds bounds")
        name_bytes = data[off + 4 : off + 4 + cb]
        text = name_bytes.split(b"\x00")[0].decode(codec_for_codepage(codepage), "replace")
        return name_bytes.hex(), text, 4 + cb

    if base_type == VT_VARIANT:
        # A VT_VARIANT contains its own 4-byte type code, followed by the value
        if off + 4 > length:
            raise PropertyParseError("truncated VT_VARIANT inner type")
        inner_type = struct.unpack_from("<I", data, off)[0]
        inner_raw, inner_dec, inner_consumed = _parse_typed_value(
            data, off + 4, inner_type, codepage
        )
        raw = {
            "variant_type": inner_type,
            "variant_typename": typename(inner_type),
            "raw": inner_raw,
        }
        return raw, inner_dec, 4 + inner_consumed

    raise PropertyParseError(f"unsupported base type {base_type} ({typename(base_type)})")


def _decode_blob_content(blob: bytes) -> Any:
    """Decode known FlashPix binary blobs into structured dicts."""
    cb = len(blob)
    # FlashPix Subimage Color descriptor (20 bytes)
    if cb == 20:
        uncalibrated, ch_count, ch0, ch1, ch2 = struct.unpack_from("<5I", blob, 0)
        channels = [ch0, ch1, ch2]
        space_name = "UNKNOWN"
        if channels == [0x00030000, 0x00030001, 0x00030002]:
            space_name = "NIF_RGB"
        elif channels == [0x00020000, 0x00020001, 0x00020002]:
            space_name = "PhotoYCC"
        return {
            "blob_type": "SubimageColor",
            "uncalibrated": bool(uncalibrated),
            "channel_count": ch_count,
            "channel_ids": [f"0x{c:08X}" for c in channels],
            "colour_space": space_name,
        }

    # JPEG Tables blob (~574 bytes)
    if cb >= 4 and blob.startswith(b"\xff\xd8"):
        return {
            "blob_type": "JPEGTables",
            "length": cb,
            "has_soi": True,
            "has_eoi": blob.endswith(b"\xff\xd9"),
        }

    return {"blob_type": "GenericBlob", "size": cb, "hex_preview": blob[:32].hex()}


def _decode_cf_content(cf_data: bytes) -> Any:
    """Decode clipboard format data, specifically CF_DIB thumbnails."""
    if len(cf_data) < 40:
        return {"cf_type": "GenericCF", "size": len(cf_data)}

    w_format = struct.unpack_from("<i", cf_data, 0)[0]
    # wFormat == -1 (or 0xFFFFFFFF) indicates a Windows clipboard format tag follows
    if w_format == -1 and len(cf_data) >= 8:
        tag = struct.unpack_from("<I", cf_data, 4)[0]
        if tag == 8:  # CF_DIB
            dib_header = cf_data[8:]
            if len(dib_header) >= 40:
                header_size, w, h, planes, bpp = struct.unpack_from("<IiiHH", dib_header, 0)
                return {
                    "cf_type": "CF_DIB",
                    "width": w,
                    "height": h,
                    "bit_depth": bpp,
                    "planes": planes,
                    "dib_size": len(dib_header),
                }

    return {"cf_type": "UnknownCF", "format_code": w_format, "size": len(cf_data)}


def _parse_typed_value(
    data: bytes, off: int, type_code: int, codepage: int | None = None
) -> tuple[Any, Any, int]:
    """Parse a typed value (scalar or vector) at offset off."""
    base_type = type_code & 0x0FFF
    p = off

    if type_code & VT_VECTOR:
        if p + 4 > len(data):
            raise PropertyParseError("truncated vector count")
        count = struct.unpack_from("<I", data, p)[0]
        p += 4
        raw_list: list[Any] = []
        dec_list: list[Any] = []
        for i in range(count):
            if base_type == VT_VARIANT:
                if p + 4 > len(data):
                    raise PropertyParseError(f"truncated VT_VARIANT vector element at {i}")
                elem_type = struct.unpack_from("<I", data, p)[0]
                elem_raw, elem_dec, elem_consumed = _parse_typed_value(
                    data, p + 4, elem_type, codepage
                )
                raw_list.append({"type": elem_type, "raw": elem_raw})
                dec_list.append(elem_dec)
                p += 4 + elem_consumed
            else:
                elem_raw, elem_dec, elem_consumed = _parse_scalar(data, p, base_type, codepage)
                raw_list.append(elem_raw)
                dec_list.append(elem_dec)
                p += elem_consumed

            # Vector elements of variable-length types are 4-byte aligned
            if base_type in (VT_LPSTR, VT_BSTR, VT_LPWSTR, VT_BLOB, VT_BLOB_OBJECT, VT_CF):
                p = (p + 3) & ~3

        return raw_list, dec_list, p - off

    # Scalar value
    raw_val, dec_val, consumed = _parse_scalar(data, p, base_type, codepage)
    return raw_val, dec_val, consumed


# =============================================================================
# Full Property Set Parser
# =============================================================================


def parse_propset(
    data: bytes, stream_name: str = ""
) -> ParsedPropertySet:
    """Parse an OLE property set stream.

    Returns a `ParsedPropertySet` containing all parsed sections, properties,
    and any decoding errors encountered. Never raises unhandled exceptions.
    """
    errors: list[str] = []
    sections: list[ParsedSection] = []

    if len(data) < 28:
        errors.append(f"stream truncated: {len(data)} bytes (minimum 28 required)")
        return ParsedPropertySet(stream_name=stream_name, sections=[], errors=errors)

    bom = struct.unpack_from("<H", data, 0)[0]
    if bom != 0xFFFE:
        errors.append(f"invalid byte order mark 0x{bom:04X} (expected 0xFFFE)")
        return ParsedPropertySet(stream_name=stream_name, sections=[], errors=errors)

    nsec = struct.unpack_from("<I", data, 24)[0]
    sec_entries: list[tuple[bytes, int]] = []
    p = 28
    for i in range(nsec):
        if p + 20 > len(data):
            errors.append(f"truncated section header table at index {i}")
            break
        fmtid_bytes = data[p : p + 16]
        offset = struct.unpack_from("<I", data, p + 16)[0]
        sec_entries.append((fmtid_bytes, offset))
        p += 20

    for fmtid_bytes, sec_off in sec_entries:
        fmtid_hex = fmtid_bytes.hex()
        if sec_off + 8 > len(data):
            sections.append(
                ParsedSection(
                    fmtid=fmtid_hex,
                    cb=0,
                    cprops=0,
                    codepage=None,
                    properties={},
                    errors=[f"section offset {sec_off} beyond stream bounds {len(data)}"],
                )
            )
            continue

        cb_section, cprops = struct.unpack_from("<II", data, sec_off)
        sec_data = (
            data[sec_off : sec_off + cb_section]
            if sec_off + cb_section <= len(data)
            else data[sec_off:]
        )
        sec_errors: list[str] = []
        if sec_off + cb_section > len(data):
            sec_errors.append(
                f"section size {cb_section} extends beyond stream end ({len(data)} bytes)"
            )

        props: dict[int, ParsedProperty] = {}
        codepage: int | None = None

        # Locate CODEPAGE (PID 1) before decoding anything else. It governs
        # how every VT_LPSTR in the section is interpreted, and it is not
        # guaranteed to come first in the property table -- decoding strings
        # as we met them meant the code page was frequently discovered only
        # after it was needed.
        for i in range(cprops):
            hdr_pos = 8 + i * 8
            if hdr_pos + 8 > len(sec_data):
                break
            pid, prop_off = struct.unpack_from("<II", sec_data, hdr_pos)
            if pid != 1 or prop_off + 4 > len(sec_data):
                continue
            try:
                cp_type = struct.unpack_from("<I", sec_data, prop_off)[0]
                _cp_raw, cp_dec, _ = _parse_typed_value(sec_data, prop_off + 4, cp_type)
                if isinstance(cp_dec, int):
                    codepage = cp_dec
            except Exception as exc:  # noqa: BLE001
                sec_errors.append(f"codepage (pid 1): {type(exc).__name__}: {exc}")
            break

        for i in range(cprops):
            hdr_pos = 8 + i * 8
            if hdr_pos + 8 > len(sec_data):
                sec_errors.append(f"property header table truncated at index {i}")
                break

            pid, prop_off = struct.unpack_from("<II", sec_data, hdr_pos)
            if prop_off + 4 > len(sec_data):
                sec_errors.append(f"pid 0x{pid:08X} offset {prop_off} out of section bounds")
                continue

            try:
                type_code = struct.unpack_from("<I", sec_data, prop_off)[0]
                type_lbl = typename(type_code)
                prop_name = get_property_name(fmtid_hex, pid)
                raw_v, dec_v, _ = _parse_typed_value(
                    sec_data, prop_off + 4, type_code, codepage
                )

                props[pid] = ParsedProperty(
                    pid=pid,
                    pid_hex=f"0x{pid:08X}",
                    name=prop_name,
                    type_id=type_code,
                    type_name=type_lbl,
                    raw_value=raw_v,
                    decoded_value=dec_v,
                )


            except Exception as exc:  # noqa: BLE001
                sec_errors.append(f"pid 0x{pid:08X}: {type(exc).__name__}: {exc}")

        sections.append(
            ParsedSection(
                fmtid=fmtid_hex,
                cb=cb_section,
                cprops=cprops,
                codepage=codepage,
                properties=props,
                errors=sec_errors,
            )
        )

    return ParsedPropertySet(stream_name=stream_name, sections=sections, errors=errors)
