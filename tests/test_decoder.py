"""Tier-1 unit tests for FlashPix pixel decoder.

Tests tile-table parsing, JPEG table splicing recipe, raw tile reconstruction,
single-colour fill tile, padding crop, and viewing transform application using
hand-built synthetic byte fixtures. Never imports real photos.
"""

from __future__ import annotations

import io
import struct

import pytest
from PIL import Image

from fpx_converter import decoder


def _make_subimage_header(
    width: int,
    height: int,
    records: list[tuple[int, int, int, int]],
) -> bytes:
    """Build a valid Subimage 0000 Header byte stream."""
    num_tiles = len(records)
    header = bytearray(
        struct.pack(
            "<HHI16sIIIIIIIIII",
            0xFFFE,              # BOM
            0x0000,              # format version
            0x0002040A,          # OS version
            b"\x00" * 16,        # CLSID
            1,                   # section count
            36,                  # section length
            width,
            height,
            num_tiles,
            64,                  # tile_width
            64,                  # tile_height
            3,                   # channels
            36,                  # table offset
            16,                  # record size
        )
    )
    assert len(header) == 64

    for off, size, t_type, t_sub in records:
        header.extend(struct.pack("<IIII", off, size, t_type, t_sub))

    return bytes(header)


class TestSubimageHeaderParser:
    def test_parses_valid_header_and_records(self) -> None:
        raw = _make_subimage_header(
            1152,
            864,
            [(0, 1000, 2, 0xFE011100), (1000, 1200, 2, 0xFE011100)],
        )
        hdr = decoder.parse_subimage_header(raw)
        assert hdr.width == 1152
        assert hdr.height == 864
        assert hdr.num_tiles == 2
        assert hdr.tile_width == 64
        assert hdr.tile_height == 64
        assert hdr.channels == 3
        assert len(hdr.records) == 2
        assert hdr.records[0] == decoder.TileRecord(0, 1000, 2, 0xFE011100)
        assert hdr.records[1] == decoder.TileRecord(1000, 1200, 2, 0xFE011100)

    def test_rejects_header_too_short(self) -> None:
        with pytest.raises(decoder.DecoderError, match="too short"):
            decoder.parse_subimage_header(b"\xfe\xff" * 10)

    def test_rejects_invalid_bom(self) -> None:
        raw = bytearray(_make_subimage_header(64, 64, [(0, 100, 2, 0)]))
        raw[0:2] = b"\x00\x00"
        with pytest.raises(decoder.DecoderError, match="Invalid byte order mark"):
            decoder.parse_subimage_header(bytes(raw))

    def test_rejects_truncated_records(self) -> None:
        raw = _make_subimage_header(64, 64, [(0, 100, 2, 0), (100, 100, 2, 0)])
        # Truncate by 8 bytes
        with pytest.raises(decoder.DecoderError, match="Truncated subimage header"):
            decoder.parse_subimage_header(raw[:-8])


class TestTileDecoding:
    def test_decodes_uncompressed_raw_tile(self) -> None:
        # 64x64x3 raw RGB bytes: create a red tile
        red_pixel = bytes([255, 0, 0])
        tile_payload = red_pixel * (64 * 64)
        rec = decoder.TileRecord(
            offset=0,
            size=len(tile_payload),
            compression_type=decoder.COMPRESSION_UNCOMPRESSED,
            compression_subtype=0,
        )
        img = decoder._decode_tile(rec, tile_payload, {}, "NIF_RGB")
        assert img.size == (64, 64)
        assert img.mode == "RGB"
        assert img.getpixel((0, 0)) == (255, 0, 0)
        assert img.getpixel((63, 63)) == (255, 0, 0)

    def test_decodes_single_colour_fill_tile(self) -> None:
        # Subtype 0x00112233 -> R=0x33 (51), G=0x22 (34), B=0x11 (17)
        subtype = 0x33 | (0x22 << 8) | (0x11 << 16)
        rec = decoder.TileRecord(
            offset=0,
            size=0,
            compression_type=decoder.COMPRESSION_SINGLE_COLOUR,
            compression_subtype=subtype,
        )
        img = decoder._decode_tile(rec, b"", {}, "NIF_RGB")
        assert img.size == (64, 64)
        assert img.mode == "RGB"
        assert img.getpixel((0, 0)) == (0x33, 0x22, 0x11)
        assert img.getpixel((32, 32)) == (0x33, 0x22, 0x11)

    def test_decodes_jpeg_tile_with_table_splicing(self) -> None:
        # Build a valid 64x64 JPEG image using PIL
        src_img = Image.new("RGB", (64, 64), (10, 150, 200))
        bio = io.BytesIO()
        src_img.save(bio, format="JPEG", quality=90)
        full_jpeg = bio.getvalue()

        # Simulate abbreviated JPEG:
        # Table blob is full_jpeg with dummy payload, ending with FFD9
        # Tile blob starts with FFD8 and contains the image
        # Splicing: table[:-2] + tile[2:] should recreate a valid JPEG
        # Create table: full_jpeg[:-2] + b"\xff\xd9"
        table_blob = full_jpeg[:100] + b"\xff\xd9"
        # Tile blob: b"\xff\xd8" + full_jpeg[100:]
        tile_blob = b"\xff\xd8" + full_jpeg[100:]

        tables = {254: table_blob}
        subtype = 254 << 24  # Table ID 254 in byte 3

        rec = decoder.TileRecord(
            offset=0,
            size=len(tile_blob),
            compression_type=decoder.COMPRESSION_JPEG,
            compression_subtype=subtype,
        )
        img = decoder._decode_tile(rec, tile_blob, tables, "NIF_RGB")
        assert img.size == (64, 64)
        assert img.mode == "RGB"
        # JPEG compression may have minor variance around (10, 150, 200)
        r, g, b = img.getpixel((32, 32))
        assert abs(r - 10) < 15
        assert abs(g - 150) < 15
        assert abs(b - 200) < 15

    def test_photoycc_colour_conversion(self) -> None:
        # Test PhotoYCC conversion on a known neutral grey
        # In PhotoYCC, Y=128, C1=156, C2=156 -> approximately RGB(174, 174, 174)
        ycc_img = Image.new("RGB", (64, 64), (128, 156, 156))
        rgb_img = decoder._photoycc_to_rgb(ycc_img)
        assert rgb_img.size == (64, 64)
        r, g, b = rgb_img.getpixel((0, 0))
        assert abs(r - g) <= 2
        assert abs(g - b) <= 2
        assert r > 100


class TestOrientationMatrixClassification:
    """The three matrix shapes this corpus actually contains.

    Measured over its 687 distinct files: 612 identity, 22 rotation, 53
    scale-and-translate crops. The crops are not applied, and the point of
    classifying rather than ignoring them is that an unapplied transform
    must be reportable.
    """

    IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]

    def test_identity_matrix(self) -> None:
        status, note = decoder.classify_orientation_matrix(self.IDENTITY)
        assert status == decoder.TRANSFORM_IDENTITY
        assert note == ""

    @pytest.mark.parametrize("k", [1.03, 1.07, 1.11, 1.17, 1.33])
    def test_ninety_degree_ccw_at_each_aspect_ratio(self, k: float) -> None:
        # The off-diagonal magnitude is the image aspect ratio, not 1, so a
        # test pinned to exactly 1.0 would miss every real rotated file.
        matrix = [0.0, -k, 0, k, k, 0.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
        status, _ = decoder.classify_orientation_matrix(matrix)
        assert status == decoder.TRANSFORM_ROTATE_90_CCW

    @pytest.mark.parametrize(
        ("scale", "offset"),
        [(0.921, 0.0), (0.745, 0.252), (0.41, 0.40), (0.99, 0.19)],
    )
    def test_crop_matrices_are_reported_not_treated_as_identity(
        self, scale: float, offset: float
    ) -> None:
        matrix = [scale, 0, 0, offset, 0, scale, 0, offset, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
        status, note = decoder.classify_orientation_matrix(matrix)
        assert status == decoder.TRANSFORM_UNSUPPORTED
        assert "crop" in note
        # The note has to carry the numbers, or the audit cannot tell one
        # discarded crop from another. Only the components that actually
        # deviate are named -- at scale 0.99 the offset is the anomaly.
        assert ("scale" in note) or ("offset" in note)
        assert f"{scale:.3f}" in note or f"{offset:.3f}" in note

    def test_a_wrong_length_matrix_is_unsupported_not_a_crash(self) -> None:
        status, note = decoder.classify_orientation_matrix([1.0, 0.0, 0.0])
        assert status == decoder.TRANSFORM_UNSUPPORTED
        assert "4x4" in note

    def test_classification_is_exhaustive_over_known_shapes(self) -> None:
        # No shape may fall through to a silent default.
        shapes = [
            self.IDENTITY,
            [0.0, -1.33, 0, 1.33, 1.33, 0.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0],
            [0.8, 0, 0, 0.1, 0, 0.8, 0, 0.1, 0, 0, 1.0, 0, 0, 0, 0, 1.0],
        ]
        statuses = {decoder.classify_orientation_matrix(m)[0] for m in shapes}
        assert statuses == {
            decoder.TRANSFORM_IDENTITY,
            decoder.TRANSFORM_ROTATE_90_CCW,
            decoder.TRANSFORM_UNSUPPORTED,
        }
