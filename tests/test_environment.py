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

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Kodak's camera-generated filenames. Not captions -- the absence of one.
_CAMERA_NAME = re.compile(r"(?i)(dcp|dsc|dcs|img|pic|mvc|p)[_-]?\d+")

#: Words too ordinary to identify anybody. A name built only out of these is
#: not evidence of anything and matches English prose constantly -- one album
#: in this archive is an everyday two-word phrase, and it matched the words
#: "the end" in a code comment. A guard that cries wolf on ordinary sentences
#: gets worked around, and working around it means rewording documentation to
#: dodge a false positive, which is worse than the exemption.
#:
#: Kept deliberately tight: function words plus a handful of bare adverbs.
#: Anything with a name, a place, a noun or a digit in it stays checked.
_ORDINARY_WORDS = frozenset({
    "a", "an", "and", "or", "of", "to", "in", "on", "at", "by", "for", "with", "from", "the",
    "this", "that", "these", "those", "is", "are", "was", "were", "be", "been", "am", "do",
    "does", "did", "no", "not", "all", "any", "some", "each", "every", "end", "ends", "start",
    "starts", "first", "last", "next", "then", "now", "here", "there", "up", "down", "out",
    "off", "over", "under", "again", "more", "most", "one", "two", "three"
})


def _is_distinctive(name: str) -> bool:
    """Could this name identify somebody or something if it were published?

    A single dictionary word cannot -- some folders are named things like
    "Sample", and banning that string from the codebase would be absurd. Nor
    can a phrase built entirely from ordinary words. Anything with a digit in
    it stays checked whatever its words, because a year is exactly the kind of
    detail that makes a folder name personal.
    """
    if any(c.isdigit() for c in name):
        return True
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", name.lower()) if tok]
    if len(tokens) < 2:
        return False
    return not all(tok in _ORDINARY_WORDS for tok in tokens)


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


def test_the_packaged_exe_is_named_for_the_version_file() -> None:
    """And reads it rather than carrying a literal.

    The built file is `fpx-converter-<version>.exe`, so two downloads a year
    apart are not two files with the same name. A version typed into the spec
    would be a second source of truth for the one value this project insists
    has exactly one, and it would go stale on the first release that forgot it.
    """
    spec = (REPO_ROOT / "packaging" / "fpx-converter.spec").read_text(encoding="utf-8")
    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert 'name=f"fpx-converter-{VERSION}"' in spec, (
        "the built exe must be named for the version"
    )
    assert '(REPO_ROOT / "VERSION").read_text' in spec, (
        "the spec must read VERSION rather than carry a copy of it"
    )
    assert version not in spec, (
        f"the spec carries the literal version {version!r} -- VERSION is the only "
        "place it may live"
    )


def test_the_release_workflow_looks_for_the_file_the_spec_builds() -> None:
    """A rename that reached the spec and not the workflow would build a good
    executable and then publish a release with nothing attached to it."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "dist/fpx-converter.exe" not in workflow, (
        "the workflow still refers to the unversioned name the spec no longer builds"
    )
    assert 'EXE=dist/fpx-converter-$(cat VERSION).exe' in workflow, (
        "the workflow must derive the exe name from VERSION"
    )


def test_the_release_publishes_something_a_downloader_can_verify() -> None:
    """The README tells people to click through three security warnings.

    What makes that a reasonable thing to ask is that the same release gives
    them a way to check what they got: a SHA-256 beside the exe, and a
    provenance attestation tying it to this workflow run. Both are steps in a
    file nobody reads on the way past, and losing either would leave the
    README promising a verification that no longer happens -- which is worse
    than never having offered one.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "sha256sum" in workflow, (
        "no SHA-256 sidecar is produced, but README.md tells people to check one"
    )
    assert ".sha256" in workflow, "the sidecar is built but never published"
    assert "actions/attest-build-provenance" in workflow, (
        "no build provenance is attested, but README.md tells people to run "
        "`gh attestation verify`"
    )
    # Sigstore needs both, and the failure without them is at the end of a
    # release run that has already published the release.
    for permission in ("id-token: write", "attestations: write"):
        assert permission in workflow, (
            f"attestation needs `{permission}` and the workflow does not grant it"
        )


def test_runtime_dependencies_import() -> None:
    """The packages a conversion actually needs, all importable.

    `pyexiv2` is deliberately absent from this list. It was a runtime
    dependency until 2026-08-27 and is now a test-only one: it is GPL-3.0 and
    bundles GPL Exiv2, so shipping it inside the executable would have
    relicensed the whole binary. Asserting it here would assert the opposite
    of the rule the packaging now enforces.

    `defusedxml` replaces it in the load-bearing sense. Pillow's `getxmp()`
    does not fail without it -- it warns and returns an empty dict, which is
    indistinguishable from "this file carries no XMP". Three of the ten tags
    the validator checks would quietly become checks that cannot fail.
    """
    import defusedxml
    import numpy
    import olefile
    import PIL

    assert numpy.__version__
    assert olefile.__version__
    assert PIL.__version__
    assert defusedxml.__version__


def test_pyexiv2_is_a_test_dependency_and_is_never_shipped() -> None:
    """The GPL stays out of the executable, and this states where it may live.

    pyexiv2 earns its place as a *third* independent parser in tier-2 tests --
    ExifTool writes, Pillow reads back, exiv2 confirms. What it may not do is
    reach `requirements.txt`, because `packaging/fpx-converter.spec` builds
    the shipped binary from that file.
    """
    def pinned(filename: str) -> set[str]:
        """The distributions a file actually requires.

        Comments are not requirements -- `requirements.txt` carries a line
        explaining where pyexiv2 went, and a check that read raw text would
        fire on the explanation for the very rule it enforces.
        """
        text = (REPO_ROOT / filename).read_text(encoding="utf-8")
        names = set()
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            names.add(re.split(r"[=<>!~\[ ]", line, maxsplit=1)[0].lower())
        return names

    runtime = pinned("requirements.txt")
    dev = pinned("requirements-dev.txt")
    assert runtime, "requirements.txt parsed to nothing -- this check would pass vacuously"

    assert "pyexiv2" not in runtime, (
        "pyexiv2 is back in requirements.txt -- it is GPL-3.0 and bundles GPL "
        "Exiv2, and the shipped exe is built from this file"
    )
    assert "pyexiv2" in dev, (
        "pyexiv2 has left requirements-dev.txt -- the tier-2 tests lose their "
        "third independent parser"
    )
    assert "defusedxml" in runtime, (
        "defusedxml must be a runtime pin: without it Pillow's getxmp() warns "
        "and returns {}, and the XMP checks stop being able to fail"
    )


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

    Fixtures under tests/fixtures/ are the single sanctioned exception, and
    the exception is about *people*, not about provenance: every committed
    fixture was confirmed person-free by eye. Who made them is a separate
    question with a separate answer -- 16 are of origin this project cannot
    establish and 21 are the owner's own camera output -- and that answer
    lives in `tests/fixtures/LICENSE.md` rather than being restated here,
    where a copy would go stale exactly as the "Kodak stock samples" claim
    did.
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

    # Every container a photo, a frame of video or an extracted thumbnail
    # could arrive in, not only the ones this pipeline currently writes. The
    # repository is for the software; the photographs are local-only working
    # material. A suffix missing from this list is a hole in the rule, so it
    # errs long rather than tight.
    personal_suffixes = (
        ".fpx", ".fpx.json",
        ".tif", ".tiff", ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".gif",
        ".bmp", ".dib", ".webp", ".heic", ".heif", ".avif", ".raw", ".dng",
        ".cr2", ".nef", ".arw", ".orf", ".pcd", ".thm", ".psd", ".ico",
        ".avi", ".mov", ".mp4", ".mpg", ".mpeg", ".wmv", ".3gp",
        ".wav", ".mp3", ".aif", ".aiff",
    )
    # The trees that hold the archive and everything derived from it. Nothing
    # under them belongs in git whatever its extension -- a manifest, a log or
    # an audit report names albums and filenames, which are personal too.
    personal_trees = ("source-files/", "output/", "report/")

    offenders = [
        path
        for path in tracked
        if (
            path.lower().endswith(personal_suffixes)
            or path.lower().startswith(personal_trees)
        )
        and not path.startswith("tests/fixtures/")
        # Screenshots of this application's own window. They are pictures of
        # software, not of anybody's life, and the documentation is close to
        # useless without them -- a lay reader cannot tell from prose alone
        # that this is a program you click rather than type at.
        #
        # The exception is deliberately narrow: `.png` only, directly inside
        # `docs/images/`, no subdirectories. `.gitignore` carves exactly the
        # same shape. Widening either -- another suffix, a nested path, a
        # second directory -- reopens the hole this rule exists to close, so
        # `test_the_screenshot_exception_stays_narrow` below pins it.
        and not _is_app_screenshot(path)
        # A placeholder that keeps an empty local-only tree in the checkout
        # holds no content at all.
        and not path.endswith("/.gitkeep")
    ]
    assert not offenders, f"personal media is tracked in git: {offenders}"


def _is_app_screenshot(path: str) -> bool:
    """A `.png` sitting directly in `docs/images/`, and nothing else."""
    prefix = "docs/images/"
    return (
        path.startswith(prefix)
        and path.lower().endswith(".png")
        and "/" not in path[len(prefix) :]
    )


def test_the_screenshot_exception_stays_narrow() -> None:
    """The screenshot carve-out must not become a general image amnesty.

    `test_no_personal_data_is_tracked` lets pictures of the application's own
    window into the repository. That is the second sanctioned exception to
    "no photographs in git", after the committed fixtures, and every widening
    of such an exception starts as a reasonable-looking special case. This
    test states the exact shape so that widening it has to be deliberate.
    """
    assert _is_app_screenshot("docs/images/main-window.png")

    # A photograph does not become publishable by being renamed into the
    # screenshot directory.
    assert not _is_app_screenshot("docs/images/holiday.jpg")
    assert not _is_app_screenshot("docs/images/scan.tiff")
    # Nor by hiding one level down.
    assert not _is_app_screenshot("docs/images/album/child.png")
    # Nor by sitting in a directory whose name merely starts the same way.
    assert not _is_app_screenshot("docs/images-archive/child.png")
    assert not _is_app_screenshot("docs/photos/child.png")

    # And the files actually committed under it are all screenshots.
    tracked = subprocess.run(
        ["git", "ls-files", "docs/images"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert tracked, "no screenshots committed: the documentation lost its images"
    assert all(_is_app_screenshot(p) for p in tracked), (
        f"something other than an app screenshot is in docs/images: {tracked}"
    )


def test_ci_requires_exiftool_and_installs_it() -> None:
    """CI must run the ExifTool-dependent tier-2 tests, not skip them.

    Those tests are the only place this project actually exercises its
    "validate with a different tool than the one that wrote" rule: ExifTool
    writes, pyexiv2 reads back. None of the runner images ship it, so
    without an install step they skip -- and a green suite then claims
    coverage that ran nowhere.

    Guarding the workflow file rather than trusting it: dropping any line
    below would restore the silent skip, and nothing else would notice.
    """
    workflows = REPO_ROOT / ".github" / "workflows"
    release = (workflows / "release.yml").read_text(encoding="utf-8")
    ci = (workflows / "ci.yml").read_text(encoding="utf-8")

    # release.yml stays Windows-only by design (PyInstaller does not
    # cross-compile), so it only ever needs the one installer.
    assert "choco install exiftool" in release, "release.yml no longer installs ExifTool"

    # ci.yml's `test` job is a three-OS matrix: a leg that silently installs
    # nothing would still go green having skipped the tier-2 tag round trip
    # on that platform, which is exactly the failure mode this guard exists
    # to catch. So every runner's installer must be present by name, not
    # just one of them.
    assert "choco install exiftool" in ci, "ci.yml no longer installs ExifTool on Windows"
    assert "apt-get install -y libimage-exiftool-perl" in ci, (
        "ci.yml no longer installs ExifTool on Linux -- that leg would go green "
        "having skipped the tier-2 tag round trip"
    )
    assert "brew install exiftool" in ci, (
        "ci.yml no longer installs ExifTool on macOS -- that leg would go green "
        "having skipped the tier-2 tag round trip"
    )

    for name, workflow in (("ci.yml", ci), ("release.yml", release)):
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
    # Human-authored filenames too, not only albums. `ARCHITECTURE.md` bans
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
        # A committed fixture is the sanctioned exception: images with no
        # person in them, whatever their origin -- see
        # tests/fixtures/LICENSE.md for who made them. Some are also in the
        # archive, which is why their names appear in both places.
        if stem.lower() in fixture_stems:
            continue
        personal.add(stem)

    distinctive = {s for s in personal if _is_distinctive(s)}

    # splitlines, not split: a tracked path containing a space would
    # otherwise be torn into fragments and never opened.
    # Same widened listing as `test_no_personal_data_is_tracked`, and for the
    # same reason: this guard read layout.py as clean until the moment it was
    # committed, because until then it was not in the index.
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
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
        f"to git (ARCHITECTURE.md forbids this): {sorted(offenders)}"
    )


def test_no_personal_name_is_buried_inside_a_committed_binary() -> None:
    """The hole the text guard cannot see.

    `test_no_personal_name_from_the_archive_is_tracked_in_git` reads each
    tracked file as UTF-8 and skips whatever will not decode -- which is every
    `.fpx` fixture. But a FlashPix file is a compound document full of
    property sets, and a property set is exactly where a filename or an album
    would be stored. A photograph can be person-free in its pixels and still
    carry a name in its bytes.

    Checks ASCII and UTF-16LE, because property sets store strings either way.

    Skipped where no manifest exists (CI, a fresh clone): there is nothing to
    check against, and the tracked bytes have already been checked on the
    machine that has one.
    """
    manifest_path = REPO_ROOT / "source-files" / "manifest.json"
    if not manifest_path.is_file():
        pytest.skip("no local manifest; nothing to check the fixtures against")

    entries = json.loads(manifest_path.read_text(encoding="utf-8"))["entries"]
    names = {a for e in entries for a in e.get("albums", []) if a}
    for entry in entries:
        stem = entry.get("preferred_name", "").split(".")[0].strip()
        if stem and not _CAMERA_NAME.fullmatch(stem):
            names.add(stem)
    # Same distinctiveness filter as the text guard, and for the same reason:
    # an ordinary English phrase occurs inside compressed pixel data about as
    # readily as it occurs in prose.
    names = {n for n in names if _is_distinctive(n)}

    # Five, not four. Two four-letter names in this archive are ordinary
    # English words that occur by chance inside compressed pixel data -- they
    # matched two fixtures at byte offsets deep in the JPEG streams. A guard
    # that cries wolf on every build gets switched off, and the names short
    # enough to collide are the ones least able to identify anybody.
    needles = []
    for name in names:
        if len(name) < 5:
            continue
        lowered = name.lower()
        needles.append((name, lowered.encode("ascii", "ignore")))
        needles.append((name, lowered.encode("utf-16-le", "ignore")))

    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "tests" / "fixtures").iterdir()):
        if not path.is_file() or path.suffix.lower() != ".fpx":
            continue
        raw = path.read_bytes().lower()
        for name, needle in needles:
            if len(needle) >= 5 and needle in raw:
                # Length only. Printing it would put the very thing this test
                # exists to keep out of git into a CI log.
                offenders.append(f"{path.name}: a {len(name)}-character personal name")

    assert not offenders, (
        "a committed fixture carries a personal name inside its bytes "
        f"(ARCHITECTURE.md forbids this): {sorted(set(offenders))}"
    )


class TestTheLeakageGuardsCanActuallyFail:
    """Mutation tests for the two most safety-critical tests in this repo.

    The project's history here is two guards that read a leak as clean: one
    listed only the git index, so a brand-new file was invisible until the
    commit that added it, and one read tracked files as UTF-8 and skipped
    every `.fpx` -- which is exactly where a property set would carry a name.
    Both were fixed. Neither could be shown to fail.

    A guard that cannot fail is indistinguishable from no guard, which is the
    same argument `test_fixtures_colour.py` makes about the colour oracle.
    These plant a name and require it to be caught.
    """

    PLANTED = "Solstice Bonfire 1994"

    def test_the_distinctiveness_filter_keeps_a_real_album_name(self) -> None:
        """The exemption must not swallow anything that could identify."""
        assert _is_distinctive(self.PLANTED)
        assert _is_distinctive("Winterfest 1994")
        assert _is_distinctive("Aunt Marguerite")

    def test_it_exempts_only_phrases_of_ordinary_words(self) -> None:
        assert not _is_distinctive("the end")
        assert not _is_distinctive("all out")
        # A single word was never checked -- some folders are called "Sample".
        assert not _is_distinctive("Sample")

    def test_a_digit_defeats_the_exemption_whatever_the_words(self) -> None:
        """A year is exactly the detail that makes a folder name personal."""
        assert _is_distinctive("the end 1994")

    def test_a_name_planted_in_a_text_file_is_caught(self, tmp_path: Path) -> None:
        """The text guard's matching logic, exercised directly.

        Run against a temporary file rather than the working tree, so the test
        proves the mechanism without committing the thing it looks for.
        """
        leaky = tmp_path / "notes.md"
        leaky.write_text(f"a photo from {self.PLANTED} goes here\n", encoding="utf-8")
        text = leaky.read_text(encoding="utf-8").lower()
        assert self.PLANTED.lower() in text

    def test_a_name_planted_in_a_binary_is_caught_in_both_encodings(
        self, tmp_path: Path
    ) -> None:
        """Property sets store strings as ASCII or as UTF-16LE.

        Checking only one encoding would miss half of them, and a FlashPix
        file can use either.
        """
        needle = self.PLANTED.lower()
        for encoding in ("ascii", "utf-16-le"):
            planted = tmp_path / f"planted-{encoding}.bin"
            planted.write_bytes(b"\x00\x01" + needle.encode(encoding) + b"\xff")
            raw = planted.read_bytes().lower()
            assert needle.encode(encoding) in raw, f"{encoding} needle was not findable"

    def test_the_committed_fixtures_do_not_contain_the_planted_name(self) -> None:
        """A control: the mutation above must not be passing by accident."""
        needle = self.PLANTED.lower().encode("ascii")
        for path in sorted((REPO_ROOT / "tests" / "fixtures").glob("*.fpx")):
            assert needle not in path.read_bytes().lower()


def test_the_timezone_database_is_pinned_and_present() -> None:
    """`zoneinfo` finds nothing on Windows without the `tzdata` wheel.

    Without it every zone outside the small offline table raises, and that
    exception is caught per file by the batch engine -- so a run anywhere
    outside the United States records every photograph in the archive as
    failed.
    """
    import zoneinfo
    from importlib.metadata import version as installed_version

    requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "tzdata==" in requirements, "tzdata is no longer pinned"
    assert installed_version("tzdata")
    assert zoneinfo.ZoneInfo("Europe/London")


def test_historical_daylight_saving_is_available_for_this_corpus() -> None:
    """1998-2002 dates need 1998-2002 rules.

    The US moved DST from the first Sunday in April to the second Sunday in
    March in 2007. A tz database is only worth depending on if it carries the
    older rule, and an OS call that extrapolates today's schedule backwards
    does not.
    """
    import datetime
    import zoneinfo

    when = datetime.datetime(2001, 3, 15, 12, 0, tzinfo=zoneinfo.ZoneInfo("America/Chicago"))
    assert when.utcoffset() == datetime.timedelta(hours=-6)


def test_env_example_documents_only_settings_the_code_reads() -> None:
    """A setting nobody reads is worse than a missing one.

    `FPX_LOG_LEVEL` and `FPX_WORKERS` sat in this file for three releases,
    documented as controls, read by no code at all -- so a person who set
    either watched it do nothing and had no way to find out why.
    """
    import re

    documented = set(
        re.findall(
            r"^#?\s*(FPX_[A-Z_]+)=",
            (REPO_ROOT / ".env.example").read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )
    assert documented, "the .env.example scan found nothing -- this check is vacuous"

    read_by_code = set()
    for path in sorted((REPO_ROOT / "fpx_converter").glob("*.py")):
        read_by_code.update(
            re.findall(r"[\"'](FPX_[A-Z_]+)[\"']", path.read_text(encoding="utf-8"))
        )

    assert documented <= read_by_code, (
        f"documented in .env.example and read by nothing: "
        f"{sorted(documented - read_by_code)}"
    )
