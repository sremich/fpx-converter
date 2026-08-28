# Architecture

How fpx-converter is put together, and — more usefully — the rules a change
can break silently. Most of what follows was paid for by a defect that shipped.
Each rule says *why*, because a rule without its reason gets optimised away by
the next person who finds it inconvenient.

The one-line version: this tool reads an irreplaceable archive of `.fpx` files
that nothing modern can open, and writes derivatives. **The archive is the
original. Everything the tool produces is a copy.** Almost every rule here
follows from that asymmetry — a wrong output can be regenerated, and a damaged
or misdescribed source cannot.

## The shape of the pipeline

```
scan      walk the source read-only, hash every file, write manifest.json
ingest    copy one file per hash into a working store (never moves the source)
metadata  parse all property sets, dump a raw .fpx.json sidecar
convert   decode pixels -> write TIFF + JPEG -> tag with ExifTool -> read back
gallery   build a QA page over a finished run, and collect album dates
```

`fpx_converter/` holds all of it. `fpx_gui/` is a desktop front end that
**wraps the CLI as a child process** and reimplements none of it. The
interesting modules:

| Module | Job |
|---|---|
| `propset.py` | OLE property-set parser: all FlashPix property sets, extension sets, and the composite variant types |
| `decoder.py` | Tile table, tile decode, stitch, crop, colour space, viewing transform |
| `thumbnail.py` | Embedded CF_DIB extraction, plus the greyscale correlation oracle |
| `oracles.py` | The colour oracle (`chroma_agreement`), shared by tiers 1, 2 and 3 |
| `timestamps.py`, `layout.py`, `naming.py`, `name_template.py` | Dates, folders, filenames — three separate questions, see below |
| `writer.py`, `validator.py` | ExifTool writes the tags; Pillow reads them back |
| `batch.py` | Resume-by-hash batch engine; never aborts the run on one bad file |

`docs/FORMAT.md` covers the file format itself. `docs/DATES.md` covers the
dating rules in user-facing terms. `docs/TESTING.md` covers the four tiers.

---

## The source tree is read-only

Nothing in this project may write, move, rename or delete under the source
root. Ingestion verifies the tree is byte-identical afterwards.

This is enforced in code rather than left to the caller: `--manifest`,
`--dest` and every other destination path go through
`config.ensure_outside_source`, which refuses any path inside the source root.

**The GUI calls that function; it does not have its own copy of the check.**
That distinction is the rule, not an implementation detail — a second copy of
a safety check is a second thing to forget to update, and the whole point of
the desktop app wrapping the CLI is that the dangerous decisions have one
home. Exactly two tier-1 tests fail if the call is replaced by a local
reimplementation of the same logic (one at `fpx_gui/options.py`, one at the
window). That count is measured by mutation, not asserted in prose.

## There is no capture date in this corpus

The FlashPix capture-date property is **absent from every file**. The only
timestamp any of these files carries is a Kodak import-batch stamp, recorded
when the photographs were pulled off the camera — which on this archive misses
the actual event by as much as 223 days, and disagrees with folder-name ground
truth on 7 of 9 dated albums.

So the import stamp is written to `DateTimeDigitized` / `xmp:CreateDate`,
where it is true, and **never** to `DateTimeOriginal`.

**"Defensible" means a single day.** A folder naming a year, a two-year span,
a season or a month does not date a photograph, and EXIF has no way to say
"sometime in 2001" — writing a tag means naming a day. The first
implementation took the start of the range and borrowed the hour, minute and
second from the import stamp, which gave 151 of 687 files a fabricated capture
moment precise to the second, in the one field that is supposed to hold only
things that are known.

Coarse dates are still useful, and still kept — as `sort_datetime`, which
drives the filesystem mtime and the filename prefix. Unknown components are
written as zeros (`2001-00-00_000000_`), which sorts correctly and cannot be
mistaken for knowledge. **A filename prefix is a browsing affordance;
`DateTimeOriginal` is a claim.**

## A folder name somebody typed outranks any date we can derive

Somebody typed the folder name about these specific photographs. Nobody typed
the import stamp. So a descriptive source folder keeps its name as the album
whatever date the photo carries, nested under the year if the name gives one.
Only a folder whose name says nothing — the tool-generated and placeholder
names in `layout.NON_DESCRIPTIVE_ALBUMS`, extended per-archive through
`FPX_NON_DESCRIPTIVE_ALBUMS` — is replaced by a `<year>/<year> <Month>` filing
folder.

The two mistakes are not symmetric: wrongly calling a folder non-descriptive
discards something a person wrote and cannot be recovered from the file, while
wrongly calling one descriptive leaves a slightly odd album name. That is why
the non-descriptive list is short and explicit and never a heuristic.

A file usually belongs to several albums. It is filed under the **most
descriptive** one, not the first listed — taking the first put 52 photographs
of one holiday under a folder named after a zip file, and because the album is
also what resolves the date, cost them the day-precise date their real album
gave for free.

### Three date vocabularies, deliberately not shared

There are three places a date appears, and they answer different questions:

| Where | May use | Because |
|---|---|---|
| Folder (`--folder-scheme`, `--folder-template`) | `{year}` `{month}` `{album}`, resolved from `layout.filing_year_month` | A folder is a browsing affordance; it may use the album name or the import stamp |
| Filename (`--name-template`) | `{year}` `{month}` `{day}` `{time}` `{name}`, from `format_date_prefix` | Tracks what is *claimable*; zeroes anything undefensible |
| EXIF `DateTimeOriginal` | Only a day-precise folder date, an owner-supplied date, or an embedded scan date | It is a claim |

Reusing one vocabulary for another is not hypothetical: the first
implementation gave folder patterns the filename's fields, and a custom
`{year}/{album}` then filed almost everything under `0000/` while
`--folder-scheme year` — the same word — correctly said `2002/`. Asking for
`{day}` or `{time}` in a folder pattern is now refused rather than answered.
`filing_year_month` returns a *pair* rather than a `datetime` for the same
reason: a `datetime` forces an unknown month to be some month, and every such
file landed in January, which reads as evidence rather than as its absence.

## The two oracles, and why they are not interchangeable

Both compare a decode against evidence stored inside the same file — the
embedded thumbnail, written by the software that made the file. They witness
different things and are not substitutes.

**`thumbnail.compute_image_correlation` folds both images to greyscale** before
correlating. It is therefore evidence about framing, orientation and crop, and
**no evidence at all about colour**. It is the strongest oracle here — it
confirmed the 90° rotation direction and all 70 crops, and its worst score is
0.981 — which is exactly what makes it dangerous: numbers that high look like a
general "the image is right" check. A file with its colour channels permuted,
or with PhotoYCC left unconverted, scores just as well. It is aspect-blind too,
since it resizes both images to a square 64×64. **Never cite it in support of a
colour claim.**

**`oracles.chroma_agreement` is the colour check.** It compares `R-G` and `B-G`
against the same thumbnail, dividing out the luma the greyscale oracle already
covers, and reports correlation, scale and offset separately because each
catches a different fault and none catches all three.

**Correlating the R, G and B channels separately is not a colour check.**
Pearson correlation is invariant under any per-channel affine map, so a wrong
gain or a wrong neutral point scores exactly as well as a correct decode. That
version was written, shipped, and caught: measured on this corpus it passed a
decode with the wrong PhotoYCC neutral — half of the very bug it was written
for — passed a fully desaturated decode, and passed one with red and blue
swapped.

The history behind all of this: two PhotoYCC files were being converted twice
and came out solidly green with 42% of their pixels clipped to zero, past every
automated check the project had at the time. What found it was plain pixel
statistics. What fixed the gap is `chroma_agreement`. What confirms it is still
a person looking — a 96-pixel thumbnail is evidence, not sight.

Known blind spot, measured rather than assumed: chroma is `R-G` and `B-G`, so
an error confined to the **green** channel moves both signals together and
largely cancels. A green gain of ×1.10 trips no gate on any file; a comparable
red gain trips 39% of them.

## `archive/` keeps the full frame; `sharing/` gets the crop

70 files in this archive carry a crop somebody framed in the Kodak software —
56 axis-aligned, 14 riding along with a 90° rotation. Both the captured frame
and the intended composition are worth keeping, and the two output trees have
exactly those two jobs. `DecodedImage.image` always stays the full frame;
`cropped_image()` applies the crop.

**A matrix's shape does not tell you whether it crops.** Rotation and crop are
independent properties of the same matrix, and asking "is this a rotation or a
crop?" answers the wrong question. The closed-form read of a scale and a
translation is only valid for an axis-aligned matrix; under a rotation the
scale sits on the off-diagonal, the formula reads zeros, and the code takes the
"this is a rotation, not a crop" branch and silently drops the crop — which is
exactly the 0.4.0 defect, affecting 14 files with `crop_box: null` in the
sidecar and nothing in the audit. The box is derived by mapping the four
corners of the result viewport through the matrix and taking the bounding box,
so there is one derivation rather than two. Even inside the classifier's 2%
identity tolerance a matrix can resolve to a real crop, so **the box is the
authority and the label is not**; where the box cannot be resolved the file is
reported `unsupported` rather than assumed uncropped.

In the desktop app the destination tree therefore follows the **framing**, not
the named mode. Deciding by anything else files a cropped image in the tree
whose job is to keep the full frame.

## Dedup keys on whole-file SHA-256

One output per distinct whole-file SHA-256 — not per distinct pixel payload.
That is the owner's decision, taken knowingly. Roughly 146 output pairs are
therefore pixel-identical, differing only by a few bytes of save timestamp in a
property stream.

**Those are expected and the audit must not report them as faults.** The audit
reports them as `expected_pixel_identical_groups`, which is a description, not a
warning. The filename-preservation rule still applies *within* each hash group,
because one hash maps to several source paths.

## Validate with a different tool than the one that wrote

**ExifTool writes the tags. Pillow (plus `defusedxml` for XMP) reads them back.**
Writing and auditing with the same tool proves much less than it appears to.

This read-back used to use `pyexiv2` and no longer does: `pyexiv2` is GPL-3.0
and bundles a GPL-2.0-or-later `exiv2.dll`, so importing it from the shipped
package would relicense the Windows executable. It remains a *development*
dependency, where tiers 2 and 3 use it as a third opinion on the same files —
never packaged. A test fails if `validator.py` imports it again.

One caveat stated honestly: the images themselves are written with Pillow and
re-opened with Pillow, so the size and format checks are a same-tool round
trip. The *tag* chain — the part the rule is about — is genuinely two tools.

## Never hardcode a declared size

Read each file's declared size and use it everywhere: tile grid, padding crop,
audit. Do not derive the top resolution index from the image width either —
read it from the resolution count, because some files have fewer resolutions
than the norm. Seven distinct declared sizes occur in this archive; 1152×864 is
merely the most common.

## Never call Pillow's `FpxImagePlugin` in the batch path

Run over 1,265 files, Pillow's built-in FlashPix plugin opened 39 and raised on
1,224. **Two files hard-crashed the CPython process** — access violation, heap
corruption, nondeterministic. An in-process crash takes the whole batch run
down.

The custom decoder is the primary path and not a fallback. The plugin is usable
only as an **out-of-process** correctness oracle; the 39 files it did open
matched the custom reconstruction at 0.0 mean absolute difference.

## Filenames are the only human-authored content

No captions, titles or notes exist in any property set in this archive. The
filename is the only thing a person wrote about the picture, and a folder name
is the same thing one level up.

That is why `--name-template` **requires `{name}`**. A pattern that drops it
destroys, for every file it renames, something re-reading the source cannot
recover. Unlike a wrong date, it is not fixable afterwards, so it is refused
rather than warned about. Within a hash group, prefer the human-authored name
over a camera-generated twin, and record every contributing path in the sidecar.

Related: **do not normalise doubled file extensions.** Files differing only by
a repeated extension can be genuinely different pixels.

## Other rules worth not rediscovering

- **Stored FILETIMEs are LOCAL wall-clock time, not UTC.** Do not
  timezone-convert them. The timezone map governs which `OffsetTime*` value is
  written and nothing more.
- **A parser that returns errors is not a parser that raises.**
  `propset.parse_propset` reports malformed input by returning a property set
  carrying `errors`. A caller that guards only with `try/except` therefore
  treats corrupt input as valid-but-empty — which is how a corrupt `Transform`
  stream read as "this file has no transform" and produced byte-identical
  output and an identical audit line to a file that genuinely has none. Check
  `pset.ok`.
- **A run that renames or refiles is not the same run.** `run-state.json`
  records the filename pattern and the folder arrangement beside the output
  specs, and a change to any of them invalidates the resume. Resuming across
  one would skip nothing and move nothing, leaving half a tree in each shape
  with nothing recording which is which.
- **A conversion writes only the images it was asked for.** The `.fpx` copy
  (`--source-copy`) and the raw-property sidecar (`--sidecar`) are opt-in. The
  source archive is read-only and still there, so the copy duplicates something
  that was never at risk, and the sidecar is re-derivable with `metadata`.
- **The batch engine never aborts the run on one bad file**, and resumes by
  hash — so an interrupted run costs the file in flight, not the batch.
- **Keep paths short.** Windows long-path support is off by default; the writer
  pre-checks each output path against the 259-character limit and reports the
  file rather than failing obscurely inside the filesystem.
