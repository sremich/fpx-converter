"""The check that keeps copyleft code out of the published executable.

This project is published under Apache-2.0 and its executable is downloaded
by people who are given no other terms. Two things would silently change that:

* **pyexiv2**, which is GPL-3.0 and carries `exiv2.dll` (GPL-2.0-or-later)
  beside it. It is a development dependency -- the read-back validator uses
  it, and validating with a different tool than the one that wrote is a rule
  this project keeps -- but nothing in a *shipped* conversion needs it, and a
  bundled copy would make the whole binary GPL-3.0.
* **PySide6-Addons**, some of whose modules are offered under GPLv3 only
  rather than LGPLv3. The application uses QtCore, QtGui and QtWidgets, all of
  which are in PySide6-Essentials, so the Addons wheel is not installed at
  all and its modules cannot be found by anything.

Naming them in `excludes` is necessary and is **not sufficient**. PyInstaller's
analyser follows imports it discovers at build time, hooks add binaries the
spec never mentions, and a denylist fails open: the day a package is renamed,
re-vendored, or pulled in as somebody else's dependency, the exclusion stops
matching and the build succeeds with the file inside it. Nothing about the
resulting exe looks different.

So the exclusion is checked rather than trusted. `check_bundle` reads what the
analysis actually resolved -- every binary, every data file, every pure module
-- and raises before the exe is written. A licence violation is not something
to notice after publishing.

Kept out of the `.spec` so it can be unit-tested: a spec file is executed by
PyInstaller with injected globals and cannot be imported by a test.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

#: Name fragments that must not appear anywhere in the bundle, and the reason,
#: which is quoted into the failure so a future build error explains itself.
FORBIDDEN_FRAGMENTS: tuple[tuple[str, str], ...] = (
    ("exiv2", "pyexiv2 / exiv2 is GPL and would relicense the whole executable"),
    ("pyexiv2", "pyexiv2 is GPL-3.0 and would relicense the whole executable"),
)

#: Distributions that must not be installed in the environment doing the
#: build. Excluding a module the build machine does not have is a rule that
#: cannot fail open; excluding one it does have is a rule that can.
FORBIDDEN_DISTRIBUTIONS: tuple[tuple[str, str], ...] = (
    (
        "PySide6-Addons",
        "some Qt Addons modules are offered under GPLv3 only. The application "
        "uses Essentials modules alone, so install PySide6-Essentials and "
        "shiboken6 rather than the PySide6 metapackage",
    ),
)


class LicenceLeak(Exception):
    """Raised when the bundle would carry something it may not carry."""


def _entry_names(entry: object) -> tuple[str, ...]:
    """The strings worth inspecting in one TOC entry.

    PyInstaller TOC entries are `(destination_name, source_path, typecode)`,
    and either of the first two can be the thing that gives a package away: a
    binary renamed on the way in still comes from a path with its name in it.
    """
    if isinstance(entry, str):
        return (entry,)
    if isinstance(entry, Sequence):
        return tuple(str(part) for part in entry[:2] if part is not None)
    return (str(entry),)


def offenders(toc: Iterable[object]) -> list[tuple[str, str]]:
    """Every entry that must not be shipped, as `(entry, why)` pairs.

    Matched on a lowercased substring of both the destination and the source
    path. Deliberately blunt: this is the last check before an executable is
    published under the wrong licence, and a false positive costs a
    conversation while a false negative costs a licence violation.
    """
    found: list[tuple[str, str]] = []
    for entry in toc:
        names = _entry_names(entry)
        haystack = " ".join(names).lower().replace("\\", "/")
        for fragment, why in FORBIDDEN_FRAGMENTS:
            if fragment in haystack:
                found.append((names[0] if names else str(entry), why))
                break
    return found


def check_bundle(*tocs: Iterable[object]) -> None:
    """Raise `LicenceLeak` if anything forbidden reached the bundle."""
    found: list[tuple[str, str]] = []
    for toc in tocs:
        found.extend(offenders(toc))
    if not found:
        return
    listing = "\n".join(f"  {name}  --  {why}" for name, why in sorted(set(found)))
    raise LicenceLeak(
        "This build would publish an Apache-2.0 executable containing "
        f"copyleft code:\n{listing}\n\n"
        "Nothing here is a naming problem to work around. Find what pulled "
        "the package in and remove the dependency; do not widen the exclude "
        "list and re-run."
    )


def installed_distributions() -> set[str]:
    """Every distribution installed in the environment running the build."""
    from importlib import metadata

    return {
        (dist.metadata["Name"] or "").lower()
        for dist in metadata.distributions()
        if dist.metadata["Name"]
    }


def check_build_environment(installed: set[str] | None = None) -> None:
    """Raise `LicenceLeak` if the build environment can supply what it must not.

    Checked because it is the only version of this rule that cannot fail open:
    a module that is not installed cannot be found by an analyser, a hook, or
    a dependency nobody read.
    """
    present = installed if installed is not None else installed_distributions()
    bad = [
        (name, why)
        for name, why in FORBIDDEN_DISTRIBUTIONS
        if name.lower() in present
    ]
    if not bad:
        return
    listing = "\n".join(f"  {name}  --  {why}" for name, why in bad)
    raise LicenceLeak(
        "The build environment has packages this executable may not "
        f"contain:\n{listing}\n\n"
        "Rebuild in an environment installed from requirements-gui.txt."
    )
