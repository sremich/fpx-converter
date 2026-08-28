# Troubleshooting

Symptom first. Most of these are the tool behaving as designed and saying so.

---

## Getting the app to run at all

### Windows says "Windows protected your PC"

A blue box fills the screen and the only button is **Don't run**. The app is
not code-signed — certificates cost money annually and this is a free tool — so
SmartScreen treats it as an unrecognised program. Click the small **More info**
link above the button, then **Run anyway**.

### The browser will not let me keep the download

Chrome and Edge say the file "isn't commonly downloaded" and may hide it. Same
cause. Open the browser's downloads list, click the **…** beside the file,
choose **Keep**, then **Keep anyway** if asked again.

### My antivirus flagged it

The app is packed into a single file with PyInstaller, and one-file bundles are
a well-known heuristic false positive — a guess about the packaging, not a
detection of anything inside. If you would rather not take that on trust, read
the source and build your own copy; [BUILD.md](BUILD.md) has the steps, and a
build you made yourself will not be flagged.

---

## The conversion

### The app says every photo failed

Almost always **ExifTool is missing**. It writes the metadata, it is a separate
program with its own licence, and it is not bundled.

```powershell
winget install --id OliverBetz.ExifTool
```

Then **close the terminal, open a new one**, and check with `exiftool -ver`.

Current versions refuse to start without it: one clear message, nothing
written, exit code `1`. On an older copy you may instead see every file written
and every file reported failed — the fix is the same. If ExifTool is installed
somewhere not on `PATH`, point at it with `--exiftool C:\path\to\exiftool.exe`,
or set `FPX_EXIFTOOL` in `.env`.

### It refuses my destination folder

> refusing to use … it is inside the read-only source archive

The source archive is strictly read-only, and that is enforced in code rather
than left to the caller — a destination inside it would eventually mean writing
over an original. Choose a folder outside your photo collection.

### The run stopped on its own / I pressed Cancel

`convert` catches the interruption, saves its state, and writes the audit report
before returning. Run it again: it resumes by source hash, so an interruption
costs the file that was in flight, not the batch.

If the desktop app says the converter **had to be killed**, no report was
written for that run. The photographs already converted are still there and are
still good; press Convert again to carry on.

### The report says `"complete": false`

The run did not attempt every entry in the manifest — it was interrupted, or
`--limit` was passed. Read it alongside the failure count: zero failures over
three of six hundred files is not a passing run, it is an unfinished one. Run
`convert` again without `--limit`.

### Some files failed with a path-length error

> output path is N characters, over the 259 Windows allows without long-path
> support

Windows long-path support is off by default, and past that limit the failure
from deep inside a save is an opaque `FileNotFoundError`. Choose a shorter
destination — a top-level folder like `C:\converted` rather than something
nested inside Documents and OneDrive — or shorten your filename pattern. If
your machine has long-path support enabled, `--max-path 0` turns the check off.
The same applies to virtual environments when running from source: a deep path
can corrupt a `pip install` outright.

### A warning about the colour space

> colour-space-assumed: … Check the colour by eye before trusting this file.

The file did not declare its colour space, or declared one this decoder does
not recognise, so it was decoded as NIF RGB — which almost every file in this
format really is. It is a warning rather than a failure because refusing would
fail conversions that are almost certainly right. **Open the file and look at
it:** this project has already shipped two mis-decoded photographs that came
out solidly green, past every automated check it had.

### Some outputs are pixel-identical

The report lists `expected_pixel_identical_groups`. Deduplication keys on the
whole-file SHA-256, not on the pixels, so two source files that differ only by
a timestamp inside a property stream both convert. This is expected, it is not
a fault, and both are kept because the metadata differs.

---

## Dates and names

### All my filenames are zeros

`0000-00-00_000000_DCP12345.jpg` is the archive being honest.

**There is no capture date in these files.** The only timestamp is an
import-batch stamp — when the photographs reached a computer, not when they
were taken — and on the reference corpus it disagrees with the folder names for
most dated albums, one by a whole calendar year. So it is never written as a
capture date, and any part of a filename the evidence does not support is
written as zeros rather than invented.

You can supply the dates you know through the review page:
[see below](#how-do-i-save-the-json-from-the-review-page), and
[DATES.md](DATES.md) for the whole picture.

### `check-dates` fails

Under `--strict` it exits non-zero when an album's import stamps disagree with
its folder name. On this kind of corpus that is the **expected** state — it is
the evidence behind not trusting the import stamp — so the gate is opt-in. Run
it without `--strict` to read the table. Its value is in showing you whether
things get worse, not in passing.

### My dates file was rejected

> album dates: … is not a single day

EXIF has no way to record "sometime in 2001". Supplying a month, a year, a
season or a range would force the tool to invent a day, so the whole file is
refused before anything converts rather than being rounded to the first of
something.

Give a single day as `YYYY-MM-DD`, or leave the box blank. A blank is a
legitimate answer, and no tag at all is the correct output when nobody can name
the day.

### My photos got the wrong time zone

The zone decides the UTC offset recorded beside each timestamp. It **never
shifts the stored time** — the times in these files are already local
wall-clock time, and converting them would move about a fifth of a typical
collection onto the previous calendar day.

Resolution order is `--timezone`, then `FPX_DEFAULT_TZ`, then this machine's
own system zone. So a collection converted on a laptop in a different country
than the photographs were taken in picks up the laptop's zone. Set it
explicitly:

```sh
python -m fpx_converter convert --timezone Europe/London
```

In the window, use the **Time zone** box. Any IANA zone name works. If some
albums were shot elsewhere, `FPX_TZ_OVERRIDES` in `.env` maps album names to
zones individually.

Fixing it means re-running with the right zone and `--no-resume`, since the
already-converted files are recorded as done.

### The Convert button is greyed out

Your filename pattern is missing `{name}`, or is otherwise invalid — the
message under the box says which. `{name}` is required because those filenames
are the only human-authored content in an archive like this, and a pattern
without it discards them permanently for every file it renames.

---

## The review page

### Where did `source-files/` come from?

Pressing **Open review page** runs `ingest` first. The page shows a thumbnail
of every photograph, and those come out of the `.fpx` files themselves, so it
needs one copy of each distinct photograph in one flat folder:
`<destination>/source-files/`. For a large collection that can be gigabytes.

The app asks before it starts and tells you roughly how much space it needs.
Your source folder is only read from and is not changed, and the copies are
yours to delete once you have finished with the review page.

### How do I save the JSON from the review page?

There is no download button. At the bottom of the page, press **Rebuild from
the boxes above**; a text box fills with JSON. Select it, copy it, and save it
as a plain-text file called **`album-dates.json`** beside the manifest.

- From the **desktop app**, that is your *Save into* folder, next to
  `manifest.json`.
- From the **command line**, it is beside whatever `--manifest` points at.
  Running `gallery` prints the exact path it will look in.

Then run `convert` again. It reads the file, writes those dates as
`DateTimeOriginal`, and records `date_source: owner-supplied`.

### The review page says there is nothing to review

There is no finished run in that destination — no `audit_report.json`. Convert
some photographs first.

---

## Still stuck

Open an issue at
<https://github.com/sremich/fpx-converter/issues> with the relevant lines from
`conversion.log` and the `counts` block from `audit_report.json`. **Please do
not attach photographs, folder names or filenames from a personal archive** —
the failure is almost always visible without them.
