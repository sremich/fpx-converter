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


#: What was found in `0x10000003` and what was done about it.
#:
#: Measured over the 687 distinct files: 612 identity, 22 a 90 degrees CCW
#: rotation, and 53 a uniform-scale-plus-translation crop that somebody
#: framed in the Kodak software. All three are now recognised. `unsupported`
#: means a matrix outside those shapes, and it is reported rather than
#: quietly treated as identity -- which is what used to happen, so a cropped
#: photo came out uncropped with nothing recording the discarded transform.
TRANSFORM_ABSENT = "absent"
TRANSFORM_IDENTITY = "identity"
TRANSFORM_ROTATE_90_CCW = "rotate-90-ccw"
TRANSFORM_CROP = "crop"
TRANSFORM_UNSUPPORTED = "unsupported"
TRANSFORM_PARSE_ERROR = "parse-error"


@dataclass
class DecodedImage:
    image: Image.Image
    declared_width: int
    declared_height: int
    colour_space: str
    resolution_index: int
    rotation_applied: int
    crop_applied: tuple[int, int, int, int] | None
    #: One of the TRANSFORM_* constants above.
    transform_status: str = TRANSFORM_ABSENT
    #: The raw 4x4 matrix, kept so an unsupported one can be reported rather
    #: than merely counted.
    transform_matrix: list[float] | None = None
    #: Populated when `transform_status` is not identity/absent/applied.
    transform_note: str = ""

    def cropped_image(self) -> Image.Image:
        """The image with the crop applied, or the full frame if there is none.

        `image` always stays the full frame: `archive/` preserves every pixel
        the camera captured, and `sharing/` shows the composition somebody
        framed at the time. Both are wanted, so the crop is applied here
        rather than in the decode.
        """
        if self.crop_applied is None:
            return self.image
        return self.image.crop(self.crop_applied)


def classify_orientation_matrix(matrix: list[float]) -> tuple[str, str]:
    """Classify a FlashPix `0x10000003` matrix. Returns (status, note).

    The matrix is row-major 4x4 mapping result coordinates to source
    coordinates. Three shapes are recognised, measured over the 687 distinct
    files in this corpus:

    * identity (612 files) -- nothing to do
    * a 90 degrees counter-clockwise rotation (22 files)
    * a uniform scale plus translation (53 files) -- a crop somebody framed
      in the Kodak software

    Anything else returns `unsupported` with the reason, so it lands in the
    audit rather than falling through to identity and shipping silently.

    This says only what the matrix *is*. It does not say whether a crop is
    present: 14 of the 22 rotations carry one too, so the crop is derived
    separately by `output_geometry` for every shape.
    """
    if len(matrix) != 16:
        return TRANSFORM_UNSUPPORTED, f"expected a 4x4 matrix, got {len(matrix)} values"

    m0, m1, _m2, m3 = matrix[0:4]
    m4, m5, _m6, m7 = matrix[4:8]

    def near(value: float, target: float, tol: float = 0.02) -> bool:
        return abs(value - target) <= tol

    if (
        near(m0, 1.0)
        and near(m1, 0.0)
        and near(m3, 0.0)
        and near(m4, 0.0)
        and near(m5, 1.0)
        and near(m7, 0.0)
    ):
        return TRANSFORM_IDENTITY, ""

    # 90 CCW: the diagonal is zero and the off-diagonal swaps the axes with
    # opposite signs and equal magnitude. That magnitude is a scale, not 1 --
    # FlashPix normalises the result height to 1.0 regardless of how much of
    # the source the result covers.
    if near(m0, 0.0, 0.05) and near(m5, 0.0, 0.05) and m1 < -0.5 and m4 > 0.5:
        if not near(-m1, m4, 1e-3):
            return (
                TRANSFORM_UNSUPPORTED,
                f"rotation with unequal axis scales: m1={m1:.4f}, m4={m4:.4f}",
            )
        return TRANSFORM_ROTATE_90_CCW, ""

    # Uniform scale plus translation. Uniform is required -- a non-square
    # scale would be a stretch, which is a different thing and is not
    # something this corpus contains.
    scaled = not near(m0, 1.0) or not near(m5, 1.0)
    translated = not near(m3, 0.0) or not near(m7, 0.0)
    if (scaled or translated) and near(m0, m5, 1e-4) and m0 > 0.0:
        parts = []
        if scaled:
            parts.append(f"scale {m0:.3f}")
        if translated:
            parts.append(f"offset ({m3:.3f}, {m7:.3f})")
        return TRANSFORM_CROP, "crop: " + ", ".join(parts)

    return TRANSFORM_UNSUPPORTED, f"unrecognised orientation matrix: {matrix[:8]}"


def source_crop_box(
    matrix: list[float],
    result_aspect: float | None,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    """Which source pixels the result viewport covers, or None for the full frame.

    FlashPix normalises image coordinates so height is 1.0 and width is the
    aspect ratio, which makes one normalised unit exactly `height` pixels on
    both axes. The matrix maps the *result* viewport -- which spans
    `[0, ResultAspectRatio] x [0, 1]` -- back into the source, so pushing the
    viewport's four corners through it and taking the bounding box gives the
    source region the result is made from.

    Doing it by corner-mapping rather than by reading a scale and a
    translation off the matrix is what makes this work for rotations as well
    as for axis-aligned crops. The earlier closed form only handled the
    axis-aligned case, so 14 rotated-and-cropped files came out rotated but
    uncropped, with nothing recording the difference.

    `ResultAspectRatio` (`0x10000000`) is per-file and describes the
    *cropped* result, not the source; without it the translation alone looks
    like it overflows the frame. Verified against the embedded DIB thumbnail
    across all 71 files in this corpus that resolve to a crop: cropping
    improved correlation with the thumbnail on every one of them, mean +0.56,
    min +0.003, and the worst post-crop correlation is 0.981.
    """
    if len(matrix) != 16 or not result_aspect or result_aspect <= 0:
        return None
    if width <= 0 or height <= 0:
        # No declared size: there is nothing to resolve the normalised
        # coordinates into. Refusing beats inventing a box.
        return None

    m0, m1, _m2, m3 = matrix[0:4]
    m4, m5, _m6, m7 = matrix[4:8]
    corners = [(rx, ry) for rx in (0.0, float(result_aspect)) for ry in (0.0, 1.0)]
    xs = [m0 * rx + m1 * ry + m3 for rx, ry in corners]
    ys = [m4 * rx + m5 * ry + m7 for rx, ry in corners]

    # Round the origin and the size separately, rather than rounding all four
    # edges. Rounding edges independently can move the box's width or height
    # by a pixel, which changes the aspect ratio away from the one the file
    # declares -- and that ratio is what this calculation is anchored on.
    left = round(min(xs) * height)
    top = round(min(ys) * height)
    box_w = round((max(xs) - min(xs)) * height)
    box_h = round((max(ys) - min(ys)) * height)

    if box_w < 1 or box_h < 1:
        return None
    # A box outside the frame means the matrix was misread. Refuse, so it
    # reports as unsupported rather than silently cropping to the wrong
    # pixels. One pixel of slack absorbs the rounding above.
    if left < -1 or top < -1 or left + box_w > width + 1 or top + box_h > height + 1:
        return None

    left = max(0, left)
    top = max(0, top)
    right = min(width, left + box_w)
    bottom = min(height, top + box_h)

    if (left, top, right, bottom) == (0, 0, width, height):
        return None
    return (left, top, right, bottom)


def rotate_box_90_ccw(box: tuple[int, int, int, int], width: int) -> tuple[int, int, int, int]:
    """Map a source-space box into the coordinates of the 90 CCW rotated image.

    Pillow's ROTATE_90 turns counter-clockwise, so a source pixel `(x, y)` in
    a `width x height` image lands at `(y, width - x)` in the `height x width`
    result. The box's left and right edges therefore become its top and
    bottom, and the vertical order flips.
    """
    left, top, right, bottom = box
    return (top, width - right, bottom, width - left)


@dataclass
class OutputGeometry:
    """The sizes and crop the two output files must have.

    Derived from the transform property set alone, so `metadata.py` can
    compute it straight from the `.fpx` and the validator can hold the
    finished outputs to it, instead of asking the decoder what it happened to
    produce and then checking the decoder against itself.
    """

    status: str
    note: str = ""
    matrix: list[float] | None = None
    #: Degrees counter-clockwise actually applied: 0 or 90.
    rotation: int = 0
    #: Size of the full-frame TIFF, after any rotation.
    tiff_size: tuple[int, int] = (0, 0)
    #: Crop box in the rotated image's coordinates, or None for no crop.
    crop_box: tuple[int, int, int, int] | None = None

    @property
    def jpeg_size(self) -> tuple[int, int]:
        if self.crop_box is None:
            return self.tiff_size
        left, top, right, bottom = self.crop_box
        return (right - left, bottom - top)


def output_geometry(
    matrix: list[float] | None,
    result_aspect: float | None,
    width: int,
    height: int,
) -> OutputGeometry:
    """Resolve a transform matrix into rotation, TIFF size, and crop box.

    Rotation and crop are independent: 14 of this corpus's 22 rotated files
    are also cropped. Treating "is it a rotation?" as the whole question is
    what dropped those crops.
    """
    if matrix is None:
        return OutputGeometry(status=TRANSFORM_ABSENT, tiff_size=(width, height))

    status, note = classify_orientation_matrix(matrix)

    if status == TRANSFORM_UNSUPPORTED:
        return OutputGeometry(status=status, note=note, matrix=matrix, tiff_size=(width, height))

    box = source_crop_box(matrix, result_aspect, width, height)

    if status == TRANSFORM_CROP and box is None:
        # The matrix says "crop" but no box could be resolved -- usually a
        # missing ResultAspectRatio. Report it; do not fall back to the full
        # frame as though the file had asked for one.
        return OutputGeometry(
            status=TRANSFORM_UNSUPPORTED,
            note=(
                f"{note}; could not be resolved to a box inside the "
                f"{width}x{height} frame (ResultAspectRatio={result_aspect})"
            ),
            matrix=matrix,
            tiff_size=(width, height),
        )

    if status == TRANSFORM_ROTATE_90_CCW:
        return OutputGeometry(
            status=status,
            note=f"rotation plus crop {box}" if box else note,
            matrix=matrix,
            rotation=90,
            tiff_size=(height, width),
            crop_box=rotate_box_90_ccw(box, width) if box else None,
        )

    return OutputGeometry(
        status=TRANSFORM_CROP if box else status,
        note=note if box else "",
        matrix=matrix,
        tiff_size=(width, height),
        crop_box=box,
    )


def parse_transform_stream(
    transform_stream_bytes: bytes,
) -> tuple[list[float] | None, float | None]:
    """`(SpatialOrientationMatrix, ResultAspectRatio)` from a Transform stream.

    Raises `DecoderError` if the stream will not parse. The parser reports
    malformed input by returning a property set carrying errors rather than
    by raising, so a caller that only guards against exceptions reads a
    corrupt transform stream as a file with no transform at all -- and ships
    a rotated photo sideways with nothing in the audit.
    """
    pset = propset.parse_propset(transform_stream_bytes, stream_name="Transform 000001")
    if not pset.ok:
        raise DecoderError(
            "transform property set did not parse: "
            + "; ".join(pset.errors + [e for s in pset.sections for e in s.errors])
        )
    matrix: list[float] | None = None
    result_aspect: float | None = None
    for sec in pset.sections:
        prop = sec.properties.get(0x10000003)
        if prop is not None:
            value = prop.decoded_value
            if isinstance(value, list) and len(value) == 16:
                matrix = [float(x) for x in value]
        prop = sec.properties.get(0x10000000)
        if prop is not None:
            value = prop.decoded_value
            if isinstance(value, (int, float)):
                result_aspect = float(value)
    return matrix, result_aspect


def apply_viewing_transform(
    image: Image.Image,
    transform_stream_bytes: bytes,
    width: int,
    height: int,
) -> tuple[Image.Image, OutputGeometry]:
    """Apply the `Transform 000001` viewing transform. Returns (image, geometry).

    Rotation is applied here; the crop is not. `archive/` keeps every pixel
    the camera captured, so the returned image is the full frame, upright,
    and the crop travels alongside it as a box for `sharing/` to apply.

    Split out of `decode_fpx` so it can be tested against real property-set
    bytes. Inside the decode it sat behind an OLE container, which meant the
    only way to reach the rotation and crop branches was to have a real
    `.fpx` carrying them -- and all four committed fixtures are identity, so
    neither branch was covered at any tier. Deleting either one left the
    whole suite green while 22 photos shipped sideways and 71 shipped
    uncropped.
    """
    try:
        matrix, result_aspect = parse_transform_stream(transform_stream_bytes)
    except Exception as exc:  # noqa: BLE001
        # Keep the upright image, but never silently: an unreadable transform
        # stream and a file with no transform at all used to produce
        # byte-identical results and the same empty report.
        return image, OutputGeometry(
            status=TRANSFORM_PARSE_ERROR,
            note=f"{type(exc).__name__}: {exc}",
            tiff_size=(width, height),
        )

    geom = output_geometry(matrix, result_aspect, width, height)
    if geom.rotation == 90:
        image = image.transpose(Image.Transpose.ROTATE_90)
    return image, geom


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
        raw_tile = Image.frombytes(
            "RGB", (TILE_WIDTH, TILE_HEIGHT), tile_bytes[:UNCOMPRESSED_TILE_SIZE]
        )
        # A raw tile holds channel values in the file's colour space, the
        # same as a JPEG one. The conversion was wired into the JPEG branch
        # only, so an uncompressed tile inside a PhotoYCC file came out as
        # YCC pretending to be RGB -- a colour-wrong patch in an otherwise
        # correct picture. Latent in this corpus (both PhotoYCC files are
        # entirely type-2), but "detect per file, never assume corpus-wide"
        # is a binding rule for exactly this reason.
        if colour_space == "PhotoYCC":
            return _photoycc_to_rgb(raw_tile)
        return raw_tile

    if t_type == COMPRESSION_SINGLE_COLOUR:
        # Type 1: 0 bytes data, fill colour is in the 4 subtype bytes
        sub = tile_rec.compression_subtype
        r = sub & 0xFF
        g = (sub >> 8) & 0xFF
        b = (sub >> 16) & 0xFF
        fill_tile = Image.new("RGB", (TILE_WIDTH, TILE_HEIGHT), (r, g, b))
        if colour_space == "PhotoYCC":
            return _photoycc_to_rgb(fill_tile)
        return fill_tile

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
    geom = OutputGeometry(status=TRANSFORM_ABSENT, tiff_size=(width, height))

    if apply_transform and ole.exists("\x05Transform 000001"):
        with ole.openstream("\x05Transform 000001") as handle:
            tx_bytes = handle.read()
        cropped, geom = apply_viewing_transform(cropped, tx_bytes, width, height)

    return DecodedImage(
        image=cropped,
        declared_width=width,
        declared_height=height,
        colour_space=colour_space,
        resolution_index=resolution_index,
        rotation_applied=geom.rotation,
        crop_applied=geom.crop_box,
        transform_status=geom.status,
        transform_matrix=geom.matrix,
        transform_note=geom.note,
    )
