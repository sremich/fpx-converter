# What a `.fpx` file actually is

Notes on the FlashPix container as this project found it, written to save the
next person the reverse-engineering. Everything here was established by parsing
files and checking the arithmetic across a corpus of 1,265 of them; the numbers
quoted are measurements from that corpus, not general truths about the format.

The authoritative specification is *FlashPix Format Specification, version
1.0.2* (Eastman Kodak Company, on behalf of the Digital Imaging Group). It is
a copyrighted document and none of it is reproduced here — this file describes
the format in its own words, and describes what our own parser does. Our parser
is an independent implementation; no code or text from any third-party FlashPix
toolkit is used in this project, and none should be introduced.

## The container: an OLE2 compound document

A `.fpx` file is a Microsoft OLE2 compound document — the same container
format as a pre-2007 Word file. It presents a small filesystem of *storages*
(directories) and *streams* (files), which this project reads with `olefile`.

The parts that matter:

```
\x05SummaryInformation                                (root)
\x05Transform 000001                                  (root)
Data Object Store 000001/
    \x05Image Contents
    Resolution 0000/
        Subimage 0000 Header
        Subimage 0000 Data
    Resolution 0001/
        ...
```

Stream names beginning `\x05` are OLE **property sets** — a tagged key/value
encoding where each property has a numeric id and a variant type code. Property
sets are grouped into sections identified by a FMTID (a 16-byte GUID). This
project's `propset.py` decodes them directly from the stream bytes.

Two details of property-set parsing that cost time:

- **Composite `VT_VARIANT` values are real and must be decoded recursively.**
  Some files (film scans, in this corpus) store variant containers whose
  elements each carry their own type code before the payload. A parser that
  skips them silently loses metadata. Handle `VT_VARIANT` both as a scalar and
  as a vector element.
- **Keep the raw bytes of `VT_BLOB` and `VT_CF` properties.** Downstream stages
  need the actual payloads — the JPEG table blob for the decoder, the DIB for
  the thumbnail extractor. A parser that reduces binary properties to a hex
  preview makes the pixel path impossible. Retain `raw_bytes` in memory and
  filter at *serialisation* time, so the JSON sidecar stays small without
  starving the decoder.
- **A parser that reports errors by return value is not one that raises.**
  `parse_propset` returns a property set carrying an `errors` list. A caller
  guarding only with `try/except` will read corrupt input as valid-but-empty.
  Check the `ok` flag.

## The resolution pyramid

`Data Object Store 000001` holds a pyramid of resolutions, `Resolution 0000`
upward, each roughly double the linear size of the last. **The highest index is
full resolution.**

Read the resolution count from the `Image Contents` property set (property id
`0x01000000`) rather than inferring it from the image width — a few files in
this corpus carry fewer resolutions than the norm, and guessing the top index
from the declared size picks the wrong storage.

Each resolution has a `Subimage 0000 Header` stream (the tile table) and a
`Subimage 0000 Data` stream (the tile payloads).

## The tile table

Tiles are a fixed 64 × 64 × 3 throughout. The subimage header stream is:

- a **64-byte preamble**, then
- **N × 16-byte little-endian records**, each
  `(offset, size, compression_type, compression_subtype)` as four `uint32`.

`64 + N*16 == len(header)` held on every file in the corpus.

There is a discrepancy in the header worth knowing about, because it looks like
a bug in the file until you resolve it. A header field states the tile-table
offset as 36 (`0x24`), while the records physically begin at byte 64 (`0x40`).
The stated offset is relative to the start of the section header at byte 28
(`0x1C`): `28 + 36 = 64`. Both the relative calculation and the fixed 64-byte
preamble formula give byte-exact pointers on 100% of files.

### Tile offsets are relative to byte 28 of the *Data* stream

Not to its start. The data stream opens with a 28-byte preamble, and every
record's `offset` is measured from the end of it. Confirmed arithmetically
across the corpus by `28 + max(offset + size) == len(data)`.

Hardcoding an offset base of 0, or a record size other than 16, breaks
everything downstream in ways that look like corrupt image data.

### The tile grid

Tiles are laid out row-major across a canvas of `ceil(width/64)` by
`ceil(height/64)` tiles. The canvas is therefore usually larger than the image;
crop it to the **declared** width and height after stitching. Read that declared
size per file — never assume the most common one.

## Three tile compression modes

`compression_type` selects between them. Across roughly 318,000 tiles in this
corpus: about 97% JPEG, about 3% uncompressed, and around 930 single-colour
fills.

**Type 0 — uncompressed.** Exactly 12,288 bytes (64 × 64 × 3), interleaved
channel values, no markers. The values are in the *file's* colour space, exactly
as a JPEG tile's are — a converter that wires the colour conversion into the
JPEG branch only will emit a colour-wrong patch inside an otherwise correct
picture.

**Type 1 — single-colour fill.** `size` is **0**, which is not an error. The
fill colour is packed into the four bytes of `compression_subtype`: red in the
low byte, then green, then blue. Any decoder that treats a zero-length tile as
a failure will reject files that are perfectly well-formed.

**Type 2 — abbreviated JPEG.** See below.

## Abbreviated JPEG: tables and tile data are stored apart

A tile's JPEG stream contains **only** SOI, SOF0, SOS and EOI. There are no
quantisation tables, no Huffman tables, no APP segments — verified by a full
marker parse over ~11,800 tiles. On its own, such a stream is not a decodable
JPEG, which is the root cause of most third-party FlashPix failures.

The tables live in the `Image Contents` property set, in properties matching
`0x03TT0001` (`VT_BLOB`). In this corpus the blob is 574 bytes: SOI, two DQT,
four DHT, EOI.

**The table id is chosen per tile**, carried in the top byte of the tile's
`compression_subtype`. Assuming one global table is wrong for the minority of
files that use an alternate id.

Reassembly is:

```python
jpeg_full = table_blob[:-2] + tile_bytes[2:]
```

That is: strip the table blob's **trailing EOI**, and drop the tile's leading
SOI. Both halves of that matter. Prepending the table blob *including* its EOI
is precisely why Pillow's bundled FlashPix plugin fails on the overwhelming
majority of these files — a decoder that sees an end-of-image marker before the
scan data stops there.

## Colour space: NIF RGB or PhotoYCC, per file

The declared colour space lives in `Image Contents` property `0x02RR0002`
(where `RR` is the resolution index) — a `VT_BLOB` carrying an uncalibrated
flag, a channel count, and per-channel ids. NIF RGB channel ids are
`0x00030000/1/2`.

In this corpus 99.7% of subimages are NIF RGB and only a handful are PhotoYCC —
so the expensive colour-science step everyone budgets for is mostly not needed.
**Detect it per file; never assume corpus-wide.** Decoding a PhotoYCC file as
RGB costs 25–28 levels of error, and *small is not the same as safe*: the two
PhotoYCC files here shipped solidly green with 42% of their pixels clipped to
zero, past every automated check the project had. No ICC profile exists anywhere
in these files, so sRGB is an assumption the output should make explicit rather
than one it should hide.

Where a file declares nothing, or declares channel ids the decoder does not
recognise, this project assumes NIF RGB — but records that the assumption was
made, because when it is wrong it is invisible.

### Decoding a PhotoYCC tile without converting it twice

A PhotoYCC tile must be read as its **stored components** and only then put
through the PhotoYCC transform:

```python
tile_im.draft("YCbCr", tile_im.size)
tile_im.load()
```

Calling `convert("RGB")` first runs the ordinary JFIF YCbCr→RGB transform, and
the PhotoYCC transform then runs on top of an image that has already been
converted once. That is the double conversion described above.

`draft()` is a request, not a guarantee. A single-component (greyscale) JPEG
stays in mode `L`, and `convert("YCbCr")` would then *fabricate* chroma at 128,
which this transform turns into a strong green cast on what was a neutral tile.
Refuse rather than invent.

**The two chroma axes do not share a neutral point.** The blue-difference axis
is neutral at 156 and the red-difference axis at 137. Centring both on 156 —
the obvious-looking simplification — costs the red channel about 35 levels and
hands roughly half of that to green.

## The viewing transform

Every file carries a `\x05Transform 000001` stream. The spatial orientation
matrix is property `0x10000003` (`VT_VECTOR|VT_R4`, 16 elements). Across this
corpus it is identity on most files, a scale-plus-translation on about a
hundred, and a **90° counter-clockwise rotation** on 22 distinct images.

The rotation *direction* was settled empirically rather than by reading the
spec: correlating both candidate rotations against each file's own already-
oriented embedded thumbnail gave +0.999 for counter-clockwise against −0.23 for
clockwise. A human-readable edit-log stream, present on a minority of files,
independently records a 270° rotate.

A decoder that ignores `0x10000003` emits those images sideways and ignores
every crop.

### `ResultAspectRatio` is what makes the crop box resolvable

FlashPix normalises image coordinates so that height is 1.0 and width is the
aspect ratio, which makes one normalised unit exactly `height` pixels on *both*
axes. The matrix maps the result viewport — spanning `[0, ResultAspectRatio] ×
[0, 1]` — back into the source.

`ResultAspectRatio` is property `0x10000000`, it is per file, and it describes
the **cropped result**, not the source. Without it the translation alone appears
to push the crop box outside the frame, which is what makes a first reading of
the matrix look wrong. With it, every box lands inside the image and every
resulting width and height matches the declared aspect ratio to four decimal
places.

Two things about deriving the box:

- **Map the four corners of the result viewport through the matrix and take the
  bounding box.** Do not read a scale and a translation off the matrix: that
  closed form is only valid for an axis-aligned matrix, and under a rotation the
  scale sits on the off-diagonal, so the formula reads zeros and the crop is
  silently dropped. In this corpus 14 of the 22 rotated files also carry a crop.
- **Round the origin and the *size* separately**, not all four edges. Rounding
  edges independently moves the width or height by a pixel and pushes the result
  off the declared aspect ratio, which is the quantity the whole calculation is
  anchored on.

A matrix's *shape* does not tell you whether it crops. Within a small identity
tolerance a matrix can still resolve to a real box — three files here keep only
75–87% of the frame with the narrowing coming from `ResultAspectRatio` rather
than from the matrix at all. The box is the authority. In the other direction, a
box within a pixel of the frame on both axes is rounding, not a crop, and should
be discarded.

Also present on some files: a non-identity colour twist at `0x10000004`, which
this project reads but does not apply.

## The embedded thumbnail is a DIB, not a JPEG

Every file in this corpus embeds a thumbnail in the root summary property set,
`PIDSI_THUMBNAIL` (property id 17, type `VT_CF`), 12–28 KB, accounting for
about 99% of that stream's size. The long side is always 96 pixels.

The payload is `CF_DIB`:

```
+0   int32   -1            standard clipboard format marker
+4   uint32  8             CF_DIB
+8   40-byte BITMAPINFOHEADER (biBitCount 24, biCompression BI_RGB)
+48  pixel bytes
```

The pixel bytes are **BGR, bottom-up, with rows padded to a 4-byte stride** —
so row 0 in the data is the *bottom* row of the picture (positive `biHeight`
signals bottom-up; a negative one would mean top-down).

**Writing those bytes out with a `.jpg` extension produces garbage.** They are
not a JPEG and not even a complete BMP: a bare DIB needs a 14-byte
`BITMAPFILEHEADER` prepended before any image viewer will open it, or else
conversion to a real image format.

Two free wins come from it. It gives a QA gallery its thumbnails without
decoding anything. And because it was written by the authoring software
**already rotated and cropped**, it is an independent oracle for decode
correctness, rotation direction and crop geometry. Because it is stored
*uncompressed*, it can also witness colour — but only if it is asked properly;
see `ARCHITECTURE.md` on the two oracles.

## Why Pillow's `FpxImagePlugin` is unusable here

Run over all 1,265 files, Pillow's bundled FlashPix plugin opened **39** and
raised on **1,224** (`broken data stream when reading image file`, `decoder fill
not available`). **Two files hard-crashed the CPython process** with an access
violation — heap corruption, nondeterministic.

The common failure has the root cause described above: the plugin prepends the
table blob including its trailing EOI marker. It also has no decoder for
zero-length single-colour tiles.

So the custom decoder is the primary path and not a fallback. The 39 files the
plugin did open were used as a correctness oracle and matched the custom
reconstruction at 0.0 mean absolute difference — which is worth having, but it
must be run **out of process**, because an in-process crash takes the whole
batch down.
