"""Tier-1 unit tests for thumbnail extractor and correlation oracle.

Uses hand-built byte fixtures with known pixel layouts. Never imports real photos.
"""

from __future__ import annotations

import struct

import pytest
from PIL import Image

from fpx_converter import thumbnail

PixelGrid = list[list[tuple[int, int, int]]]


def _make_dib_bytes(width: int, height: int, pixels_bgr: PixelGrid) -> bytes:
    """Build a valid 24-bit CF_DIB byte stream from a 2D grid of visual (top-down) BGR pixels."""
    bi_size = 40
    bi_planes = 1
    bi_bpp = 24
    bi_comp = 0  # BI_RGB

    header = bytearray(
        struct.pack(
            "<iIIiiHHIIiiII",
            -1,                  # format tag
            thumbnail.CF_DIB,    # 8 = CF_DIB
            bi_size,             # 40 bytes
            width,
            height,              # positive -> bottom-up
            bi_planes,
            bi_bpp,
            bi_comp,
            0,                   # biSizeImage
            0,                   # biXPelsPerMeter
            0,                   # biYPelsPerMeter
            0,                   # biClrUsed
            0,                   # biClrImportant
        )
    )
    # Total header is 8 + 40 = 48 bytes
    assert len(header) == 48

    stride = ((width * 3 + 3) // 4) * 4
    pixel_bytes = bytearray()

    # DIB rows are stored bottom-up, so start from the last visual row
    for row_idx in reversed(range(height)):
        row_data = bytearray()
        for col_idx in range(width):
            b, g, r = pixels_bgr[row_idx][col_idx]
            row_data.extend([b, g, r])
        # Pad to stride
        padding = stride - len(row_data)
        row_data.extend(b"\x00" * padding)
        pixel_bytes.extend(row_data)

    header.extend(pixel_bytes)
    return bytes(header)


class TestThumbnailExtractor:
    def test_decodes_known_2x2_bottom_up_dib(self) -> None:
        # Visual layout:
        # Row 0 (top):    Red (RGB 255,0,0 / BGR 0,0,255), Green (RGB 0,255,0 / BGR 0,255,0)
        # Row 1 (bottom): Blue (RGB 0,0,255 / BGR 255,0,0), White (RGB 255,255,255)
        pixels = [
            [(0, 0, 255), (0, 255, 0)],
            [(255, 0, 0), (255, 255, 255)],
        ]
        dib_data = _make_dib_bytes(2, 2, pixels)
        img = thumbnail.extract_thumbnail_from_bytes(dib_data)

        assert img.size == (2, 2)
        assert img.mode == "RGB"
        assert img.getpixel((0, 0)) == (255, 0, 0)      # Top-left Red
        assert img.getpixel((1, 0)) == (0, 255, 0)      # Top-right Green
        assert img.getpixel((0, 1)) == (0, 0, 255)      # Bottom-left Blue
        assert img.getpixel((1, 1)) == (255, 255, 255)  # Bottom-right White

    def test_handles_4_byte_row_stride_padding_on_odd_width(self) -> None:
        # 3x2 image: width=3, 3*3=9 bytes per row, padded to 12 bytes
        pixels = [
            [(10, 20, 30), (40, 50, 60), (70, 80, 90)],
            [(100, 110, 120), (130, 140, 150), (160, 170, 180)],
        ]
        dib_data = _make_dib_bytes(3, 2, pixels)
        img = thumbnail.extract_thumbnail_from_bytes(dib_data)

        assert img.size == (3, 2)
        assert img.getpixel((0, 0)) == (30, 20, 10)     # BGR (10,20,30) -> RGB (30,20,10)
        assert img.getpixel((2, 0)) == (90, 80, 70)     # BGR (70,80,90) -> RGB (90,80,70)
        assert img.getpixel((0, 1)) == (120, 110, 100)
        assert img.getpixel((2, 1)) == (180, 170, 160)

    def test_rejects_truncated_data(self) -> None:
        with pytest.raises(thumbnail.ThumbnailError, match="too short"):
            thumbnail.extract_thumbnail_from_bytes(b"\x00" * 20)

    def test_rejects_invalid_clipboard_format(self) -> None:
        header = bytearray(b"\xff\xff\xff\xff\x03\x00\x00\x00" + b"\x00" * 40)
        with pytest.raises(thumbnail.ThumbnailError, match="Expected CF_DIB"):
            thumbnail.extract_thumbnail_from_bytes(bytes(header))

    def test_rejects_non_24bpp_depth(self) -> None:
        header = struct.pack(
            "<iIIiiHHIIiiII",
            -1, thumbnail.CF_DIB, 40, 10, 10, 1, 8, 0, 0, 0, 0, 0, 0,
        )
        with pytest.raises(thumbnail.ThumbnailError, match="Unsupported bit depth: 8"):
            thumbnail.extract_thumbnail_from_bytes(header)


class TestImageCorrelation:
    def test_identical_images_have_unit_correlation(self) -> None:
        img = Image.new("RGB", (64, 64), (128, 64, 32))
        # Add some variation so std > 0
        img.putpixel((10, 10), (255, 255, 255))
        img.putpixel((50, 50), (0, 0, 0))
        corr = thumbnail.compute_image_correlation(img, img)
        assert pytest.approx(corr, abs=1e-4) == 1.0

    def test_inverted_image_has_negative_correlation(self) -> None:
        # Build gradient image
        img1 = Image.linear_gradient("L").convert("RGB")
        img2 = Image.eval(img1, lambda x: 255 - x)
        corr = thumbnail.compute_image_correlation(img1, img2)
        assert corr < -0.99

    def test_solid_flat_image_returns_zero_without_error(self) -> None:
        img1 = Image.new("RGB", (64, 64), (100, 100, 100))
        img2 = Image.new("RGB", (64, 64), (200, 200, 200))
        corr = thumbnail.compute_image_correlation(img1, img2)
        assert corr == 0.0
