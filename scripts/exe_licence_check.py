"""Check the *built executable* for copyleft code, after PyInstaller has run.

`packaging/licence_guard.py` already refuses a bundle containing pyexiv2 or
`exiv2.dll`, and it is mutation-tested. It has one weakness, and it is the
weakness every spec-level check has: it runs **inside the build**. Comment out
the call, break the import, edit the spec, or hit a PyInstaller version whose
`Analysis` no longer exposes what it reads, and the build succeeds, the guard
is silent, and the published exe is GPL. Nothing about the file looks
different.

So this reads the finished artefact instead. Different input (the exe on disk,
not the analysis that produced it), different moment (after the build, in the
release workflow), different failure mode. Two checks that can only fail
together if both are removed on purpose.

## Why not simply grep the exe for "exiv2"

Because this project's own source says the word. `fpx_converter/validator.py`
documents, in a docstring that is compiled into the bundle, that pyexiv2 is
GPL-3.0 and carries a GPL-2.0-or-later `exiv2.dll` -- which is exactly the
sentence that keeps the rule explained where it is enforced. A bare substring
scan would match that and fail every clean build, and a check that cries wolf
on every green build gets switched off.

Two layers instead, neither of which matches prose:

* **Archive entry names.** PyInstaller records what it bundled, by name, in
  the exe's own table of contents. Read that back and the bare fragment is
  safe to match: a *file* called anything containing `exiv2` is a leak, and no
  docstring is a filename. This is authoritative.
* **Artefact byte needles**, for when the table cannot be read. These are the
  concrete file and directory names pyexiv2 ships under -- `exiv2api`,
  `libexiv2`, `pyexiv2/lib` -- chosen because they appear nowhere in the
  packages that go into the bundle. Checked against the raw bytes as ASCII and
  as UTF-16LE, because Windows resource strings are wide.

`--require-toc` makes the first layer mandatory, which is what the release
workflow passes: on a machine that just ran PyInstaller, being unable to read
a PyInstaller archive is a failure, not a reason to fall back quietly.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

#: Matched against bundle entry *names*, where a bare fragment is exactly
#: right: these name files, and a file is not prose. Same list, and the same
#: reasoning, as `packaging.licence_guard.FORBIDDEN_FRAGMENTS`; kept here as
#: well rather than imported so that removing the spec-level guard cannot also
#: disarm this one.
FORBIDDEN_NAME_FRAGMENTS: tuple[str, ...] = ("exiv2", "pyexiv2")

#: Matched against raw bytes. Every one of these is a real path or symbol
#: pyexiv2 ships, and none of them occurs anywhere in `fpx_converter` or
#: `fpx_gui` -- which is what makes them usable where the bare word is not.
FORBIDDEN_BYTE_NEEDLES: tuple[str, ...] = (
    "exiv2api",
    "libexiv2",
    "pyexiv2/lib",
    "pyexiv2\\lib",
    "pyexiv2.libs",
)

#: Read in chunks, overlapping by more than the longest needle so a match
#: straddling a boundary is not missed. An exe is ~60 MB and a release runner
#: has the memory, but a scanner that quietly depends on that is a scanner
#: that quietly stops working.
_CHUNK = 4 << 20


class LicenceLeak(Exception):
    """Raised when the built executable carries something it may not carry."""


def offending_names(names: Iterable[str]) -> list[str]:
    """Every bundle entry name that must not be in an Apache-2.0 executable."""
    found: list[str] = []
    for name in names:
        lowered = str(name).lower().replace("\\", "/")
        if any(fragment in lowered for fragment in FORBIDDEN_NAME_FRAGMENTS):
            found.append(str(name))
    return sorted(set(found))


def bundle_entry_names(exe_path: Path) -> list[str]:
    """What PyInstaller recorded in the exe's own table of contents.

    Raises `LicenceLeak` if the archive cannot be read: on the machine that
    just built it, that is a broken check rather than a clean bundle, and the
    difference must not be reported as a pass.
    """
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except Exception as exc:  # noqa: BLE001 -- any import failure is the same failure
        raise LicenceLeak(
            f"PyInstaller is not importable, so the bundle's table of contents "
            f"could not be read: {exc}"
        ) from exc

    try:
        reader = CArchiveReader(str(exe_path))
        toc = reader.toc
    except Exception as exc:  # noqa: BLE001
        raise LicenceLeak(
            f"{exe_path} could not be read as a PyInstaller archive: {exc}"
        ) from exc

    if isinstance(toc, dict):
        return [str(name) for name in toc]
    return [str(entry[-1] if isinstance(entry, (list, tuple)) else entry) for entry in toc]


def _needle_bytes() -> list[tuple[str, bytes]]:
    encoded: list[tuple[str, bytes]] = []
    for needle in FORBIDDEN_BYTE_NEEDLES:
        encoded.append((needle, needle.lower().encode("ascii")))
        encoded.append((needle, needle.lower().encode("utf-16-le")))
    return encoded


def scan_bytes(exe_path: Path) -> list[str]:
    """Artefact needles found in the raw file, as the needles that matched."""
    needles = _needle_bytes()
    overlap = max(len(raw) for _, raw in needles)
    found: set[str] = set()
    tail = b""
    with exe_path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            window = (tail + chunk).lower()
            for needle, raw in needles:
                if raw in window:
                    found.add(needle)
            tail = window[-overlap:]
    return sorted(found)


def check_executable(exe_path: Path, require_toc: bool = False) -> list[str]:
    """Both layers over one built exe. Raises `LicenceLeak` on any hit."""
    if not exe_path.is_file():
        raise LicenceLeak(f"{exe_path} does not exist, so nothing was verified")

    findings: list[str] = []
    checked: list[str] = []

    try:
        names = bundle_entry_names(exe_path)
    except LicenceLeak:
        if require_toc:
            raise
        names = None
    else:
        checked.append(f"{len(names)} bundle entries")
        findings += [f"bundle entry: {name}" for name in offending_names(names)]

    checked.append("raw bytes")
    findings += [f"artefact string: {needle}" for needle in scan_bytes(exe_path)]

    if findings:
        listing = "\n".join(f"  {item}" for item in findings)
        raise LicenceLeak(
            f"{exe_path.name} is published under Apache-2.0 and contains "
            f"copyleft code:\n{listing}\n\n"
            "packaging/licence_guard.py should have refused this build. Find "
            "out why it did not -- a bypassed guard is the finding here, not "
            "just the file. Do not widen either list."
        )
    return checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("exe", type=Path)
    parser.add_argument(
        "--require-toc",
        action="store_true",
        help="fail if the PyInstaller table of contents cannot be read, "
        "instead of falling back to the byte scan alone.",
    )
    args = parser.parse_args(argv)

    try:
        checked = check_executable(args.exe, require_toc=args.require_toc)
    except LicenceLeak as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    print(f"{args.exe.name}: no copyleft code found ({', '.join(checked)} checked).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
