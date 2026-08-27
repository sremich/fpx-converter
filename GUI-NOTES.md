# 1.1.0 desktop app — notes for folding into the committed docs

Scratch file for the branch `feat/1.1.0-desktop-app`. Everything here belongs
in `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `DECISIONS.md` or the wiki, which
are being edited on `main` and were left alone here. **Delete this file once
it has been folded in.**

---

## For `CLAUDE.md` — Commands

A second venv, because the pipeline that runs over the archive must not
depend on a GUI toolkit:

```sh
# desktop app + packaging (short path, same reason as the other one)
py -3.14 -m venv C:\venvs\fpxgui
C:\venvs\fpxgui\Scripts\python.exe -m pip install -r requirements-gui.txt

# run the window
C:\venvs\fpxgui\Scripts\python.exe -m fpx_gui

# build the standalone exe
C:\venvs\fpxgui\Scripts\python.exe -m PyInstaller --noconfirm packaging/fpx-converter.spec
```

`C:\venvs\fpx` is unchanged and still runs the CLI and tiers 1–2. The GUI venv
also runs the whole suite (it includes `requirements-dev.txt`), and it is the
only one that runs `tests/test_gui_window.py`, which skips cleanly elsewhere.

Two new `convert` flags, both of which exist for the front end but are CLI
features in their own right:

- `--progress` — mirror each per-file `conversion.log` line onto stdout,
  flushed. The trail had only ever gone to the log file, so anything watching
  a 687-file run saw a header, an hour of silence, and a summary.
- `--stop-file PATH` — stop cleanly at the next file boundary if `PATH`
  appears, still writing `audit_report.json`. For a caller that cannot deliver
  a console signal to this process; see the cancellation note below.

## For `CLAUDE.md` — Milestone plan

`1.1.0 — Desktop app` is built. Suggested tick with a note that it wraps the
CLI as planned, ships as one Windows exe, and that the release job still needs
wiring (below).

## For `CLAUDE.md` — Testing tiers

Tier 1 and tier 2 both grew, and **none of it needs the personal archive or a
display**:

- Tier 1: `test_gui_invoke.py`, `test_gui_options.py`, `test_gui_progress.py`,
  `test_gui_summary.py`, `test_batch_hooks.py`.
- Tier 2: `test_gui_e2e.py` runs a real conversion as a child process over
  `tests/fixtures/` and cancels another one partway; `test_gui_window.py`
  drives the widgets under `QT_QPA_PLATFORM=offscreen`.

`test_gui_e2e.py` needs **no PySide6** — `fpx_gui.runner` and its friends are
deliberately Qt-free — so CI's current job runs it as-is. Only
`test_gui_window.py` needs `requirements-gui.txt`, and it `importorskip`s.

## For `CLAUDE.md` — Project-specific binding rules

Worth adding, in the spirit of the existing entries:

> **The desktop app wraps the CLI; it never reimplements it.** Every
> conversion the window starts is `fpx_converter` running as a child process
> with the arguments a person would have typed. Nothing in `fpx_gui` decodes a
> pixel, writes a tag, or decides where a file lands — and the read-only rule
> reaches it as a *call* to `config.ensure_outside_source`, not as a second
> implementation. Two tests fail if that call stops happening.

## For `DECISIONS.md`

Four decisions here are worth a full entry, because each was paid for by a
measurement:

**1. Cancelling needs two mechanisms, not one.** The plan was
`CTRL_BREAK_EVENT` to a child created with `CREATE_NEW_PROCESS_GROUP`, so the
batch engine's existing `KeyboardInterrupt` handling runs and the audit report
still lands. Three things were found:

- `CREATE_NO_WINDOW` does not merely hide a window — it gives the child a
  **new** console. Passing it when we already have one stops the child sharing
  ours, and `GenerateConsoleCtrlEvent` can only reach a process through a
  shared console. Cancel silently degraded to a kill.
- `GetConsoleWindow()` is the usual way to ask "do I have a console", and it
  is wrong here: a pseudo-console has no window, so Windows Terminal and VS
  Code both report 0 while a real console is attached.
  `GetConsoleProcessList` answers it correctly.
- **A console-less parent cannot deliver the signal at all.** From `pythonw`,
  `AttachConsole` against the child fails with `ERROR_INVALID_HANDLE` whether
  the child was created with `CREATE_NO_WINDOW` or `CREATE_NEW_CONSOLE`. That
  is precisely the packaged windowed exe's situation.

So `--stop-file` exists: a marker the parent writes, checked between photos,
raising the same `KeyboardInterrupt` and writing the same report. The signal
is still sent first — it lands immediately rather than at the next boundary —
and the file is what makes the guarantee true. Verified in all three
configurations (terminal, console-less parent, built exe): cancelled within
about a second, `interrupted: true`, report present.

**2. A hard stop must take the process tree.** A one-file PyInstaller exe is a
bootloader whose child is the real program. `terminate()` on the process we
hold would leave a conversion running with nothing watching it, still writing
into the destination. `taskkill /F /T` takes the tree.

**3. `ingest` belongs to the review page, not to Convert.** The gallery reads
thumbnails at `store/<store_name>`, a flat layout neither the nested source
tree nor the nested output tree provides. Putting `ingest` in the Convert
pipeline would copy the whole archive a second time on every run, and nothing
in the conversion needs it. The review-page button pays for it instead, and
`ingest` re-hashes and skips, so the second press costs a read.

**4. The version file is shipped inside the bundle.** `fpx_converter.__init__`
reads `VERSION` from beside the package, which inside a PyInstaller bundle is
the bundle root — so the spec adds `VERSION` as data. That keeps the single
source of truth single; a literal in the spec would have been a second copy.

## For `README.md`

A section for people who do not use a terminal:

- Download `fpx-converter.exe`. Nothing else to install **except ExifTool**
  (`winget install --id OliverBetz.ExifTool`) — that one cannot be bundled.
- Double-click it. Pick the folder holding the photos, pick a folder to put
  the converted ones in, press Convert.
- The folder holding the photos is only ever read from. Choosing a
  destination inside it is refused.
- Resume is on by default: if it is stopped, pressing Convert again picks up
  where it left off.
- "Open review page" builds the gallery and opens it in a browser.
- Developers: `python -m fpx_gui`, `packaging/build.md` for the build.

## For the release workflow (I did not touch `.github/`)

A build-and-attach job needs to:

1. run on `windows-latest` with `python-version: '3.14'`;
2. `pip install -r requirements-gui.txt` (this includes the pinned
   PyInstaller, so no separate install step and no floating version);
3. `python -m PyInstaller --noconfirm packaging/fpx-converter.spec`;
4. smoke-test the artifact before attaching it — **not** just that the file
   exists:
   `dist\fpx-converter.exe --run-cli --version` must print the contents of
   `VERSION` (if it prints `unknown`, `VERSION` did not make it into the
   bundle), and a two-file convert over `tests/fixtures/` must exit 0. That
   second one is the check that catches a missing `pyexiv2` binary or Pillow
   plugin, which a `--version` call cannot see. It needs
   `choco install exiftool` and `FPX_REQUIRE_EXIFTOOL`, exactly as the test
   job already does.
5. attach `dist/fpx-converter.exe` to the release.

Worth knowing: the build takes about 75 seconds and the artifact is ~67 MB,
which is over GitHub's 25 MB inline attachment comfort zone but well under the
2 GB release-asset limit.

There is also a case for a **second CI job that installs
`requirements-gui.txt` and runs the full suite**, so `tests/test_gui_window.py`
actually executes somewhere instead of skipping in every job. Today the
existing job installs `requirements-dev.txt`, so that file's 16 tests are
skipped in CI. Everything else in `fpx_gui` is covered by tests that run
there.

## Things I did not do

- **`.github/workflows/` untouched**, as instructed — see above for what the
  job needs.
- **No screenshot committed.** The window was rendered in both themes and
  checked by eye during the build, but a PNG in the repo trips
  `test_no_personal_data_is_tracked`'s suffix list, and an exception for it
  would weaken the guard that matters most here.
- **Tier 3 and tier 4 not run.** No `.env`, no archive, and this branch
  changes no decode, metadata or layout logic. The two CLI-side changes
  (`--progress`, `--stop-file`) touch the batch loop's bookkeeping, so tier 3
  before merge would be cheap insurance.
- **One thing left unverified:** the cancel path was exercised through the
  built exe driven by a console-less parent process, which is the same
  situation as the window. It was not exercised by *clicking Cancel in the
  running window* — that needs a person at the machine. The mechanism
  underneath is identical and is tested.
