"""Tier-1 environment guards.

These are deliberately small. They exist so the CI test command is a real
gate from the first commit rather than a warning, and so the two failure
modes that would silently poison an archival run -- a missing native
extension, or a version drifting out of the pinned set -- surface on push
instead of halfway through a 1,265-file batch.

No real photos, no external tools: tier 1 by definition.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Kodak's camera-generated filenames. Not captions -- the absence of one.
_CAMERA_NAME = re.compile(r"(?i)(dcp|dsc|dcs|img|pic|mvc|p)[_-]?\d+")


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

    # --others --exclude-standard adds files that are not committed yet but
    # would be by the next `git add -A`. Plain `git ls-files` checks only
    # what is already in the index, so a brand-new file with a leak in it
    # passes right up until the moment it is committed -- which is exactly
    # how a real album name got into two new files and pushed.
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
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


def test_ci_requires_exiftool_and_installs_it() -> None:
    """CI must run the ExifTool-dependent tier-2 tests, not skip them.

    Those tests are the only place this project actually exercises its
    "validate with a different tool than the one that wrote" rule: ExifTool
    writes, pyexiv2 reads back. GitHub's Windows runners ship no ExifTool,
    so without an install step they skip -- and a green suite then claims
    coverage that ran nowhere.

    Guarding the workflow file rather than trusting it: dropping either line
    below would restore the silent skip, and nothing else would notice.
    """
    workflows = REPO_ROOT / ".github" / "workflows"
    # Both gates, not just the push one: a release must never be cut on a
    # suite weaker than the one that guards an ordinary push.
    for name in ("ci.yml", "release.yml"):
        workflow = (workflows / name).read_text(encoding="utf-8")
        assert "choco install exiftool" in workflow, f"{name} no longer installs ExifTool"
        assert "FPX_REQUIRE_EXIFTOOL" in workflow, (
            f"{name} no longer sets FPX_REQUIRE_EXIFTOOL, so a missing ExifTool "
            f"would skip the tier-2 metadata tests instead of failing the run"
        )


def test_no_developer_home_paths_are_hardcoded() -> None:
    """No absolute path into a developer's home directory in shipped code.

    One of these used to point ExifTool into a named user's home directory,
    which made the tool unfindable on any other machine and, worse,
    unhideable on
    the machine that had it -- every attempt to test the missing-tool branch
    silently found the real binary. Paths belong in `.env`.
    """
    offenders: list[str] = []
    # `[\\/]` is a class of backslash-or-slash. Written as `[\/]` it is just
    # an escaped forward slash, which makes the pattern blind to
    # `C:\Users\...` -- the only form it exists to catch.
    pattern = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+(?!<)[A-Za-z0-9_.-]+", re.IGNORECASE)
    for path in sorted((REPO_ROOT / "fpx_converter").glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{lineno}")
    assert not offenders, f"hardcoded home-directory paths: {offenders}"


def test_no_personal_name_from_the_archive_is_tracked_in_git() -> None:
    """No album name and no human-authored filename appears in a tracked file.

    Checked against `source-files/manifest.json` — the actual list — rather
    than against a hand-written pattern list. That distinction matters: a
    guessed list of "holiday plus year" patterns passed this repository while
    six real album names sat in the test suite, in a file whose own docstring
    said it used invented names only. Only the real inventory can answer this.

    Skips where the manifest is absent (CI, a fresh clone, a worktree). That
    is not a hole: the leak it guards against can only be introduced on a
    machine that has the archive, which is the same machine that has the
    manifest.

    Single dictionary words are ignored. Some album folders are named things
    like "Sample", and banning that string from the codebase would be absurd;
    what must not appear is a distinctive multi-word or year-bearing name.

    The comparison is **case-insensitive**, and every tracked file is read,
    not a chosen list of extensions. The first version of this test did
    neither, and reported clean while a real album name sat in the test suite
    differing from the folder only in the capitalisation of one letter. A
    guard that can be evaded by pressing shift is not a guard.
    """
    manifest_path = REPO_ROOT / "source-files" / "manifest.json"
    if not manifest_path.is_file():
        import pytest

        pytest.skip("no local manifest; this guard only applies where the archive is")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries", [])

    personal = {a for e in entries for a in e.get("albums", []) if a}
    # Human-authored filenames too, not only albums. `CLAUDE.md` bans
    # "personal filenames, album names, or photo captions", and it also says
    # filenames ARE the captions -- "the only human-authored content in the
    # archive". A guard that covered albums alone left 109 of the 611 stems
    # in this manifest unprotected, which is most of the actual captions.
    fixture_stems = {
        path.name.split(".")[0].lower()
        for path in (REPO_ROOT / "tests" / "fixtures").glob("*")
        if path.is_file()
    }
    for entry in entries:
        if not entry.get("preferred_name_is_human_authored"):
            continue
        stem = entry.get("preferred_name", "").split(".")[0].strip()
        if not stem:
            continue
        # A camera-generated name carries no human intent -- it is the
        # opposite of a caption, and the codebase uses one as the worked
        # example of exactly that. The manifest's human-authored flag says
        # True for a few of them, so the pattern is checked here rather than
        # trusted from the flag.
        if _CAMERA_NAME.fullmatch(stem):
            continue
        # A committed fixture is the sanctioned exception: Kodak stock
        # samples, not family photos. Some of them are also in the archive,
        # which is why their names appear in both places.
        if stem.lower() in fixture_stems:
            continue
        personal.add(stem)

    # Distinctive = more than one word, or containing a digit. A single
    # dictionary word is excluded: some folders are named things like
    # "Sample", and banning that string from the codebase would be absurd.
    distinctive = {s for s in personal if len(s.split()) > 1 or any(c.isdigit() for c in s)}

    # splitlines, not split: a tracked path containing a space would
    # otherwise be torn into fragments and never opened.
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    folded = [(name, name.lower()) for name in distinctive]
    offenders: list[str] = []
    for rel in tracked:
        path = REPO_ROOT / rel
        try:
            text = path.read_text(encoding="utf-8").lower()
        except (OSError, UnicodeDecodeError):
            # Binary or unreadable: nothing to match a folder name against.
            continue
        for name, needle in folded:
            if needle in text:
                # Report the file and the length only. Printing the string
                # would put the very thing this test exists to keep out of
                # git into a CI log.
                offenders.append(f"{rel}: a {len(name)}-character personal name")

    assert not offenders, (
        "album names or human-authored filenames from the archive are committed "
        f"to git (CLAUDE.md forbids this): {sorted(offenders)}"
    )
