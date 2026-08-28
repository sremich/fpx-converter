# Command line reference

```sh
python -m fpx_converter <command> [options]
```

The desktop application is a front end over exactly these commands — it builds
an argument list and runs the converter as a child process. Nothing in the
window decodes a pixel or decides where a file lands.

The published executable can be used the same way, with `--run-cli` in front of
the arguments:

```powershell
fpx-converter-1.2.1.exe --run-cli convert --dest C:\converted
```

**ExifTool** must be installed for `convert`; it is a separate program, not a
Python package. See the [README](../README.md#3-install-exiftool).

---

## You probably only need two commands

```sh
python -m fpx_converter scan ./photos --manifest ./work/manifest.json
python -m fpx_converter convert --manifest ./work/manifest.json --dest ./converted
```

`scan` walks your archive read-only and writes a manifest; `convert` reads the
manifest and produces the images. **`ingest`, `verify`, `metadata` and
`thumbnail` are optional side tools, not steps 2, 3 and 4.** In particular,
`convert` reads each photograph from the source path recorded in the manifest
when no local copy exists, so there is no need to duplicate your archive before
converting it. `ingest` exists for the review page (which needs one flat copy
per distinct photograph) and for working offline from a detached source.

## Global options

These come *before* the command name.

| Option | Meaning |
|---|---|
| `--version` | Print the version and exit. |
| `--env-file PATH` | Read settings from exactly this `.env`, instead of searching. |
| `--work-dir PATH` | Where the default manifest, store and `output/` live. Same as `FPX_WORK_DIR`. |

**Where `.env` is looked for**, first hit wins: the current directory, then
your user config directory (`%APPDATA%\fpx-converter` on Windows,
`~/.config/fpx-converter` elsewhere), then beside the package. Real environment
variables beat the file. Nothing in it is required — see
[`.env.example`](../.env.example) for every setting with a comment.

**Where the defaults point.** With no `--work-dir` and no `FPX_WORK_DIR`, the
working root is the current directory — or the checkout, when you are running
from a clone of this repository. It is never the install directory of an
installed copy.

---

## `scan` — walk the source read-only, write the manifest

```sh
python -m fpx_converter scan ./photos --manifest ./work/manifest.json
```

Hashes every `.fpx` under the source root, groups them by SHA-256, records the
human-authored filenames, then proves the tree is unchanged afterwards by
re-stating every file and re-hashing a sample.

| Option | Default | Meaning |
|---|---|---|
| `SOURCE` (positional) | `FPX_SOURCE_ROOT` | The folder holding the `.fpx` photos. Read-only. |
| `--source PATH` | — | The same thing as the positional argument, kept for existing scripts. |
| `--manifest PATH` | `<work>/source-files/manifest.json` | Where to write the manifest. Refused if inside the source root. |
| `--progress-every N` | `100` | Print a progress line every N files. |
| `--resample N` | `25` | How many files to re-hash when proving the source unchanged. `0` disables content re-verification and warns that it did. |

Exit codes: `0` clean, `1` nothing found or bad configuration, `2` the source
tree changed during the scan — investigate before going further.

## `convert` — the conversion

```sh
python -m fpx_converter convert --dest ./converted --progress
```

Reads the manifest, converts every entry it has not already done, and never
lets one bad file end the run. Resume is on by default.

### Where things come from and go

| Option | Default | Meaning |
|---|---|---|
| `--manifest PATH` | `<work>/source-files/manifest.json` | The manifest to convert. |
| `--store PATH` | `<work>/source-files/fpx` | Local `.fpx` store, if you made one with `ingest`. Falls back to the manifest's own source paths. |
| `--dest PATH` | `FPX_OUTPUT_ROOT`, else `<work>/output` | Output root. Refused if inside the source root. |
| `--limit N` | all | Convert only the first N manifest entries. Does not change where anything lands. |
| `--dry-run` | off | Walk without writing; report any source file that cannot be found. |
| `--no-resume` | off | Ignore what previous runs recorded and convert everything again. |

### What gets written

| Option | Default | Meaning |
|---|---|---|
| `--archive-format {tiff,jpeg}` | `tiff` | Format for the `archive/` tree. TIFF is Deflate-compressed and lossless. |
| `--archive-framing {full,cropped}` | `full` | Which pixels the archive copy keeps. |
| `--sharing-format {tiff,jpeg}` | `jpeg` | Format for the `sharing/` tree. JPEG is q95, 4:4:4. |
| `--sharing-framing {full,cropped}` | `cropped` | Which pixels the sharing copy keeps. |
| `--no-archive` | off | Do not write the archive tree. |
| `--no-sharing` | off | Do not write the sharing tree. With the defaults this leaves only the full-frame lossless TIFF. |
| `--source-copy` | off | Also copy each source `.fpx` beside its image. |
| `--sidecar` | off | Also write the `.fpx.json` raw-property dump beside each image. |

Format and framing are **independent axes**. A full-frame JPEG for people who
do not open TIFFs is `--no-archive --sharing-framing full`.

`--source-copy` and `--sidecar` are off because a run should write only the
images you asked for. Your source archive is read-only and still there, so the
copy duplicates something that was never at risk; the sidecar can be rebuilt at
any time with `metadata`.

### Names and folders

| Option | Default | Meaning |
|---|---|---|
| `--folder-scheme {album,year,year-month,flat,custom}` | `album` | How the output tree is arranged. `custom` reads `--folder-template`. |
| `--folder-template PATTERN` | `{year}/{album}` | With `--folder-scheme custom`, the folders each image is filed under. One level per `/`. |
| `--name-template PATTERN` | `{year}-{month}-{day}_{time}_{name}` | What each image is called, before its extension. |

**Filename fields:** `{year}` `{month}` `{day}` `{date}` `{time}` `{name}`
`{album}`. **`{name}` is required** — filenames are the only human-authored
content in an archive like this, and a pattern that drops them destroys, for
every file it renames, something no amount of re-reading the source can
recover.

**Folder fields are a different, smaller vocabulary: `{year}`, `{month}` and
`{album}` only.** Asking for `{day}` or `{time}` in a folder pattern is refused
rather than answered, and `..` is refused outright. The two vocabularies are
deliberately not shared, because they do not draw on the same date values: a
folder may use the import stamp's year, while a filename's date fields zero out
anything undefensible. Reusing one for the other was written and caught — a
custom `{year}/{album}` filed almost everything under `0000/` while
`--folder-scheme year`, the same word, correctly said `2002/`. Both patterns
are validated **once, before the run starts**, and changing either invalidates
a resume: a run that renames or refiles is not the same run.

### Dates, time zones and tools

| Option | Default | Meaning |
|---|---|---|
| `--album-dates PATH` | `album-dates.json` beside the manifest | Album → `YYYY-MM-DD` dates you supplied via the gallery. |
| `--timezone ZONE` | see below | IANA zone the photographs were taken in, e.g. `Europe/London`. |
| `--exiftool PATH` | `FPX_EXIFTOOL`, else `PATH` | The ExifTool executable. |
| `--max-path N` | 259 on Windows, no limit elsewhere | Refuse an output path longer than N characters. `0` turns the check off. |

**Time zone resolution**, in order: `--timezone`, then `FPX_DEFAULT_TZ`, then
this machine's own system zone, and if none of those resolves, the run refuses
to start. Any IANA zone works. It **never shifts a stored timestamp** — those
are already local wall-clock time — it only decides which `OffsetTimeOriginal`
and `OffsetTimeDigitized` values are recorded beside them. `FPX_TZ_OVERRIDES`
maps individual albums to different zones.

The zone is resolved and *proved* once, before the first file. So is ExifTool:
a missing ExifTool is a fact about the machine, not about any photograph, so it
is one clear refusal and exit `1` with nothing written. `--max-path` exists
because Windows long-path support is off by default and the failure past 259
characters is an opaque `FileNotFoundError` from deep inside a save; macOS and
Linux have per-component limits rather than a whole-path one, so it is off
there.

### Watching and stopping a run

| Option | Meaning |
|---|---|
| `--progress` | Mirror each per-file log line onto stdout. The desktop app uses this to drive its progress bar. |
| `--stop-file PATH` | Stop cleanly at the next file boundary if `PATH` appears, still writing the audit report. |

<kbd>Ctrl</kbd>+<kbd>C</kbd> is the direct way to stop, and it is better where
it works — it lands immediately, and `convert` catches it, saves state and
writes the report before returning. `--stop-file` is for a caller that cannot
deliver a console signal to a child process on Windows, where the alternative
is killing it, and a killed run is the one ending that leaves no report at all.

A stop marker is only honoured if it is **newer than the run**, so a stale one
cannot wedge a destination for ever.

Exit codes: `0` finished cleanly, `1` refused before starting (bad
configuration, missing ExifTool, unresolvable zone, bad pattern) or
interrupted, `2` one or more files failed.

---

## The three files a run leaves behind

All three sit in the destination root.

### `conversion.log`

Append-only text, flushed after every line, so it survives a crash. One line
per file: `OK` with the output count and the time taken, or `FAIL` with the
reason. `WARN` lines carry things worth a look that did not fail the file — an
unresolvable viewing transform, or a **colour space the file never declared**,
which is decoded as NIF RGB and says so.

### `audit_report.json`

Describes the **output tree**, not the invocation — a corpus built across three
sessions still produces one complete picture. Keyed on source SHA-256. The
things to read:

- `counts` — converted, resumed, failed, with warnings, and how many manifest
  entries were never reached.
- `complete` — true only when every manifest entry was attempted and the run
  was not interrupted or limited. **Read it alongside the failure count:** zero
  failures over three of 687 files is not a passing run, it is an unfinished
  one.
- `unexplained_failures` — failures with no recorded explanation.
- `expected_pixel_identical_groups` — files whose pixels match exactly.
  Deduplication keys on whole-file SHA-256, not pixels, so two files differing
  only by a timestamp in a property stream both convert. **This is expected and
  is not a fault.**
- `failures` — the full record for each one.

### `run-state.json`

The resume state, keyed on source SHA-256. It also records the output specs,
the filename pattern, the folder arrangement and which optional extras were
asked for. Change any of those and the resume is invalidated — resuming across
such a change would skip nothing and move nothing, leaving half a tree in one
shape and half in the other.

A killed run therefore costs the file in flight, not the batch.

---

## `gallery` — the review page and the album-dates round trip

```sh
python -m fpx_converter gallery --dest ./converted
# writes ./converted/report/index.html
```

One self-contained HTML file over a finished run: every photograph as a
thumbnail decoded from its own embedded DIB, filterable by album and by audit
status, failures outlined in red, and a date box beside every album holding an
undated photograph.

| Option | Default | Meaning |
|---|---|---|
| `--dest PATH` | `FPX_OUTPUT_ROOT`, else `<work>/output` | The conversion output root. |
| `--report PATH` | `<dest>/audit_report.json` | The audit report to build from. |
| `--manifest PATH` | `<work>/source-files/manifest.json` | Used to locate `album-dates.json`. |
| `--store PATH` | `<work>/source-files/fpx` | The `.fpx` store the thumbnails are read from. |
| `--sidecars PATH` | — | Directory of `.fpx.json` sidecars, for dates. |
| `--album-dates PATH` | beside the manifest | Dates you already supplied, shown pre-filled. |
| `--out PATH` | `<dest>/report/index.html` | Where to write the page. |
| `--no-thumbnails` | off | Skip the thumbnails. Much faster, much less useful. |

The thumbnails come from the `.fpx` files, so the store has to exist — run
`ingest` first, or point `--store` at one.

**The round trip**, which is the only route by which a defensible capture date
enters the archive from outside the files:

1. `convert`, then `ingest`, then `gallery`.
2. Open the page, fill in the dates you know.
3. Save the JSON it renders as `album-dates.json`, beside the manifest.
4. `convert` again. Those dates are written as `DateTimeOriginal` with
   `date_source: owner-supplied`, ranking above the folder name and far above
   the import stamp.

A date must be a **single day** in `YYYY-MM-DD`. A month, a year, a season or a
range is refused at parse time and the whole file is rejected before anything
converts, rather than being rounded to a first day. See [DATES.md](DATES.md).

---

## The side tools

### `ingest` — one copy per distinct photograph

```sh
python -m fpx_converter ingest --dest ./work/fpx
```

Copies one file per distinct SHA-256 into a flat local store. Needed by
`gallery` for thumbnails; otherwise optional. **It can be a large amount of
data.**

| Option | Default | Meaning |
|---|---|---|
| `--manifest PATH` | `<work>/source-files/manifest.json` | |
| `--dest PATH` | `<work>/source-files/fpx` | Refused if inside the source root. |
| `--dry-run` | off | Say what would be copied. |
| `--allow-unverified` | off | Ingest from a manifest whose scan did not prove the source unchanged. |

### `verify` — re-hash the store

```sh
python -m fpx_converter verify
```

Re-hashes every ingested copy against the manifest. `--manifest`, `--dest`.
Exit `2` on any mismatch.

### `metadata` — raw property sidecars

```sh
python -m fpx_converter metadata --dest ./work/sidecars
```

Dumps every property the files carry — all ten property sets plus the two
extension storages — as `.fpx.json`. `--manifest`, `--store`, `--dest`,
`--dry-run`, `--timezone`.

### `check-dates` — the album ground-truth report

```sh
python -m fpx_converter check-dates
```

Prints a table comparing each album's folder name against the import stamps of
the files inside it. `--manifest`, `--store`, `--timezone`, and `--strict`.

It **reports by default and only fails under `--strict`**. On the corpus this
was built from the import stamp misses most dated albums, one by a whole
calendar year — which is precisely why it is not trusted as a capture date. A
failing strict gate there is the expected state, not a regression; its value is
in telling you whether that state gets *worse*.

### `thumbnail` — extract the embedded DIBs

```sh
python -m fpx_converter thumbnail --dest ./work/thumbs
```

Writes each file's embedded thumbnail as a PNG. `--manifest`, `--store`,
`--dest`, `--dry-run`. Useful as an independent check on orientation and
framing — but note that a 96-pixel thumbnail is evidence, not sight, and it
cannot settle a colour question on its own. See [TESTING.md](TESTING.md).
