# Converting an Archive

This guide explains how to convert a FlashPix archive from end to end using the 
`fpx-converter` tool.

## 1. Scan the source archive

The first step is to walk the source archive and write a manifest. The source 
tree is treated as strictly read-only.

```sh
python -m fpx_converter scan
```

Flags:
* `--source`: Override the `FPX_SOURCE_ROOT` environment variable.
* `--manifest`: Where to write the manifest file.
* `--progress-every N`: Print progress every N files.
* `--resample N`: How many files to re-hash to prove the source is unchanged 
  (default: 25). Set to 0 to disable content re-verification.

## 2. Ingest the files

Copy one file per distinct SHA-256 hash into the local store, deduplicating the 
archive.

```sh
python -m fpx_converter ingest
```

Flags:
* `--manifest`: Path to the manifest file.
* `--dest`: Output directory for the local store.
* `--dry-run`: Walk through the ingestion process without copying files.
* `--allow-unverified`: Allow ingestion even if the manifest's scan did not 
  prove the source was unchanged.

## 3. Verify the store

Verify that the local store matches the manifest.

```sh
python -m fpx_converter verify
```

Flags:
* `--manifest`: Path to the manifest file.
* `--dest`: Path to the ingested `.fpx` store directory.

## 4. Extract metadata

Extract full metadata from the files and emit raw JSON sidecars. 

```sh
python -m fpx_converter metadata
```

Flags:
* `--manifest`: Path to the manifest file.
* `--store`: Path to the ingested `.fpx` store directory.
* `--dest`: Output directory for the sidecars.
* `--dry-run`: Walk through the process without writing files.

## 5. Convert the images

The batch engine performs the conversion into standard formats. It is resilient 
to interruptions and does not abort on a single bad file.

```sh
python -m fpx_converter convert
```

Flags:
* `--manifest`: Path to the manifest file.
* `--store`: Path to the ingested `.fpx` store directory.
* `--dest`: Output root directory.
* `--limit N`: Limit the number of files to convert.
* `--dry-run`: Walk through the conversion without writing images.
* `--no-resume`: Convert every entry again, ignoring previous state.
* `--archive-format`: File format for the archive tree (choices: `tiff`, `jpeg`;
  default: `tiff`).
* `--archive-framing`: Which pixels the archive copy keeps (choices: `full`, 
  `cropped`; default: `full`).
* `--sharing-format`: File format for the sharing tree (choices: `tiff`, `jpeg`;
  default: `jpeg`).
* `--sharing-framing`: Which pixels the sharing copy keeps (choices: `full`, 
  `cropped`; default: `cropped`).
* `--no-archive`: Do not write the archive tree.
* `--no-sharing`: Do not write the sharing tree.
* `--source-copy`: Also copy each source `.fpx` beside its converted image.
  Off by default.
* `--sidecar`: Also write the `.fpx.json` raw-property dump beside each image.
  Off by default.
* `--folder-scheme`: How the output tree is arranged (choices: `album`, `year`,
  `year-month`, `flat`, `custom`; default: `album`).
* `--folder-template`: With `--folder-scheme custom`, the folders to file each
  image under (default: `{year}/{album}`).
* `--name-template`: What each converted image is called, before its extension
  (default: `{year}-{month}-{day}_{time}_{name}`).
* `--album-dates`: JSON file of album to date mappings you supplied via gallery.

### Output format and framing

Format and framing are independent settings. Format controls how the pixels are 
stored (`tiff` for lossless Deflate, `jpeg` for quality-95 4:4:4). Framing 
controls which pixels are kept (`full` for every captured pixel, `cropped` for 
the composition framed in the Kodak software).

By default, the tool outputs a full-frame TIFF for the archive and a cropped 
JPEG for sharing. You can change this using the format and framing flags.

Example 1: A cropped TIFF in the archive tree.
```sh
python -m fpx_converter convert --archive-framing cropped
```

Example 2: A full-frame JPEG in the sharing tree.
```sh
python -m fpx_converter convert --sharing-framing full
```

### What a run writes

By default a photograph produces exactly the images you asked for and nothing
else — a full-frame TIFF in `archive/` and a cropped JPEG in `sharing/`.

Two more files are available per photograph, each behind its own flag:

* `--source-copy` puts a copy of the original `.fpx` beside its converted
  image. Your source folder is only ever read from and is still there, so this
  is a second copy of something that was never at risk — useful if you want the
  originals and the conversions to travel together, unnecessary otherwise.
* `--sidecar` writes `.fpx.json`, every property the file holds, as JSON. It
  can be rebuilt from the original at any time with the `metadata` command.

Until 1.2.0 both were written on every conversion, so asking for one photograph
produced four files.

### Where the files go

`--folder-scheme` chooses the shape of the output tree. Both `archive/` and
`sharing/` get the same shape.

| Scheme | Result | Notes |
|--------|--------|-------|
| `album` (default) | `2002/Summer 2002/` | Your folder names, kept. A folder somebody typed outranks any date the tool can work out. Tool-made names — a zip file's, `New Folder` — are replaced by the year and month. |
| `year` | `2002/` | |
| `year-month` | `2002/2002 July/` | Where only the year is known, the file sits directly in the year folder. No month is invented. |
| `flat` | no subfolders | |
| `custom` | whatever `--folder-template` says | |

A folder pattern uses `/` between levels and may use `{year}`, `{month}` and
`{album}`. An empty level is dropped, so `{year}/{month}/{album}` gives
`2002/07/Summer 2002`.

Where nothing dates a file at all, `year` and `year-month` file it under
`undated/`; a custom pattern writes `0000` and `00`, the same way the filename
does, so the preview shows you what you are asking for.

A folder's year and month may come from an album name or from the import
stamp — a folder is a browsing affordance, not a claim, and this is the same
licence `album` has always taken. They are deliberately *not* the same values a
filename's date prefix uses, which track only what can be defended.

### What the files are called

`--name-template` sets the filename, before the extension. The fields are:

| Field | Example | |
|-------|---------|--|
| `{year}` | `2002` | `0000` where unknown |
| `{month}` | `07` | `00` where unknown |
| `{day}` | `04` | `00` where unknown |
| `{date}` | `2002-07-04` | shorthand for `{year}-{month}-{day}` |
| `{time}` | `143210` | `000000` where unknown |
| `{name}` | `Backyard` | the filename from your archive, without `.fpx` |
| `{album}` | `Summer 2002` | |

Two rules are enforced rather than advised:

* **`{name}` is required.** Filenames are the only human-authored content in
  this kind of archive — no captions, titles or notes survive anywhere else.
  A pattern that drops them throws that away for every file it renames, and
  unlike a wrong date it cannot be recovered by re-reading the source.
* **A date component the evidence does not support stays zeroed.** `{month}`
  for a file dated only to its year is `00`, never `01`. `01` would name a
  month nobody established. On this kind of corpus most files have no date at
  all, so most filenames are mostly zeros — that is the archive telling you
  the truth, not the tool failing.

```sh
# day first, no time
python -m fpx_converter convert --name-template "{day}-{month}-{year}_{name}"

# the year is in the folder already, so leave it out of the name
python -m fpx_converter convert --folder-scheme year --name-template "{name}"
```

A pattern is checked once, before the run starts, so a mistake costs a message
rather than a half-renamed output tree.

### Artifacts and tree layout

After a run, the destination contains:
* `conversion.log`: An append-only text log flushed after every file, detailing 
  what happened.
* `run-state.json`: Internal resume state, keyed on the source SHA-256 hash.
* `audit_report.json`: A JSON report describing the entire output tree.
* `archive/`: The archival copies (full-frame TIFF by default). The original
  `.fpx` and its `.fpx.json` sidecar land here too, if `--source-copy` or
  `--sidecar` asked for them.
* `sharing/`: The shareable copies (cropped JPEG by default).

### Resuming a run

The batch engine resumes by hash. A file counts as done if it is marked as 
converted in `run-state.json` and its output files are present on disk. 

A resumed run will redo work if:
* The `--no-resume` flag is passed.
* The output files have been deleted from disk.
* The output specifications (format or framing) have changed, which
  invalidates the previous state.
* The filename pattern or the folder arrangement has changed. A run that
  renames or refiles is not the same run: resuming across the change would
  skip nothing and move nothing, leaving half the tree in each shape.

## 6. Review the gallery and supply dates

Generate a local HTML QA page to review the conversion and provide missing 
dates.

```sh
python -m fpx_converter gallery
```

Flags:
* `--dest`: Conversion output root.
* `--report`: Path to `audit_report.json`.
* `--manifest`: Path to the manifest file.
* `--store`: Path to the ingested `.fpx` store directory.
* `--sidecars`: Directory of `.fpx.json` sidecars, for dates.
* `--album-dates`: JSON file of dates you already supplied.
* `--out`: Where to write the HTML page (default: `<dest>/report/index.html`,
  beside the run it describes).
* `--no-thumbnails`: Skip embedding thumbnails.

Open the generated `index.html` file in a browser. You can filter by album and 
audit status. For albums without a capture date, you can supply a date. Save the
JSON it outputs as `album-dates.json` beside the manifest, and re-run the 
`convert` command. The batch engine reads `album-dates.json` and applies these 
dates to the EXIF `DateTimeOriginal` metadata.

## Additional Commands

* `check-dates`: Run the automated album folder ground-truth date check.
  * `--manifest`: Path to the manifest file.
  * `--store`: Path to the ingested `.fpx` store directory.
  * `--strict`: Exit non-zero when any album's import stamps disagree with its 
    folder name.
* `thumbnail`: Extract embedded DIB thumbnails as PNG images.
  * `--manifest`: Path to the manifest file.
  * `--store`: Path to the ingested `.fpx` store directory.
  * `--dest`: Output directory for thumbnails.
  * `--dry-run`: Walk through the process without writing thumbnails.
