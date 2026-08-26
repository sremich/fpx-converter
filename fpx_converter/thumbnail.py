"""Embedded DIB thumbnail extractor and image correlation oracle.

Extracts the 24-bit CF_DIB thumbnail from root `\\x05SummaryInformation` PID 17
(`PIDSI_THUMBNAIL`). The thumbnail is stored in the authoring application
already rotated and cropped, making it an orientation and correctness oracle.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import olefile
from PIL import Image

from . import propset

# CF_DIB format constant in Windows clipboard spec
CF_DIB = 8
BI_RGB = 0


class ThumbnailError(RuntimeError):
    """Raised when the embedded thumbnail is missing or malformed."""


def extract_thumbnail_from_bytes(cf_data: bytes) -> Image.Image:
    """Decode a 24-bit CF_DIB payload from raw VT_CF bytes.

    Layout:
      +0   int32   -1 (0xFFFFFFFF) -> standard clipboard format
      +4   uint32  8 (CF_DIB)
      +8   BITMAPINFOHEADER (biSize=40, biWidth, biHeight, biPlanes=1,
                            biBitCount=24, biCompression=0)
      +48  pixel bytes (BGR, bottom-up rows padded to 4-byte boundary)
    """
    if len(cf_data) < 48:
        raise ThumbnailError(f"VT_CF data too short ({len(cf_data)} bytes < 48)")

    fmt_tag, fmt_val = struct.unpack_from("<iI", cf_data, 0)
    if fmt_val != CF_DIB:
        raise ThumbnailError(f"Expected CF_DIB (8), got tag={fmt_tag}, val={fmt_val}")

    bi_size, bi_w, bi_h, bi_planes, bi_bpp, bi_comp = struct.unpack_from("<IiiHHI", cf_data, 8)
    if bi_size != 40:
        raise ThumbnailError(f"Unsupported DIB header size: {bi_size}")
    if bi_bpp != 24:
        raise ThumbnailError(f"Unsupported bit depth: {bi_bpp} bpp (expected 24)")
    if bi_comp != BI_RGB:
        raise ThumbnailError(f"Unsupported compression: {bi_comp} (expected BI_RGB 0)")
    if bi_w <= 0 or bi_h == 0:
        raise ThumbnailError(f"Invalid dimensions: {bi_w}x{bi_h}")

    is_bottom_up = bi_h > 0
    height = abs(bi_h)
    width = bi_w

    stride = ((width * 3 + 3) // 4) * 4
    expected_data_len = stride * height
    pixel_data = cf_data[8 + bi_size :]

    if len(pixel_data) < expected_data_len:
        raise ThumbnailError(
            f"Truncated pixel data: got {len(pixel_data)} bytes, expected {expected_data_len}"
        )

    # Reconstruct RGB image from BGR padded rows
    # Pre-allocate numpy array of shape (height, width, 3)
    img_array = np.zeros((height, width, 3), dtype=np.uint8)

    for row_idx in range(height):
        # In bottom-up DIBs, row 0 in pixel_data is the bottom row of the visual image
        target_row = (height - 1 - row_idx) if is_bottom_up else row_idx
        row_offset = row_idx * stride
        row_bytes = pixel_data[row_offset : row_offset + width * 3]
        # Reshape row into (width, 3) BGR and flip to RGB
        bgr_row = np.frombuffer(row_bytes, dtype=np.uint8).reshape((width, 3))
        img_array[target_row, :, :] = bgr_row[:, ::-1]

    return Image.fromarray(img_array, mode="RGB")


def extract_thumbnail(fpx_source: Path | str | olefile.OleFileIO) -> Image.Image:
    """Extract the embedded thumbnail from an `.fpx` file or open OleFileIO."""
    if isinstance(fpx_source, olefile.OleFileIO):
        return _extract_from_ole(fpx_source)

    fpx_path = Path(fpx_source)
    if not fpx_path.is_file():
        raise ThumbnailError(f"File not found: {fpx_path}")

    with olefile.OleFileIO(str(fpx_path)) as ole:
        return _extract_from_ole(ole)


def _extract_from_ole(ole: olefile.OleFileIO) -> Image.Image:
    stream_name = "\x05SummaryInformation"
    if not ole.exists(stream_name):
        raise ThumbnailError("Stream \\x05SummaryInformation missing from OLE container")

    with ole.openstream(stream_name) as handle:
        raw_bytes = handle.read()

    pset = propset.parse_propset(raw_bytes, stream_name=stream_name)
    # Search for PID 17 (PIDSI_THUMBNAIL)
    for sec in pset.sections:
        if 17 in sec.properties:
            prop = sec.properties[17]
            if isinstance(prop.raw_value, dict) and "raw_bytes" in prop.raw_value:
                return extract_thumbnail_from_bytes(prop.raw_value["raw_bytes"])

    raise ThumbnailError("PIDSI_THUMBNAIL (PID 17) not found in \\x05SummaryInformation")


def compute_image_correlation(img1: Image.Image, img2: Image.Image) -> float:
    """Compute the Pearson correlation coefficient between two images.

    Both images are normalized to 64x64 greyscale vectors.
    Returns a float in [-1.0, 1.0]. A score of +0.97 to +1.0 indicates
    strong pixel agreement and matching visual orientation.
    """
    thumb1 = img1.convert("L").resize((64, 64), Image.Resampling.BILINEAR)
    thumb2 = img2.convert("L").resize((64, 64), Image.Resampling.BILINEAR)

    arr1 = np.asarray(thumb1, dtype=np.float32).ravel()
    arr2 = np.asarray(thumb2, dtype=np.float32).ravel()

    diff1 = arr1 - np.mean(arr1)
    diff2 = arr2 - np.mean(arr2)

    std1 = np.sqrt(np.sum(diff1**2))
    std2 = np.sqrt(np.sum(diff2**2))

    if std1 < 1e-6 or std2 < 1e-6:
        # One of the images is solid flat / zero variance
        return 0.0

    corr = float(np.sum(diff1 * diff2) / (std1 * std2))
    return max(-1.0, min(1.0, corr))
