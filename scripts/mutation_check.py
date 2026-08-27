"""Break each load-bearing rule on purpose and check the named tests notice.

A test that cannot fail is worse than no test: it reports that a property is
held without ever having checked it. This project has shipped one of those --
a colour oracle that passed every mutation of a wrong decode, because Pearson
correlation is invariant under a per-channel affine map. So the rules that
would corrupt or lose something get checked the other way round: break them,
and require the suite to go red.

Each mutation names the test file that is supposed to catch it, so a pass here
says the *right* test caught it and not merely that something somewhere went
red. That distinction is not academic. The first version of this script passed
`--timeout` to a virtualenv without `pytest-timeout` installed: every run died
on the argument error, every mutation was scored as caught, and it reported
nine catches it had not made. It now refuses to count a red run that names no
failing test.

    C:\\venvs\\fpxgui\\Scripts\\python.exe scripts/mutation_check.py

Needs the GUI virtualenv, because some of these are caught by the window's
tests. Exits non-zero if any mutation survives. Restores every file it touches,
including on failure -- run it on a clean tree so a crash cannot be mistaken
for an edit. It also takes a lock: two runs at once read each other's
mutations, and one of the ways that goes wrong is a false catch.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

NAMES = "tests/test_name_template.py"
GUI = "tests/test_gui_options.py"
WINDOW = "tests/test_gui_window.py"
CONVERT = "tests/test_cli_convert.py"

#: `(label, file, before, after, tests that must fail)`.
#:
#: `before` must appear exactly once in the file where it matters. Where the
#: same line occurs more than once, `occurrence` picks which one -- see the
#: writer's extras guards, whose text is repeated inside a helper that only
#: *reports* the extras rather than writing them, so mutating the wrong copy
#: proves nothing.
MUTATIONS: list[tuple[str, str, str, str, list[str], int]] = [
    (
        "a filename pattern may drop {name}",
        "fpx_converter/name_template.py",
        "    if REQUIRED_FIELD not in fields:",
        "    if False:",
        [NAMES, GUI, WINDOW],
        1,
    ),
    (
        "a folder pattern may walk upwards",
        "fpx_converter/layout.py",
        '        if level.strip() in ("..", "."):',
        "        if False:",
        [NAMES, GUI],
        1,
    ),
    (
        "a substituted value may walk upwards",
        "fpx_converter/layout.py",
        '        if rendered in (".", ".."):',
        "        if False:",
        [NAMES],
        1,
    ),
    (
        "a reserved device name may come out bare",
        "fpx_converter/name_template.py",
        '    if stem.split(".")[0].lower() in _RESERVED:',
        "    if False:",
        [NAMES],
        1,
    ),
    (
        "year-month invents a January",
        "fpx_converter/layout.py",
        "        if scheme == BY_YEAR or month is None:",
        "        if scheme == BY_YEAR:",
        [NAMES],
        1,
    ),
    (
        "a substituted value keeps its separators",
        "fpx_converter/name_template.py",
        '    return "".join("-" if ch in _FORBIDDEN else ch for ch in text)',
        "    return text",
        [NAMES],
        1,
    ),
    (
        "a folder pattern accepts filename-only fields",
        "fpx_converter/layout.py",
        "            if field in FOLDER_FIELDS:",
        "            if True:",
        [NAMES],
        1,
    ),
    (
        "a folder pattern uses the claimable date, not the filing one",
        "fpx_converter/layout.py",
        '        "year": f"{year:04d}" if year else "0000",',
        '        "year": "0000",',
        [NAMES, WINDOW],
        1,
    ),
    (
        "the default filename is normalised",
        "fpx_converter/name_template.py",
        "    if stem.split(\".\")[0].lower() in _RESERVED:",
        '    stem = stem.strip().rstrip(". ")\n    if stem.split(".")[0].lower() in _RESERVED:',
        [NAMES],
        1,
    ),
    (
        "the source copy is written unasked",
        "fpx_converter/writer.py",
        "        if source_copy:",
        "        if True:",
        [CONVERT],
        2,  # the first is inside `_extras()`, which reports rather than writes
    ),
    (
        "the sidecar is written unasked",
        "fpx_converter/writer.py",
        "        if sidecar:",
        "        if True:",
        [CONVERT],
        2,
    ),
    (
        "a named mode falls back to the custom settings",
        "fpx_gui/options.py",
        "        if self.mode == ARCHIVE:",
        "        if False:",
        [GUI, WINDOW],
        1,
    ),
    (
        "a cropped image is filed in the tree that keeps the full frame",
        "fpx_gui/options.py",
        '        tree = "sharing" if self.custom_framing == "cropped" else "archive"',
        '        tree = "archive"',
        [GUI, WINDOW],
        1,
    ),
    (
        "resume ignores a changed filename pattern",
        "fpx_converter/batch.py",
        '        if raw.get("name_template", name_template_mod.DEFAULT_TEMPLATE) '
        "!= self.name_template:",
        "        if False:",
        [CONVERT],
        1,
    ),
    (
        "resume ignores a changed folder arrangement",
        "fpx_converter/batch.py",
        '        if raw.get("folder_key", layout.BY_ALBUM) != self.folder_key:',
        "        if False:",
        [CONVERT],
        1,
    ),
    (
        "resume ignores a run asking for more files than the last one",
        "fpx_converter/batch.py",
        "        if not set(self.extras).issubset(set(stored)):",
        "        if False:",
        [CONVERT],
        1,
    ),
    (
        "every folder scheme keeps the album naming scope",
        "fpx_converter/layout.py",
        "    if scheme != BY_ALBUM:",
        "    if False:",
        [NAMES],
        1,
    ),
]


def _apply(text: str, before: str, after: str, occurrence: int) -> str:
    """Replace the nth occurrence of `before`, counting from 1."""
    index = -1
    for _ in range(occurrence):
        index = text.index(before, index + 1)
    return text[:index] + after + text[index + len(before) :]


#: Two of these running at once corrupt each other's results. The second run
#: sees the first one's live mutation instead of the line it expected and
#: reports NOT APPLIED -- and the other direction, a red caused by somebody
#: else's mutation being scored as a catch, is the one that would be believed.
#: Both happened before this lock existed.
LOCK = Path(tempfile.gettempdir()) / "fpx-mutation-check.lock"


def main() -> int:
    try:
        handle = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(f"another mutation run holds {LOCK}.")
        print("Wait for it, or delete the file if no run is alive.")
        return 1
    os.write(handle, str(os.getpid()).encode())
    os.close(handle)
    try:
        return _run()
    finally:
        LOCK.unlink(missing_ok=True)


def _run() -> int:
    survivors: list[str] = []
    width = max(len(label) for label, *_ in MUTATIONS) + 2

    for label, rel, before, after, targets, occurrence in MUTATIONS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if original.count(before) < occurrence:
            print(f"{'NOT APPLIED':>16}  {label:<{width}} ({rel})")
            survivors.append(f"{label} (could not be applied)")
            continue

        path.write_text(_apply(original, before, after, occurrence), encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *targets],
                cwd=REPO,
                capture_output=True,
                text=True,
            )
        finally:
            path.write_text(original, encoding="utf-8")

        failed = [ln for ln in proc.stdout.splitlines() if ln.startswith("FAILED")]
        if proc.returncode != 0 and failed:
            print(f"{'caught':>16}  {label}")
            for line in failed[:2]:
                print(f"{'':>16}    {line.split('::')[-1]}")
        elif proc.returncode != 0:
            # Red with no failing test named is an error in the harness, not a
            # catch. This is the case that made the first version worthless.
            print(f"{'ERRORED':>16}  {label}")
            print("\n".join(f"{'':>16}    {ln}" for ln in proc.stdout.splitlines()[-6:]))
            survivors.append(f"{label} (harness error, not a catch)")
        else:
            print(f"{'SURVIVED':>16}  {label}")
            survivors.append(label)

    print()
    if survivors:
        print(f"{len(survivors)} of {len(MUTATIONS)} mutations were not caught:")
        for item in survivors:
            print(f"  - {item}")
        return 1
    print(f"all {len(MUTATIONS)} mutations caught by the tests named for them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
