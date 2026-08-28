"""Give a committed fixture a viewing transform, at test time, in a copy.

`feeder-crop.fpx` was the only fixture in this repository carrying a
viewing-transform crop, and it was deleted on 2026-08-27 because a person turned
up in its background at full resolution. The rule outranked the coverage, which
is what that rule has to mean when obeying it is expensive -- but it left the
branch that carried the 0.4.0 defect, where rotated-and-cropped files shipped
with their crop silently dropped, with no cover in CI at all.

This restores the cover without putting another photograph in the repository.
Every committed fixture already carries a `\\x05Transform 000001` stream holding
an **identity** `SpatialOrientationMatrix` and a `ResultAspectRatio`. Both are
fixed-width float32 fields, so replacing their values changes no byte count
anywhere -- which is exactly the constraint `olefile`'s `write_stream` imposes:
it will replace a stream only with data of the same size. So a copy of a
person-free fixture can be given any transform we like, in a real OLE2
container, with real pixels behind it.

What this does *not* buy, and must not be claimed to: the embedded DIB thumbnail
in these files was written to the **uncropped** framing by the software that made
the file. Against a crop we invented it is not a witness to anything. Every
assertion built on these fixtures has to be geometric. See the module docstring
of `test_fixtures_transform.py`.

The byte offsets come from `ParsedProperty.byte_offset` rather than from
searching the stream, because searching is ambiguous: `ColorTwistMatrix`
(`0x10000004`) is *also* an identity 4x4 of float32 on an untransformed file, so
the packed identity bytes occur twice. Re-walking the section table here instead
would be the second copy of the format that `propset_builder.py` warns about in
its own docstring.
"""

from __future__ import annotations

import shutil
import struct
from pathlib import Path

import olefile

from fpx_converter import propset

#: The stream every FlashPix file in this corpus keeps its viewing transform in.
TRANSFORM_STREAM = "\x05Transform 000001"

#: `SpatialOrientationMatrix` -- the row-major 4x4 mapping result coordinates
#: back to source coordinates.
PID_ORIENTATION_MATRIX = 0x10000003

#: `ResultAspectRatio` -- the aspect of the *cropped* result, not of the source.
#: Without it a translation looks like it overflows the frame, so a transform
#: written without updating it resolves to nonsense rather than to a crop.
PID_RESULT_ASPECT = 0x10000000


def rotate_90_ccw(scale: float, tx: float, ty: float) -> list[float]:
    """A 90-degree counter-clockwise matrix in the shape this corpus stores.

    `scale` is how much of the source the result covers, in normalised units
    where the source height is 1.0 -- not a zoom. It sits on the off-diagonal
    with opposite signs and equal magnitude, which is what
    `decoder.classify_orientation_matrix` recognises the rotation by.
    """
    return [
        0.0, -scale, 0.0, tx,
        scale, 0.0, 0.0, ty,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]  # fmt: skip


def axis_aligned(scale: float, tx: float, ty: float) -> list[float]:
    """A uniform scale plus translation -- a crop somebody framed, unrotated.

    56 of the 70 crops in the reference corpus are this shape; the other 14
    ride along with a rotation and are `rotate_90_ccw` above.
    """
    return [
        scale, 0.0, 0.0, tx,
        0.0, scale, 0.0, ty,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]  # fmt: skip


def _patch_value(
    stream: bytearray, prop: propset.ParsedProperty, values: list[float], *, vector: bool
) -> None:
    """Overwrite one float32 property's value bytes in place.

    Refuses rather than writes if the property is not the type and length
    expected. A helper that silently wrote to the wrong offset would corrupt the
    stream into something the parser still reads, which is the failure mode this
    whole project is most careful about.
    """
    offset = prop.byte_offset
    if offset < 0:
        raise ValueError(f"{prop.name} carries no byte offset")
    if vector:
        count = struct.unpack_from("<I", stream, offset)[0]
        if count != len(values):
            raise ValueError(
                f"{prop.name} holds {count} values, not the {len(values)} offered"
            )
        offset += 4
    elif len(values) != 1:
        raise ValueError(f"{prop.name} is a scalar; {len(values)} values offered")
    struct.pack_into(f"<{len(values)}f", stream, offset, *values)


def write_transform(
    source: Path, dest: Path, *, matrix: list[float], result_aspect: float
) -> Path:
    """Copy `source` to `dest` and give the copy `matrix` and `result_aspect`.

    Returns `dest`. The source fixture is never touched -- the same read-only
    rule the tool applies to a real archive applies to the fixtures, which are
    the only irreplaceable thing in this repository.
    """
    if len(matrix) != 16:
        raise ValueError(f"expected a 4x4 matrix, got {len(matrix)} values")

    shutil.copy2(source, dest)

    with olefile.OleFileIO(dest) as ole:
        if not ole.exists(TRANSFORM_STREAM):
            raise ValueError(f"{source.name} carries no {TRANSFORM_STREAM!r} stream")
        with ole.openstream(TRANSFORM_STREAM) as handle:
            original = handle.read()

    parsed = propset.parse_propset(original, stream_name=TRANSFORM_STREAM)
    if not parsed.ok:
        raise ValueError(f"{source.name}: transform stream does not parse cleanly")

    section = parsed.sections[0]
    patched = bytearray(original)
    _patch_value(patched, section.properties[PID_ORIENTATION_MATRIX], matrix, vector=True)
    _patch_value(
        patched, section.properties[PID_RESULT_ASPECT], [result_aspect], vector=False
    )

    # The invariant `write_stream` enforces, asserted here so a future change to
    # the packing fails with this sentence rather than inside olefile.
    if len(patched) != len(original):
        raise AssertionError(
            f"patching changed the stream length ({len(original)} -> {len(patched)})"
        )

    with olefile.OleFileIO(dest, write_mode=True) as ole:
        ole.write_stream(TRANSFORM_STREAM, bytes(patched))

    return dest
