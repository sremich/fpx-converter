"""Tier-1 unit tests for custom OLE property-set parser over hand-built bytes.

No real photos, no external tools, no source archive. Tests construct byte
streams from scratch and assert decoding of all FlashPix types, composite
variants, and malformed/hostile inputs.
"""

from __future__ import annotations

import datetime
import struct
import uuid

import pytest

from fpx_converter import propset


def _build_propset_bytes(
    fmtid_hex: str,
    properties: list[tuple[int, int, bytes]],  # (pid, type_code, raw_bytes_after_type)
) -> bytes:
    """Helper to construct a valid OLE property set byte stream with 1 section."""
    fmtid_bytes = bytes.fromhex(fmtid_hex)
    assert len(fmtid_bytes) == 16

    # Section layout:
    # cb_section (4B) + cprops (4B) + cprops * (pid (4B) + off (4B)) + prop payloads
    cprops = len(properties)
    hdr_size = 8 + cprops * 8

    prop_entries: list[tuple[int, int, bytes]] = []
    current_off = hdr_size
    for pid, type_code, payload in properties:
        # Each property starts with dwType (4B) followed by payload
        full_val = struct.pack("<I", type_code) + payload
        prop_entries.append((pid, current_off, full_val))
        current_off += len(full_val)

    cb_section = current_off
    section_bytes = bytearray(struct.pack("<II", cb_section, cprops))
    for pid, off, _ in prop_entries:
        section_bytes.extend(struct.pack("<II", pid, off))
    for _, _, full_val in prop_entries:
        section_bytes.extend(full_val)

    # Stream layout:
    # wByteOrder (2B) + wFormat (2B) + dwOSVer (4B) + clsid (16B) + cSections (4B)
    # + fmtid (16B) + dwOffset (4B) + section_bytes
    sec_offset = 28 + 20
    header = bytearray()
    header.extend(struct.pack("<HHI", 0xFFFE, 0, 0x00020004))
    header.extend(b"\x00" * 16)  # CLSID
    header.extend(struct.pack("<I", 1))  # 1 section
    header.extend(fmtid_bytes)
    header.extend(struct.pack("<I", sec_offset))
    header.extend(section_bytes)

    return bytes(header)


class TestPropsetScalarTypes:
    def test_parses_integer_types(self) -> None:
        props = [
            (2, propset.VT_I2, struct.pack("<h", -42)),
            (3, propset.VT_UI2, struct.pack("<H", 65500)),
            (4, propset.VT_I4, struct.pack("<i", -1234567)),
            (5, propset.VT_UI4, struct.pack("<I", 3000000000)),
            (6, propset.VT_BOOL, struct.pack("<h", 1)),
        ]
        raw = _build_propset_bytes(propset.FMTID_GLOBAL_INFO, props)
        parsed = propset.parse_propset(raw, stream_name="test_integers")
        assert parsed.ok
        assert len(parsed.sections) == 1
        sec = parsed.sections[0]
        assert sec.properties[2].decoded_value == -42
        assert sec.properties[3].decoded_value == 65500
        assert sec.properties[4].decoded_value == -1234567
        assert sec.properties[5].decoded_value == 3000000000
        assert sec.properties[6].decoded_value is True

    def test_parses_float_types(self) -> None:
        props = [
            (2, propset.VT_R4, struct.pack("<f", 3.14159)),
            (3, propset.VT_R8, struct.pack("<d", 2.718281828459)),
        ]
        raw = _build_propset_bytes(propset.FMTID_TRANSFORM, props)
        parsed = propset.parse_propset(raw)
        assert parsed.ok
        sec = parsed.sections[0]
        assert pytest.approx(sec.properties[2].decoded_value, 1e-4) == 3.14159
        assert pytest.approx(sec.properties[3].decoded_value, 1e-8) == 2.718281828459

    def test_parses_strings_lpstr_and_lpwstr(self) -> None:
        latin_text = b"Picture Easy Software\x00"
        utf16_text = "Eastman Kodak Company\x00".encode("utf-16-le")

        kodak_text = "Eastman Kodak Company\x00"
        props = [
            (18, propset.VT_LPSTR, struct.pack("<I", len(latin_text)) + latin_text),
            (
                0x24000000,
                propset.VT_LPWSTR,
                struct.pack("<I", len(kodak_text)) + utf16_text,
            ),
        ]
        raw = _build_propset_bytes(propset.FMTID_IMAGE_INFO, props)
        parsed = propset.parse_propset(raw)
        assert parsed.ok
        sec = parsed.sections[0]
        assert sec.properties[18].decoded_value == "Picture Easy Software"
        assert sec.properties[0x24000000].decoded_value == "Eastman Kodak Company"
        assert sec.properties[0x24000000].name == "CameraManufacturerName"

    def test_parses_filetime_as_naive_local_time(self) -> None:
        # 2002-07-18 14:01:34 -> FILETIME representation
        dt_target = datetime.datetime(2002, 7, 18, 14, 1, 34)
        ft_val = int((dt_target - propset.FT_EPOCH).total_seconds() * 10_000_000)

        props = [
            (12, propset.VT_FILETIME, struct.pack("<Q", ft_val)),
        ]
        raw = _build_propset_bytes(propset.FMTID_SUMMARY_INFORMATION, props)
        parsed = propset.parse_propset(raw)
        assert parsed.ok
        sec = parsed.sections[0]
        prop = sec.properties[12]
        assert prop.name == "PIDSI_CREATE_DTM"
        assert prop.decoded_value == "2002-07-18T14:01:34"

    def test_parses_clsid(self) -> None:
        test_guid = uuid.UUID("56616700-c154-11ce-8553-00aa00a1f95b")
        props = [
            (0x00010000, propset.VT_CLSID, test_guid.bytes_le),
        ]
        raw = _build_propset_bytes(propset.FMTID_OPERATION, props)
        parsed = propset.parse_propset(raw)
        assert parsed.ok
        sec = parsed.sections[0]
        assert sec.properties[0x00010000].decoded_value == test_guid.bytes_le.hex()


class TestPropsetVectorsAndBlobs:
    def test_parses_vector_r4_orientation_matrix(self) -> None:
        matrix_16 = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        payload = bytearray(struct.pack("<I", 16))
        for val in matrix_16:
            payload.extend(struct.pack("<f", val))

        props = [
            (0x10000003, propset.VT_VECTOR | propset.VT_R4, bytes(payload)),
        ]
        raw = _build_propset_bytes(propset.FMTID_TRANSFORM, props)
        parsed = propset.parse_propset(raw)
        assert parsed.ok
        sec = parsed.sections[0]
        prop = sec.properties[0x10000003]
        assert prop.name == "SpatialOrientationMatrix"
        assert prop.type_name == "VT_VECTOR|VT_R4"
        assert len(prop.decoded_value) == 16
        assert prop.decoded_value[0] == 1.0

    def test_parses_vector_lpwstr(self) -> None:
        path1 = "/viewpedigree 86240060971BCCD8\x00".encode("utf-16-le")
        payload = bytearray(struct.pack("<I", 1))  # 1 element
        payload.extend(struct.pack("<I", len(path1) // 2))
        payload.extend(path1)
        # Pad to 4-byte boundary if needed
        while len(payload) % 4 != 0:
            payload.append(0)

        props = [
            (0x00011000, propset.VT_VECTOR | propset.VT_LPWSTR, bytes(payload)),
        ]
        raw = _build_propset_bytes(propset.FMTID_EXTENSION_LIST, props)
        parsed = propset.parse_propset(raw)
        assert parsed.ok
        sec = parsed.sections[0]
        prop = sec.properties[0x00011000]
        assert prop.name == "StorageStreamPathnames"
        assert prop.decoded_value == ["/viewpedigree 86240060971BCCD8"]

    def test_parses_subimage_color_blob(self) -> None:
        # NIF RGB colour descriptor (20 bytes)
        blob = struct.pack("<5I", 1, 3, 0x00030000, 0x00030001, 0x00030002)
        payload = struct.pack("<I", len(blob)) + blob

        props = [
            (0x02000002, propset.VT_BLOB, payload),
        ]
        raw = _build_propset_bytes(propset.FMTID_IMAGE_CONTENTS, props)
        parsed = propset.parse_propset(raw)
        assert parsed.ok
        sec = parsed.sections[0]
        prop = sec.properties[0x02000002]
        assert prop.name == "Res0_SubimageColor"
        assert prop.decoded_value["colour_space"] == "NIF_RGB"
        assert prop.decoded_value["channel_count"] == 3

    def test_parses_cf_dib_thumbnail(self) -> None:
        # CF_DIB thumbnail: dwSize, -1, tag=8, 40-byte BITMAPINFOHEADER + 100 bytes dummy pixels
        dib_header = struct.pack("<IiiHHIIiiII", 40, 96, 72, 1, 24, 0, 100, 0, 0, 0, 0)
        cf_body = struct.pack("<iI", -1, 8) + dib_header + b"\x00" * 100
        payload = struct.pack("<I", len(cf_body)) + cf_body

        props = [
            (17, propset.VT_CF, payload),
        ]
        raw = _build_propset_bytes(propset.FMTID_SUMMARY_INFORMATION, props)
        parsed = propset.parse_propset(raw)
        assert parsed.ok
        sec = parsed.sections[0]
        prop = sec.properties[17]
        assert prop.name == "PIDSI_THUMBNAIL"
        assert prop.decoded_value["cf_type"] == "CF_DIB"
        assert prop.decoded_value["width"] == 96
        assert prop.decoded_value["height"] == 72
        assert prop.decoded_value["bit_depth"] == 24


class TestPropsetVariantAndComposites:
    def test_parses_scalar_vt_variant(self) -> None:
        # VT_VARIANT wrapping a VT_UI4
        inner_type = propset.VT_UI4
        inner_val = struct.pack("<I", 12345)
        variant_payload = struct.pack("<I", inner_type) + inner_val

        props = [
            (0x29000000, propset.VT_VARIANT, variant_payload),
        ]
        raw = _build_propset_bytes(propset.FMTID_IMAGE_INFO, props)
        parsed = propset.parse_propset(raw)
        assert parsed.ok
        sec = parsed.sections[0]
        prop = sec.properties[0x29000000]
        assert prop.name == "FilmExtensionData"
        assert prop.decoded_value == 12345

    def test_parses_vector_vt_variant(self) -> None:
        # Vector of 2 variants: [VT_I4(10), VT_LPSTR("test\0")]
        str_val = b"hello\x00"
        elem1 = struct.pack("<II", propset.VT_I4, 100)
        elem2 = (
            struct.pack("<II", propset.VT_LPSTR, len(str_val))
            + str_val
            + b"\x00" * ((4 - len(str_val) % 4) % 4)
        )

        vector_payload = struct.pack("<I", 2) + elem1 + elem2
        props = [
            (0x29000000, propset.VT_VECTOR | propset.VT_VARIANT, vector_payload),
        ]
        raw = _build_propset_bytes(propset.FMTID_IMAGE_INFO, props)
        parsed = propset.parse_propset(raw)
        assert parsed.ok
        sec = parsed.sections[0]
        prop = sec.properties[0x29000000]
        assert prop.decoded_value == [100, "hello"]


class TestPropsetMalformedAndAdversarialInputs:
    def test_rejects_truncated_stream_less_than_28_bytes(self) -> None:
        parsed = propset.parse_propset(b"\xfe\xff\x00\x00" * 3)
        assert not parsed.ok
        assert any("truncated" in err.lower() for err in parsed.errors)
        assert len(parsed.sections) == 0

    def test_rejects_invalid_byte_order_mark(self) -> None:
        bad_bom = b"\xaa\xbb" + b"\x00" * 30
        parsed = propset.parse_propset(bad_bom)
        assert not parsed.ok
        assert any("byte order" in err.lower() for err in parsed.errors)

    def test_records_error_for_section_offset_out_of_bounds(self) -> None:
        header = bytearray(struct.pack("<HHI", 0xFFFE, 0, 0x00020004))
        header.extend(b"\x00" * 16)
        header.extend(struct.pack("<I", 1))  # 1 section
        header.extend(b"\x01" * 16)  # fmtid
        header.extend(struct.pack("<I", 999999))  # way beyond len(header)
        parsed = propset.parse_propset(bytes(header))
        assert not parsed.ok
        assert len(parsed.sections) == 1
        assert any("beyond stream bounds" in err.lower() for err in parsed.sections[0].errors)

    def test_records_error_for_corrupted_property_offset(self) -> None:
        # Build section where property offset points outside the section
        fmtid_bytes = bytes.fromhex(propset.FMTID_GLOBAL_INFO)
        sec_offset = 48
        header = bytearray(struct.pack("<HHI", 0xFFFE, 0, 0x00020004))
        header.extend(b"\x00" * 16)
        header.extend(struct.pack("<I", 1))
        header.extend(fmtid_bytes)
        header.extend(struct.pack("<I", sec_offset))

        # Section: cb=24, cprops=1, (pid=2, off=500 -> OOB)
        sec = struct.pack("<IIII", 24, 1, 2, 500)
        header.extend(sec)

        parsed = propset.parse_propset(bytes(header))
        assert not parsed.ok
        assert any("out of section bounds" in err.lower() for err in parsed.sections[0].errors)

    def test_handles_unsupported_type_gracefully(self) -> None:
        # Base type 99 is unknown
        props = [
            (2, 99, b"\x00\x00\x00\x00"),
        ]
        raw = _build_propset_bytes(propset.FMTID_GLOBAL_INFO, props)
        parsed = propset.parse_propset(raw)
        assert not parsed.ok
        sec = parsed.sections[0]
        assert any("unsupported base type" in err.lower() for err in sec.errors)
        assert 2 not in sec.properties
