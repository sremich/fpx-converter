"""Tier-1 environment guards.

These are deliberately small. They exist so the CI test command is a real
gate from the first commit rather than a warning, and so the two failure
modes that would silently poison an archival run -- a missing native
extension, or a version drifting out of the pinned set -- surface on push
instead of halfway through a 1,265-file batch.

No real photos, no external tools: tier 1 by definition.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_version_file_is_three_part() -> None:
    """VERSION is the single source of truth; CI refuses tags that disagree."""
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"VERSION must be three-part X.Y.Z (never '0.4' -- always '0.4.0'), got {version!r}"
    )


def test_version_is_not_duplicated_in_pyproject() -> None:
    """A hand-written version in pyproject would be a second source of truth."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in pyproject["project"], (
        "pyproject must not carry a literal version -- it is dynamic, read from VERSION"
    )
    assert "version" in pyproject["project"]["dynamic"]


def test_runtime_dependencies_import() -> None:
    """pyexiv2 is a compiled extension; an import failure here is unrecoverable."""
    import numpy
    import olefile
    import PIL
    import pyexiv2

    assert numpy.__version__
    assert olefile.__version__
    assert PIL.__version__
    assert pyexiv2.__version__


def test_installed_versions_match_the_pins() -> None:
    """Catch an environment that drifted from requirements.txt."""
    from importlib.metadata import version as installed_version

    pins = {}
    for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, pinned = line.partition("==")
        pins[name] = pinned

    assert pins, "requirements.txt parsed to nothing -- the pin check would pass vacuously"
    mismatched = {
        name: (pinned, installed_version(name))
        for name, pinned in pins.items()
        if installed_version(name) != pinned
    }
    assert not mismatched, f"installed versions differ from requirements.txt pins: {mismatched}"


def test_no_personal_data_is_tracked() -> None:
    """The one rule that must never regress: no personal image lands in git.

    Fixtures under tests/fixtures/ are the single sanctioned exception -- they
    are Kodak stock sample images, not family photos.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    personal_suffixes = (
        ".fpx",
        ".tif",
        ".tiff",
        ".jpg",
        ".jpeg",
        ".png",
        ".wav",
        ".fpx.json",
    )
    offenders = [
        path
        for path in tracked
        if path.lower().endswith(personal_suffixes)
        and not path.startswith("tests/fixtures/")
    ]
    assert not offenders, f"personal media is tracked in git: {offenders}"
