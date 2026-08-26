"""Pixel decoder engine for FlashPix (.fpx) resolution pyramids.

Reconstructs images tile-by-tile, handling all 3 tile types (abbreviated JPEG
spliced with external tables, raw 12,288-byte uncompressed RGB, single-colour fill),
per-file colour spaces (NIF RGB vs PhotoYCC), tile stitching, boundary cropping,
and viewing transforms (90° CCW rotation).

Bypasses Pillow's crash-prone `FpxImagePlugin` completely.
"""

from __future__ import annotations

import io
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import olefile
from PIL import Image

from . import propset

# Constant dimensions across all FlashPix files
TILE_WIDTH = 64
TILE_HEIGHT = 64
TILE_CHANNELS = 3
UNCOMPRESSED_TILE_SIZE = TILE_WIDTH * TILE_HEIGHT * TILE_CHANNELS  # 12,288 bytes

# Tile compression types
COMPRESSION_UNCOMPRESSED = 0
COMPRESSION_SINGLE_COLOUR = 1
COMPRESSION_JPEG = 2

# FlashPix data stream preamble length
DATA_PREAMBLE_LEN = 28
HEADER_PREAMBLE_LEN = 64
TILE_RECORD_SIZE = 16


class DecoderError(RuntimeError):
    """Raised when pixel decoding fails due to container or format errors."""


@dataclass
class TileRecord:
    offset: int
    size: int
    compression_type: int
    compression_subtype: int


@dataclass
class SubimageHeader:
    width: int
    height: int
    num_tiles: int
    tile_width: int
    tile_height: int
    channels: int
    records: list[TileRecord]


@dataclass
class DecodedImage:
    image: Image.Image
    declared_width: int
    declared_height: int
    colour_space: str
    resolution_index: int
    rotation_applied: int
    crop_applied: tuple[int, int, int, int] | None


def parse_subimage_header(header_bytes: bytes) -> SubimageHeader:
    """Parse a Subimage 0000 Header stream (64-byte preamble + N*16-byte records)."""
    if len(header_bytes) < HEADER_PREAMBLE_LEN:
        raise DecoderError(
            f"Subimage header too short ({len(header_bytes)} bytes < {HEADER_PREAMBLE_LEN})"
        )

    (
        bom,
        _fmt,
        _os_ver,
    ) = struct.unpack_from("<HHI", header_bytes, 0)
    if bom != 0xFFFE:
        raise DecoderError(f"Invalid byte order mark in subimage header: 0x{bom:04X}")

    (
        _sec_count,
        _sec_len,
        width,
        height,
        num_tiles,
        tile_w,
        tile_h,
        channels,
        _table_off,
        record_size,
    ) = struct.unpack_from("<IIIIIIIIII", header_bytes, 24)

    expected_len = HEADER_PREAMBLE_LEN + num_tiles * TILE_RECORD_SIZE
    if len(header_bytes) < expected_len:
        raise DecoderError(
            f"Truncated subimage header: got {len(header_bytes)} bytes, expected {expected_len}"
        )

    records: list[TileRecord] = []
    offset = HEADER_PREAMBLE_LEN
    for _ in range(num_tiles):
        t_off, t_size, t_type, t_sub = struct.unpack_from("<IIII", header_bytes, offset)
        records.append(
            TileRecord(
                offset=t_off,
                size=t_size,
                compression_type=t_type,
                compression_subtype=t_sub,
            )
        )
        offset += TILE_RECORD_SIZE

    return SubimageHeader(
        width=width,
        height=height,
        num_tiles=num_tiles,
        tile_width=tile_w,
        tile_height=tile_h,
        channels=channels,
        records=records,
    )


def _photoycc_to_rgb(ycc_img: Image.Image) -> Image.Image:
    """Convert a PhotoYCC decoded PIL image to standard sRGB.

    PhotoYCC uses Y, C1, C2 channels (FlashPix / PhotoCD convention).
    """
    arr = np.asarray(ycc_img, dtype=np.float32)
    # arr is (H, W, 3) in [0, 255]
    y = arr[:, :, 0] / 255.0
    c1 = arr[:, :, 1] / 255.0
    c2 = arr[:, :, 2] / 255.0

    # FlashPix / PhotoCD PhotoYCC formula
    # Center chroma around 156/255 = 0.61176
    y_prime = 1.3584 * y
    c1_prime = c1 - 0.61176
    c2_prime = c2 - 0.61176

    r = y_prime + 1.8215 * c2_prime
    g = y_prime - 0.4321 * c1_prime - 0.9286 * c2_prime
    b = y_prime + 2.2179 * c1_prime

    rgb = np.stack([r, g, b], axis=-1) * 255.0
    np.clip(rgb, 0.0, 255.0, out=rgb)
    return Image.fromarray(rgb.astype(np.uint8), mode="RGB")


def _decode_tile(
    tile_rec: TileRecord,
    data_payload: bytes,
    jpeg_tables: dict[int, bytes],
    colour_space: str,
) -> Image.Image:
    """Decode a single 64x64 tile into an RGB PIL Image."""
    t_type = tile_rec.compression_type

    if t_type == COMPRESSION_UNCOMPRESSED:
        # Type 0: 12,288 bytes raw interleaved RGB
        tile_bytes = data_payload[tile_rec.offset : tile_rec.offset + tile_rec.size]
        if len(tile_bytes) < UNCOMPRESSED_TILE_SIZE:
            tile_bytes = tile_bytes.ljust(UNCOMPRESSED_TILE_SIZE, b"\x00")
        return Image.frombytes(
            "RGB", (TILE_WIDTH, TILE_HEIGHT), tile_bytes[:UNCOMPRESSED_TILE_SIZE]
        )

    if t_type == COMPRESSION_SINGLE_COLOUR:
        # Type 1: 0 bytes data, fill colour is in the 4 subtype bytes
        sub = tile_rec.compression_subtype
        r = sub & 0xFF
        g = (sub >> 8) & 0xFF
        b = (sub >> 16) & 0xFF
        return Image.new("RGB", (TILE_WIDTH, TILE_HEIGHT), (r, g, b))

    if t_type == COMPRESSION_JPEG:
        # Type 2: Abbreviated JPEG
        table_id = (tile_rec.compression_subtype >> 24) & 0xFF
        table_blob = jpeg_tables.get(table_id)
        if table_blob is None:
            # Fallback to default table id 254 if available
            table_blob = jpeg_tables.get(254)
        if table_blob is None:
            raise DecoderError(f"Missing JPEG table specification for table id {table_id}")

        tile_bytes = data_payload[tile_rec.offset : tile_rec.offset + tile_rec.size]
        if len(tile_bytes) < 4:
            raise DecoderError(f"JPEG tile data too short ({len(tile_bytes)} bytes)")

        # Splice recipe: strip trailing FFD9 from tables, drop leading FFD8 from tile
        jpeg_full = table_blob[:-2] + tile_bytes[2:]

        try:
            with Image.open(io.BytesIO(jpeg_full)) as tile_im:
                tile_im.load()
                tile_rgb = tile_im.convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise DecoderError(f"JPEG tile decompression failed: {exc}") from exc

        if colour_space == "PhotoYCC":
            return _photoycc_to_rgb(tile_rgb)

        return tile_rgb

    raise DecoderError(f"Unknown tile compression type: {t_type}")


def decode_fpx(
    fpx_source: Path | str | olefile.OleFileIO,
    resolution_index: int | None = None,
    apply_transform: bool = True,
) -> DecodedImage:
    """Decode a FlashPix image at the specified resolution (defaults to highest)."""
    if isinstance(fpx_source, olefile.OleFileIO):
        return _decode_from_ole(fpx_source, resolution_index, apply_transform)

    fpx_path = Path(fpx_source)
    if not fpx_path.is_file():
        raise DecoderError(f"File not found: {fpx_path}")

    with olefile.OleFileIO(str(fpx_path)) as ole:
        return _decode_from_ole(ole, resolution_index, apply_transform)


def _decode_from_ole(
    ole: olefile.OleFileIO,
    resolution_index: int | None,
    apply_transform: bool,
) -> DecodedImage:
    # 1. Read Image Contents property set to find resolutions and JPEG tables
    img_contents_name = "Data Object Store 000001/\x05Image Contents"
    if not ole.exists(img_contents_name):
        raise DecoderError(f"Missing required stream: {img_contents_name}")

    with ole.openstream(img_contents_name) as handle:
        img_contents_bytes = handle.read()

    pset = propset.parse_propset(img_contents_bytes, stream_name=img_contents_name)
    props: dict[int, Any] = {}
    for sec in pset.sections:
        for pid, prop in sec.properties.items():
            props[pid] = prop.decoded_value

    num_resolutions = props.get(0x01000000, 1)
    if resolution_index is None:
        resolution_index = num_resolutions - 1

    if resolution_index < 0 or resolution_index >= num_resolutions:
        raise DecoderError(
            f"Invalid resolution index {resolution_index} (available: 0..{num_resolutions - 1})"
        )

    # 2. Extract JPEG tables: 0x03TT0001 (VT_BLOB)
    jpeg_tables: dict[int, bytes] = {}
    for sec in pset.sections:
        for pid, prop in sec.properties.items():
            # Check if PID matches 0x03TT0001
            if (pid & 0xFF00FFFF) == 0x03000001:
                table_id = (pid >> 16) & 0xFF
                if isinstance(prop.raw_value, dict) and "raw_bytes" in prop.raw_value:
                    jpeg_tables[table_id] = prop.raw_value["raw_bytes"]

    # 3. Detect colour space from 0x02RR0002
    col_prop_id = 0x02000002 | (resolution_index << 16)
    col_blob = props.get(col_prop_id)
    colour_space = "NIF_RGB"
    if isinstance(col_blob, dict) and col_blob.get("colour_space") == "PhotoYCC":
        colour_space = "PhotoYCC"

    # 4. Open Subimage Header and Data streams
    res_storage = f"Data Object Store 000001/Resolution {resolution_index:04d}"
    hdr_stream_name = f"{res_storage}/Subimage 0000 Header"
    data_stream_name = f"{res_storage}/Subimage 0000 Data"

    if not ole.exists(hdr_stream_name):
        raise DecoderError(f"Missing header stream: {hdr_stream_name}")
    if not ole.exists(data_stream_name):
        raise DecoderError(f"Missing data stream: {data_stream_name}")

    with ole.openstream(hdr_stream_name) as handle:
        header_bytes = handle.read()
    with ole.openstream(data_stream_name) as handle:
        data_bytes = handle.read()

    if len(data_bytes) < DATA_PREAMBLE_LEN:
        raise DecoderError(f"Subimage data stream too short ({len(data_bytes)} bytes)")

    # Data payload starts after 28-byte preamble (+28 rule)
    data_payload = data_bytes[DATA_PREAMBLE_LEN:]
    header = parse_subimage_header(header_bytes)

    width = header.width
    height = header.height

    # 5. Grid calculation and tile stitching
    tiles_across = math.ceil(width / TILE_WIDTH)
    tiles_down = math.ceil(height / TILE_HEIGHT)

    canvas_w = tiles_across * TILE_WIDTH
    canvas_h = tiles_down * TILE_HEIGHT
    canvas = Image.new("RGB", (canvas_w, canvas_h))

    for idx, record in enumerate(header.records):
        row = idx // tiles_across
        col = idx % tiles_across
        tile_im = _decode_tile(record, data_payload, jpeg_tables, colour_space)
        canvas.paste(tile_im, (col * TILE_WIDTH, row * TILE_HEIGHT))

    # 6. Crop tile grid padding to declared subimage dimensions
    cropped = canvas.crop((0, 0, width, height))

    # 7. Viewing transform
    rotation_applied = 0
    crop_applied = None

    if apply_transform and ole.exists("\x05Transform 000001"):
        try:
            with ole.openstream("\x05Transform 000001") as handle:
                tx_bytes = handle.read()
            tx_pset = propset.parse_propset(tx_bytes, stream_name="\x05Transform 000001")
            matrix: list[float] | None = None
            for sec in tx_pset.sections:
                if 0x10000003 in sec.properties:
                    val = sec.properties[0x10000003].decoded_value
                    if isinstance(val, list) and len(val) == 16:
                        matrix = val

            if matrix is not None:
                # 90 deg CCW rotation test: A11 ~ 0, A22 ~ 0, A12 < -0.5, A21 > 0.5
                m0, m1, m4, m5 = matrix[0], matrix[1], matrix[4], matrix[5]
                if abs(m0) < 0.05 and abs(m5) < 0.05 and m1 < -0.5 and m4 > 0.5:
                    cropped = cropped.transpose(Image.Transpose.ROTATE_90)
                    rotation_applied = 270  # 90 degrees CCW
        except Exception:  # noqa: BLE001
            # If transform parsing fails, keep upright cropped canvas
            pass

    return DecodedImage(
        image=cropped,
        declared_width=width,
        declared_height=height,
        colour_space=colour_space,
        resolution_index=resolution_index,
        rotation_applied=rotation_applied,
        crop_applied=crop_applied,
    )
