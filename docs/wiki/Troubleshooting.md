# Troubleshooting

## ExifTool not installed or not on PATH

**Symptom:** `convert` does not crash. Every file's images are still written to disk, but each one is reported as `FAILED` with `ExifTool executable not found; metadata tags not embedded`, both in `conversion.log` and on stderr, and the command exits with status 2.

**Cause:** ExifTool is an external binary dependency that performs the metadata writing, and it is not a Python package included in `requirements.txt` or `requirements-dev.txt`. When it cannot be located on `PATH` (or via `FPX_EXIFTOOL`), the writer skips the tagging step and records the failure per file instead of raising.

**What to do:** Install ExifTool using Windows Package Manager:
```sh
winget install --id OliverBetz.ExifTool
```

## A destination inside the source root is refused

**Symptom:** The command fails immediately with a `SourceWriteRefused` exception, stating that nothing may be written under the source root.

**Cause:** The source archive is treated as strictly read-only. Specifying a destination for the manifest, ingested files, or converted outputs that lies inside the source directory violates this rule and is enforced in code to prevent accidental modification or truncation of irreplaceable files.

**What to do:** Provide a destination path that is outside the source archive, such as a dedicated output directory in the repository root or another short path.

## Output paths exceed the Windows path limit

**Symptom:** Depends on where the long path occurs:
- During `pip install` into the virtual environment, package installation can fail outright or leave a corrupted install.
- During `convert`, the writer checks each output path's length before writing anything; an over-long path is reported per file as `output path is N characters, over the 259 Windows allows without long-path support ... Use a shorter --dest`, and that file is marked failed. No image is written for it.
- During `ingest`, there is no such pre-check; an over-long path surfaces as whatever `OSError` the filesystem raises (commonly a `FileNotFoundError` or a Windows-specific errno), caught and reported as `FAILED <name>: copy failed: ...` rather than crashing the run.

**Cause:** Windows long-path support is disabled on the development machine, so the classic 260-character (259 usable) limit applies to virtual environments, working directories, and every output path.

**What to do:** Ensure your virtual environment, working directories, and output root are created at short, shallow paths (e.g., `C:\fpx-output`).

## The `check-dates` command reports failures

**Symptom:** Running `check-dates --strict` exits non-zero and reports that album import timestamps disagree with the folder names.

**Cause:** The Kodak import-batch stamp disagrees with the folder-name ground truth on 7 of 9 dated albums in this corpus, sometimes off by several months or a whole calendar year. This is the expected state and is exactly why `DateTimeOriginal` is not derived from the import timestamp.

**What to do:** Run the command without the `--strict` flag to view the detailed ground-truth report without treating it as a regression. The gate fails under `--strict` to highlight any worsening of the known state.

## The audit report shows `complete: false`

**Symptom:** The `audit_report.json` file contains `"complete": false`, and the summary output warns of a partial run where manifest entries were not handled.

**Cause:** The batch conversion did not attempt every file in the manifest. This happens if the run was interrupted with Ctrl-C, or if the `--limit` flag was passed to the `convert` command. The report is written once, at the end of the run's loop (or as soon as a Ctrl-C is caught) — a genuine process crash or kill, as opposed to an orderly interruption, usually leaves no updated report at all rather than one flagged incomplete.

**What to do:** Re-run the `convert` command without the `--limit` flag. The batch engine resumes by hash and will pick up where it left off.

## A run is interrupted with Ctrl-C

**Symptom:** A batch conversion run is killed by the operator, printing `INTERRUPTED by the operator` and leaving the batch unfinished.

**Cause:** The `convert` command caught a `KeyboardInterrupt`.

**What to do:** Re-run the `convert` command. The batch engine writes the current state and audit report before exiting, so resuming costs only the single file that was in flight at the moment of interruption.

## `album-dates.json` is rejected for naming a month or a year

**Symptom:** The `convert` command exits immediately, before converting anything, with `album dates: <AlbumDateError>` stating that a date is not a single day in `YYYY-MM-DD` form, or that a month or a year cannot be written as a capture date.

**Cause:** The EXIF standard has no way to record a partial date. Supplying a month or a year would force the tool to invent a specific day (like the first of the month), which fabricates a capture moment that no evidence supports. 

**What to do:** Provide a specific, single day in `YYYY-MM-DD` format if you know it. If you do not know the exact day, leave the date field blank in the gallery and allow the album to remain undated.

## Pixel-identical outputs

**Symptom:** The conversion summary reports files in pixel-identical groups, and the `audit_report.json` lists `"expected_pixel_identical_groups"`.

**Cause:** Deduplication is keyed on the whole source file SHA-256 rather than the pixel payload. Two source files can have identical pixels but differ by a few bytes in a property stream timestamp. The tool intentionally preserves both to avoid discarding valid metadata.

**What to do:** Do nothing. This is expected behavior and these files are not considered faults or errors in the conversion process.
