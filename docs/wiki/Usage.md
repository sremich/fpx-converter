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

### Artifacts and tree layout

After a run, the destination contains:
* `conversion.log`: An append-only text log flushed after every file, detailing 
  what happened.
* `run-state.json`: Internal resume state, keyed on the source SHA-256 hash.
* `audit_report.json`: A JSON report describing the entire output tree.
* `archive/`: The archival copies (full-frame TIFF by default). Alongside each 
  converted image, the original `.fpx` file and its `.fpx.json` sidecar are 
  copied.
* `sharing/`: The shareable copies (cropped JPEG by default).

### Resuming a run

The batch engine resumes by hash. A file counts as done if it is marked as 
converted in `run-state.json` and its output files are present on disk. 

A resumed run will redo work if:
* The `--no-resume` flag is passed.
* The output files have been deleted from disk.
* The output specifications (format or framing) have changed, which invalidates 
  the previous state.

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
