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
from propset_builder import build_propset_bytes

from fpx_converter import decoder, propset


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
    scale-and-translate crops. Anything else is reported as unsupported
    rather than silently treated as identity.
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
    def test_crop_matrices_are_recognised_not_treated_as_identity(
        self, scale: float, offset: float
    ) -> None:
        matrix = [scale, 0, 0, offset, 0, scale, 0, offset, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
        status, note = decoder.classify_orientation_matrix(matrix)
        assert status == decoder.TRANSFORM_CROP
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
            decoder.TRANSFORM_CROP,
        }


class TestCropGeometry:
    """The crop box derived from the viewing transform.

    Verified against the embedded DIB thumbnail across all 71 files in the
    corpus that resolve to a crop: cropping improved correlation with the
    thumbnail on every one (mean +0.56, min +0.003, none worse), and the worst
    post-crop correlation is 0.981. The thumbnail was written by the same
    software that recorded the transform, so it is an independent witness to
    the intended framing.
    """

    @staticmethod
    def _matrix(scale: float, tx: float, ty: float) -> list[float]:
        return [scale, 0, 0, tx, 0, scale, 0, ty, 0, 0, 1.0, 0, 0, 0, 0, 1.0]

    def test_full_frame_matrix_yields_no_crop(self) -> None:
        # None means "keep every pixel", which is not the same answer as a
        # box that happens to cover the frame: it is what stops the writer
        # re-encoding a JPEG identical to the TIFF and calling it a crop.
        assert decoder.source_crop_box(self._matrix(1.0, 0.0, 0.0), 4 / 3, 1152, 864) is None

    def test_uses_result_aspect_ratio_for_the_width(self) -> None:
        # Without ResultAspectRatio the width is wrong and the box can fall
        # outside the frame -- this is the term that makes the algebra work.
        box = decoder.source_crop_box(self._matrix(0.7449, 0.0, 0.2521), 0.8746, 1152, 864)
        assert box is not None
        left, top, right, bottom = box
        assert (left, top) == (0, 218)
        assert right - left == round(0.7449 * 0.8746 * 864)
        assert bottom - top == round(0.7449 * 864)
        # The cropped result must have the aspect ratio the file declares.
        assert abs(((right - left) / (bottom - top)) - 0.8746) < 0.01

    def test_box_stays_inside_the_frame(self) -> None:
        box = decoder.source_crop_box(self._matrix(0.8335, 0.1004, 0.094), 1.0365, 1152, 864)
        assert box is not None
        left, top, right, bottom = box
        assert 0 <= left < right <= 1152
        assert 0 <= top < bottom <= 864

    def test_missing_result_aspect_refuses_rather_than_guessing(self) -> None:
        # Guessing the aspect would silently crop to the wrong shape.
        assert decoder.source_crop_box(self._matrix(0.8, 0.1, 0.1), None, 1152, 864) is None
        assert decoder.source_crop_box(self._matrix(0.8, 0.1, 0.1), 0.0, 1152, 864) is None

    def test_a_box_falling_outside_the_frame_is_refused(self) -> None:
        # A box outside the image means the matrix was misread. Refusing
        # surfaces that; clamping would hide it behind a plausible crop.
        assert decoder.source_crop_box(self._matrix(0.9, 0.9, 0.9), 1.333, 1152, 864) is None

    def test_crop_matrix_is_classified_as_a_crop_not_unsupported(self) -> None:
        status, note = decoder.classify_orientation_matrix(self._matrix(0.745, 0.0, 0.252))
        assert status == decoder.TRANSFORM_CROP
        assert "0.745" in note

    def test_non_uniform_scale_is_not_treated_as_a_crop(self) -> None:
        # A stretch is a different operation and this corpus has none. Better
        # to report it than to crop to the wrong shape.
        stretched = [0.8, 0, 0, 0.1, 0, 0.5, 0, 0.1, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
        assert decoder.classify_orientation_matrix(stretched)[0] == decoder.TRANSFORM_UNSUPPORTED

    def test_cropped_image_falls_back_to_the_full_frame(self) -> None:
        img = Image.new("RGB", (100, 80), (10, 20, 30))
        dec = decoder.DecodedImage(
            image=img,
            declared_width=100,
            declared_height=80,
            colour_space="NIF_RGB",
            resolution_index=0,
            rotation_applied=0,
            crop_applied=None,
        )
        assert dec.cropped_image().size == (100, 80)
        dec.crop_applied = (10, 10, 60, 50)
        assert dec.cropped_image().size == (50, 40)
        # The full frame is never mutated -- archive/ depends on it.
        assert dec.image.size == (100, 80)


class TestOutputGeometry:
    """Rotation and crop resolved together, from the matrix alone.

    These two are independent, and treating them as one question is what this
    class exists to prevent: 14 of the corpus's 22 rotated files also carry a
    crop, and an earlier version applied the rotation, saw "this is a
    rotation, not a crop", and dropped the crop on all 14 without recording
    anything.
    """

    IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]

    # Real matrices, read out of three files in the archive. Their shape is
    # the thing under test, so inventing plausible-looking ones would test
    # the invention.
    ROTATION_ONLY = [0.0, -1.333333, 0, 1.333333, 1.333333, 0.0, 0, 0.0,
                     0, 0, 1.0, 0, 0, 0, 0, 1.0]
    ROTATION_ONLY_ASPECT = 0.75
    ROTATION_AND_CROP = [0.0, -1.169169, 0, 1.333333, 1.169169, 0.0, 0, 0.2002,
                         0, 0, 1.0, 0, 0, 0, 0, 1.0]
    ROTATION_AND_CROP_ASPECT = 0.5821918

    def test_absent_matrix_is_the_full_frame(self) -> None:
        geom = decoder.output_geometry(None, None, 1152, 864)
        assert geom.status == decoder.TRANSFORM_ABSENT
        assert geom.rotation == 0
        assert geom.tiff_size == (1152, 864)
        assert geom.crop_box is None
        assert geom.jpeg_size == (1152, 864)

    def test_identity_leaves_both_outputs_full_frame(self) -> None:
        geom = decoder.output_geometry(self.IDENTITY, 4 / 3, 1152, 864)
        assert geom.status == decoder.TRANSFORM_IDENTITY
        assert geom.rotation == 0
        assert geom.tiff_size == (1152, 864)
        assert geom.jpeg_size == (1152, 864)

    def test_rotation_swaps_the_tiff_size(self) -> None:
        geom = decoder.output_geometry(
            self.ROTATION_ONLY, self.ROTATION_ONLY_ASPECT, 1152, 864
        )
        assert geom.status == decoder.TRANSFORM_ROTATE_90_CCW
        assert geom.rotation == 90
        assert geom.tiff_size == (864, 1152)
        assert geom.crop_box is None

    def test_a_rotated_file_can_also_be_cropped(self) -> None:
        geom = decoder.output_geometry(
            self.ROTATION_AND_CROP, self.ROTATION_AND_CROP_ASPECT, 1152, 864
        )
        assert geom.rotation == 90
        assert geom.tiff_size == (864, 1152)
        assert geom.crop_box is not None, "the crop rode along with the rotation and was dropped"
        # The crop is expressed in the rotated image's coordinates, because
        # that is the image the JPEG is cut from.
        left, top, right, bottom = geom.crop_box
        assert 0 <= left < right <= 864
        assert 0 <= top < bottom <= 1152
        # And it has the aspect ratio the file declares for its result.
        assert abs(((right - left) / (bottom - top)) - self.ROTATION_AND_CROP_ASPECT) < 0.005
        assert geom.jpeg_size == (right - left, bottom - top)
        assert geom.jpeg_size != geom.tiff_size

    def test_the_note_records_a_crop_that_rode_along_with_a_rotation(self) -> None:
        geom = decoder.output_geometry(
            self.ROTATION_AND_CROP, self.ROTATION_AND_CROP_ASPECT, 1152, 864
        )
        assert "crop" in geom.note

    def test_a_crop_that_cannot_be_resolved_is_unsupported_not_full_frame(self) -> None:
        # No ResultAspectRatio: the box is not derivable. Reporting the file
        # as unsupported puts it in the audit; falling back to the full frame
        # would ship it silently uncropped.
        matrix = [0.7449, 0, 0, 0.0, 0, 0.7449, 0, 0.2521, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
        geom = decoder.output_geometry(matrix, None, 1152, 864)
        assert geom.status == decoder.TRANSFORM_UNSUPPORTED
        assert geom.crop_box is None
        assert "ResultAspectRatio" in geom.note

    def test_an_unsupported_matrix_never_rotates_or_crops(self) -> None:
        stretched = [0.8, 0, 0, 0.1, 0, 0.5, 0, 0.1, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
        geom = decoder.output_geometry(stretched, 1.333, 1152, 864)
        assert geom.status == decoder.TRANSFORM_UNSUPPORTED
        assert geom.rotation == 0
        assert geom.crop_box is None
        assert geom.tiff_size == (1152, 864)

    def test_rotating_a_box_matches_pillow(self) -> None:
        """The box mapping must agree with the rotation actually applied.

        Marking the corner pixel and following it through `ROTATE_90` is the
        only check that catches a transposed or flipped box formula; the
        arithmetic on its own looks equally right in three wrong variants.
        """
        img = Image.new("RGB", (1152, 864), (0, 0, 0))
        img.putpixel((1100, 40), (255, 0, 0))
        rotated = img.transpose(Image.Transpose.ROTATE_90)

        box = (1090, 30, 1110, 50)
        mapped = decoder.rotate_box_90_ccw(box, 1152)
        assert rotated.crop(mapped).getextrema()[0][1] == 255, (
            "the marked pixel fell outside the mapped box"
        )
        assert mapped[2] - mapped[0] == box[3] - box[1]
        assert mapped[3] - mapped[1] == box[2] - box[0]


class TestApplyViewingTransform:
    """The transform applied to real property-set bytes.

    `apply_viewing_transform` exists as a separate function precisely so
    these can run at tier 1. Inside `decode_fpx` the rotation and crop
    branches sat behind an OLE container, and all four committed fixtures are
    identity, so both branches were reachable only from the private archive
    and were covered by nothing.
    """

    @staticmethod
    def _transform_bytes(matrix: list[float], aspect: float | None) -> bytes:
        """A `Transform 000001` stream in the encoding the archive uses.

        Measured from the files: the matrix is `VT_VECTOR | VT_R4` (0x1004)
        with a 32-bit element count, and `ResultAspectRatio` is a bare
        `VT_R4`. Building it in a different encoding would test a format that
        does not occur.
        """
        props = [
            (
                0x10000003,
                propset.VT_VECTOR | propset.VT_R4,
                struct.pack("<I", len(matrix)) + struct.pack(f"<{len(matrix)}f", *matrix),
            )
        ]
        if aspect is not None:
            props.append((0x10000000, propset.VT_R4, struct.pack("<f", aspect)))
        return build_propset_bytes(propset.FMTID_TRANSFORM, props)

    def _decoded(self) -> Image.Image:
        img = Image.new("RGB", (1152, 864), (10, 20, 30))
        # An asymmetric mark, so a rotation that went the wrong way is
        # distinguishable from one that went the right way.
        img.paste((255, 0, 0), (0, 0, 200, 40))
        return img

    def test_identity_bytes_leave_the_image_alone(self) -> None:
        raw = self._transform_bytes(TestOutputGeometry.IDENTITY, 4 / 3)
        out, geom = decoder.apply_viewing_transform(self._decoded(), raw, 1152, 864)
        assert geom.status == decoder.TRANSFORM_IDENTITY
        assert out.size == (1152, 864)
        assert geom.crop_box is None

    def test_rotation_bytes_produce_an_upright_portrait_image(self) -> None:
        raw = self._transform_bytes(
            TestOutputGeometry.ROTATION_ONLY, TestOutputGeometry.ROTATION_ONLY_ASPECT
        )
        source = self._decoded()
        out, geom = decoder.apply_viewing_transform(source, raw, 1152, 864)
        assert geom.rotation == 90
        assert out.size == (864, 1152) == geom.tiff_size
        # Counter-clockwise: the red band along the top edge ends up down
        # the left edge. A clockwise rotation would put it on the right.
        assert out.getpixel((10, 1100)) == (255, 0, 0)
        assert out.getpixel((10, 10)) != (255, 0, 0)

    def test_rotation_and_crop_bytes_yield_a_cropped_jpeg_and_a_full_tiff(self) -> None:
        raw = self._transform_bytes(
            TestOutputGeometry.ROTATION_AND_CROP, TestOutputGeometry.ROTATION_AND_CROP_ASPECT
        )
        out, geom = decoder.apply_viewing_transform(self._decoded(), raw, 1152, 864)
        assert out.size == (864, 1152), "the archival TIFF must keep every captured pixel"
        assert geom.crop_box is not None
        dec = decoder.DecodedImage(
            image=out,
            declared_width=1152,
            declared_height=864,
            colour_space="NIF_RGB",
            resolution_index=0,
            rotation_applied=geom.rotation,
            crop_applied=geom.crop_box,
        )
        assert dec.cropped_image().size == geom.jpeg_size
        assert dec.cropped_image().size != out.size

    def test_a_corrupt_transform_stream_reports_rather_than_pretending(self) -> None:
        # An unreadable transform and a file with no transform at all must
        # not produce the same report -- that is a silently wrong photo.
        out, geom = decoder.apply_viewing_transform(
            self._decoded(), b"not a property set", 1152, 864
        )
        assert geom.status == decoder.TRANSFORM_PARSE_ERROR
        assert geom.note
        assert out.size == (1152, 864)
        assert geom.status != decoder.TRANSFORM_ABSENT

    def test_a_transform_stream_with_no_matrix_is_absent_not_an_error(self) -> None:
        raw = build_propset_bytes(
            propset.FMTID_TRANSFORM, [(0x10000000, propset.VT_R4, struct.pack("<f", 1.3333))]
        )
        _out, geom = decoder.apply_viewing_transform(self._decoded(), raw, 1152, 864)
        assert geom.status == decoder.TRANSFORM_ABSENT
        assert geom.tiff_size == (1152, 864)
