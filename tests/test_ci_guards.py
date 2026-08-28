"""The two CI guards, exercised failing.

A CI check nobody has seen fail is not a check -- it is a step that has always
been green, which looks identical to a step that can never be red. Both guards
here live in `scripts/` rather than inline in a workflow for exactly this
reason: a workflow step cannot be run from a test.

* `scripts/history_leak_guard.py` reads git *history*, which the two leakage
  guards in `test_environment.py` have never done. They list
  `git ls-files --cached --others`, which is the working tree, and that is why
  a child's name and two album names sat in five commits across five releases
  with every guard green.
* `scripts/exe_licence_check.py` reads the built executable, after
  PyInstaller has run, so that removing or breaking the spec-level licence
  guard is not enough to publish a GPL binary under Apache-2.0.

Nothing here contains a personal string, and neither does either script. The
history guard is configured with needles from outside the repository; the
needles planted below are nonsense words chosen to be obviously synthetic.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import exe_licence_check as exe_guard  # noqa: E402
import history_leak_guard as history_guard  # noqa: E402

#: Not a name, not an album, not a word. The point of the test is the
#: mechanism; a realistic needle would put a realistic string in a public
#: repository, which is the thing the guard exists to prevent.
PLANTED = "zzqx-planted-needle-zzqx"


def _run(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small real repository. `git` is what is being tested, so it is real."""
    root = tmp_path / "r"
    root.mkdir()
    _run(root, "init", "-b", "main")
    _run(root, "config", "user.email", "t@example.invalid")
    _run(root, "config", "user.name", "T")
    (root / "README.md").write_text("clean\n", encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-m", "first")
    return root


class TestACleanHistoryPasses:
    """Otherwise the failing tests below prove only that the guard says no."""

    def test_nothing_planted_and_nothing_found(self, repo: Path) -> None:
        assert history_guard.check_history(repo, needles=[PLANTED]) == []

    def test_the_projects_own_history_is_clean_by_shape(self) -> None:
        """The check as CI will actually run it, against the real repository.

        Skipped on a shallow clone rather than run against one. `actions/checkout`
        fetches a single commit by default, and the `test` and `gui` jobs have no
        reason to pay for the full history -- so in those jobs this would fail
        every time, not because anything leaked but because there was nothing to
        look at. The guard refusing a shallow clone is the behaviour we want; it
        is asserted directly in `TestItRefusesToScanNothing` below.

        The real scan of the real history is the dedicated `history` job, which
        sets `fetch-depth: 0` precisely so this check means something there.
        """
        root = Path(__file__).resolve().parent.parent
        if not (root / ".git").exists():
            pytest.skip("not a git checkout")
        shallow = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout.strip()
        if shallow == "true":
            pytest.skip(
                "shallow clone: the full-history scan is the `history` CI job, "
                "which sets fetch-depth: 0"
            )
        assert history_guard.check_history(root, needles=[]) == []


class TestAPlantedNeedleIsFound:
    def test_in_a_file_that_is_still_there(self, repo: Path) -> None:
        (repo / "notes.md").write_text(f"about {PLANTED} here\n", encoding="utf-8")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-m", "adds it")
        with pytest.raises(history_guard.HistoryLeak) as excinfo:
            history_guard.check_history(repo, needles=[PLANTED])
        assert "needle" in str(excinfo.value)

    def test_in_a_file_that_was_deleted_afterwards(self, repo: Path) -> None:
        """The failure that actually happened. A later commit does not undo it."""
        leaky = repo / "notes.md"
        leaky.write_text(f"about {PLANTED} here\n", encoding="utf-8")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-m", "adds it")
        leaky.unlink()
        _run(repo, "add", "-A")
        _run(repo, "commit", "-m", "removes it")

        # The working tree is spotless, which is all the existing guards see.
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert PLANTED not in listed

        with pytest.raises(history_guard.HistoryLeak):
            history_guard.check_history(repo, needles=[PLANTED])

    def test_in_a_commit_message(self, repo: Path) -> None:
        (repo / "other.md").write_text("x\n", encoding="utf-8")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-m", f"mentions {PLANTED}")
        with pytest.raises(history_guard.HistoryLeak):
            history_guard.check_history(repo, needles=[PLANTED])

    def test_on_a_branch_that_was_never_merged(self, repo: Path) -> None:
        """`--all`, not `HEAD`. A pushed branch is as public as `main`."""
        _run(repo, "checkout", "-b", "side")
        (repo / "notes.md").write_text(f"{PLANTED}\n", encoding="utf-8")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-m", "side")
        _run(repo, "checkout", "main")
        with pytest.raises(history_guard.HistoryLeak):
            history_guard.check_history(repo, needles=[PLANTED])

    def test_the_report_names_the_commit_but_never_the_needle(self, repo: Path) -> None:
        """CI logs on a public repository are public."""
        (repo / "notes.md").write_text(f"{PLANTED}\n", encoding="utf-8")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-m", "adds it")
        with pytest.raises(history_guard.HistoryLeak) as excinfo:
            history_guard.check_history(repo, needles=[PLANTED])
        message = str(excinfo.value)
        assert PLANTED not in message, "the guard printed the thing it guards"
        assert history_guard.redact(PLANTED) in message


class TestTheShapeLayerNeedsNoConfiguration:
    """It is the layer a fork gets, and the one that cannot be forgotten."""

    @pytest.mark.parametrize(
        "name", ["holiday.fpx", "out.tif", "out.jpeg", "manifest.json", "conversion.log"]
    )
    def test_a_committed_photo_or_run_output_is_found_with_no_needles(
        self, repo: Path, name: str
    ) -> None:
        target = repo / name
        target.write_bytes(b"not really an image")
        _run(repo, "add", "-f", name)
        _run(repo, "commit", "-m", "oops")
        with pytest.raises(history_guard.HistoryLeak) as excinfo:
            history_guard.check_history(repo, needles=[])
        assert name in str(excinfo.value)

    def test_the_sanctioned_fixture_directory_is_not_a_finding(self, repo: Path) -> None:
        fixture = repo / "tests" / "fixtures"
        fixture.mkdir(parents=True)
        (fixture / "Clouds01.fpx").write_bytes(b"fixture")
        _run(repo, "add", "-f", "tests/fixtures/Clouds01.fpx")
        _run(repo, "commit", "-m", "fixture")
        assert history_guard.check_history(repo, needles=[]) == []


class TestItRefusesToScanNothing:
    def test_a_shallow_clone_is_refused_rather_than_passed(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """`actions/checkout` is shallow by default, and one commit passes."""
        (repo / "second.md").write_text("x\n", encoding="utf-8")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-m", "second")

        shallow = tmp_path / "shallow"
        subprocess.run(
            ["git", "clone", "--depth", "1", "--no-local", repo.as_uri(), str(shallow)],
            check=True,
            capture_output=True,
        )
        with pytest.raises(history_guard.HistoryLeak, match="shallow"):
            history_guard.check_history(shallow, needles=[])

    def test_require_needles_refuses_an_unconfigured_run(self, repo: Path) -> None:
        with pytest.raises(history_guard.HistoryLeak, match="no needles"):
            history_guard.check_history(repo, needles=[], require_needles=True)


class TestWhereTheNeedlesComeFrom:
    """Not from this repository. See the module docstring in the guard."""

    def test_the_guard_source_contains_no_needle_of_its_own(self) -> None:
        source = (
            Path(history_guard.__file__).read_text(encoding="utf-8").lower()
        )
        assert "fpx_leak_needles" in source, "the environment seam is the design"
        assert "needles-file" in source

    def test_the_environment_supplies_them(self) -> None:
        loaded = history_guard.load_needles({"FPX_LEAK_NEEDLES": f"# a note\n{PLANTED}\n\n"})
        assert loaded == [PLANTED]

    def test_a_file_outside_the_tree_supplies_them(self, tmp_path: Path) -> None:
        path = tmp_path / "needles.txt"
        path.write_text(f"{PLANTED}\nOther-Needle\n", encoding="utf-8")
        assert history_guard.load_needles({}, path) == [PLANTED, "other-needle"]

    def test_a_needle_too_short_to_mean_anything_is_refused(self) -> None:
        """A two-character needle matches everything and looks like it works."""
        with pytest.raises(history_guard.HistoryLeak, match="3 characters"):
            history_guard.load_needles({"FPX_LEAK_NEEDLES": "ab\n"})


class TestTheBuiltExeIsCheckedIndependently:
    """Defence in depth over `packaging/licence_guard.py`, not a second copy."""

    def test_a_bundled_gpl_name_is_a_finding(self) -> None:
        assert exe_guard.offending_names(
            ["fpx_gui/style.qss", "pyexiv2/lib/exiv2api.pyd", "VERSION"]
        ) == ["pyexiv2/lib/exiv2api.pyd"]

    def test_a_clean_bundle_listing_is_not(self) -> None:
        assert exe_guard.offending_names(["fpx_gui/style.qss", "VERSION", "PIL/_imaging"]) == []

    def test_a_planted_artefact_string_fails_the_byte_scan(self, tmp_path: Path) -> None:
        exe = tmp_path / "fake.exe"
        exe.write_bytes(b"MZ" + b"\x00" * 64 + b"pyexiv2/lib/exiv2api.pyd" + b"\x00" * 64)
        with pytest.raises(exe_guard.LicenceLeak) as excinfo:
            exe_guard.check_executable(exe)
        assert "exiv2api" in str(excinfo.value)

    def test_a_wide_planted_string_fails_too(self, tmp_path: Path) -> None:
        """Windows resource strings are UTF-16LE, and a scan that only reads
        ASCII walks straight past them."""
        exe = tmp_path / "fake.exe"
        exe.write_bytes(b"MZ" + "libexiv2".encode("utf-16-le") + b"\x00" * 32)
        with pytest.raises(exe_guard.LicenceLeak, match="libexiv2"):
            exe_guard.check_executable(exe)

    def test_a_clean_file_passes(self, tmp_path: Path) -> None:
        exe = tmp_path / "fake.exe"
        exe.write_bytes(b"MZ" + b"fpx_gui/style.qss" + b"\x00" * 128)
        assert exe_guard.check_executable(exe) == ["raw bytes"]

    def test_the_word_in_a_docstring_is_not_a_finding(self, tmp_path: Path) -> None:
        """`fpx_converter/validator.py` explains, in a docstring that is
        compiled into the bundle, why pyexiv2 and its `exiv2.dll` are excluded.
        A bare substring scan fails every clean build on that sentence, and a
        check that cries wolf on green builds gets switched off."""
        exe = tmp_path / "fake.exe"
        exe.write_bytes(
            b"MZ`pyexiv2` is GPL-3.0 and bundles a GPL-2.0-or-later `exiv2.dll`, so"
        )
        assert exe_guard.check_executable(exe) == ["raw bytes"]

    def test_a_missing_file_is_a_failure_and_not_a_pass(self, tmp_path: Path) -> None:
        with pytest.raises(exe_guard.LicenceLeak, match="does not exist"):
            exe_guard.check_executable(tmp_path / "never-built.exe")

    def test_require_toc_refuses_to_fall_back_quietly(self, tmp_path: Path) -> None:
        """On the machine that just ran PyInstaller, an unreadable PyInstaller
        archive is a broken check rather than a clean bundle."""
        exe = tmp_path / "fake.exe"
        exe.write_bytes(b"MZ" + b"\x00" * 256)
        with pytest.raises(exe_guard.LicenceLeak):
            exe_guard.check_executable(exe, require_toc=True)
