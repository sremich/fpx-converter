"""Tier-1: what the published executable is allowed to contain, and to say.

Two things are checked here and neither is cosmetic.

**The build must fail rather than publish copyleft code.** This project ships
Apache-2.0 and pyexiv2 is GPL-3.0 with `exiv2.dll` (GPL-2.0-or-later) beside
it, so a bundled copy would relicense every download. The `.spec`'s `excludes`
list is a denylist and denylists fail open -- a rename, a hook, somebody
else's dependency -- and the resulting exe looks exactly like a correct one.
`packaging/licence_guard.py` is the check that closes it, so the guard itself
is tested here: both that it catches what it must and that it passes a clean
bundle, because a guard that never fires and a guard that always fires are
equally useless.

**The notice must name the versions actually shipped.** They are written out
in `fpx_gui/notices.py` because a frozen exe has no `dist-info` to ask, and a
written-out version drifts. Each one is compared against the pin it claims to
describe, so bumping a dependency fails a test rather than shipping a notice
naming a version nobody has.

No Qt here: `notices` and `licence_guard` are deliberately toolkit-free, so
this file runs on an install of `requirements-dev.txt` alone.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGING = REPO_ROOT / "packaging"
SPEC = PACKAGING / "fpx-converter.spec"

sys.path.insert(0, str(PACKAGING))

import licence_guard  # noqa: E402

from fpx_gui import notices  # noqa: E402


class TestTheBuildRefusesCopyleft:
    """The guard fires on what it is for, and only on that."""

    @pytest.mark.parametrize(
        "entry",
        [
            ("exiv2.dll", "C:/venv/Lib/site-packages/pyexiv2/lib/exiv2.dll", "BINARY"),
            ("exiv2api.pyd", "C:/venv/Lib/site-packages/pyexiv2/lib/exiv2api.pyd", "EXTENSION"),
            # Renamed on the way in. The source path still gives it away, which
            # is why both halves of the entry are inspected.
            ("lib/_x.pyd", "C:/venv/Lib/site-packages/pyexiv2/lib/exiv2api.pyd", "EXTENSION"),
            ("pyexiv2.core", "C:/venv/Lib/site-packages/pyexiv2/core.py", "PYMODULE"),
        ],
    )
    def test_a_forbidden_entry_fails_the_build(self, entry) -> None:  # noqa: ANN001
        with pytest.raises(licence_guard.LicenceLeak):
            licence_guard.check_bundle([entry])

    def test_a_clean_bundle_passes(self) -> None:
        """Otherwise the test above proves only that the guard always raises."""
        licence_guard.check_bundle(
            [
                ("fpx_gui/style.qss", str(REPO_ROOT / "fpx_gui" / "style.qss"), "DATA"),
                ("Qt6Core.dll", "C:/venv/Lib/site-packages/PySide6/Qt6Core.dll", "BINARY"),
                ("fpx_converter.writer", "fpx_converter/writer.py", "PYMODULE"),
            ]
        )

    def test_the_failure_names_the_file_and_the_reason(self) -> None:
        """A build that stops has to say what stopped it, months from now."""
        with pytest.raises(licence_guard.LicenceLeak) as caught:
            licence_guard.check_bundle([("exiv2.dll", "x/pyexiv2/lib/exiv2.dll", "BINARY")])
        message = str(caught.value)
        assert "exiv2.dll" in message
        assert "GPL" in message

    def test_an_environment_with_gpl_only_qt_addons_fails_the_build(self) -> None:
        """Not installed is the only version of this rule that cannot fail open."""
        with pytest.raises(licence_guard.LicenceLeak):
            licence_guard.check_build_environment({"pyside6-addons", "pyside6-essentials"})

    def test_an_essentials_only_environment_passes(self) -> None:
        licence_guard.check_build_environment({"pyside6-essentials", "shiboken6", "pillow"})

    def test_this_environment_is_one_the_build_would_accept(self) -> None:
        """The real check, on the venv actually running these tests.

        `requirements-gui.txt` pins PySide6-Essentials rather than the PySide6
        metapackage precisely so the GPLv3-only Addons modules are absent. An
        environment that quietly reacquired them would build an exe nobody
        could publish.
        """
        pytest.importorskip("PySide6", reason="only meaningful where the GUI is installed")
        licence_guard.check_build_environment()


class TestTheSpecDoesNotBundleIt:
    """Read as text: the spec cannot be imported, which is why the guard is not in it."""

    def test_the_spec_no_longer_collects_pyexiv2(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        assert 'collect_all("pyexiv2")' not in text
        assert "pyexiv2_binaries" not in text

    def test_the_spec_excludes_pyexiv2_and_calls_the_guard(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        assert '"pyexiv2",' in text, "the analyser is free to follow the import"
        assert "check_bundle" in text, "nothing verifies the exclusion held"
        assert "check_build_environment" in text

    def test_the_spec_bundles_the_licence_texts(self) -> None:
        """Without these the dialog cannot open, and the notice does not ship."""
        text = SPEC.read_text(encoding="utf-8")
        assert "licences" in text


class TestTheLicenceTextsTravel:
    def test_every_named_text_is_readable_as_package_data(self) -> None:
        for name in notices.LICENCE_FILES:
            body = notices.read_licence(name)
            assert len(body) > 5000, f"{name} looks truncated"

    def test_the_texts_are_the_repository_ones_byte_for_byte(self) -> None:
        """One source of truth. `LICENSES/` is it; the package copy is a copy.

        They are separate files because the package copy has to be inside the
        executable and `LICENSES/` is a directory in a checkout, but a copy
        that is allowed to drift is worse than no copy: the exe would carry a
        licence text the repository does not stand behind.
        """
        for name in notices.LICENCE_FILES:
            published = REPO_ROOT / "LICENSES" / name
            if not published.is_file():  # pragma: no cover - repo layout changed
                pytest.skip(f"the repository has no LICENSES/{name}")
            assert notices.read_licence(name) == published.read_text(encoding="utf-8")

    def test_an_unknown_name_is_refused_rather_than_read(self) -> None:
        with pytest.raises(KeyError):
            notices.read_licence("../../../etc/passwd")

    def test_the_lgpl_text_is_the_lgpl(self) -> None:
        assert "GNU LESSER GENERAL PUBLIC LICENSE" in notices.read_licence(notices.LGPL_3_0)

    def test_the_gpl_text_is_the_gpl(self) -> None:
        body = notices.read_licence(notices.GPL_3_0)
        assert "GNU GENERAL PUBLIC LICENSE" in body
        assert "LESSER" not in body.split("TERMS AND CONDITIONS")[0]


class TestTheNoticeSaysWhatItMustSay:
    def test_it_names_this_project_s_own_licence(self) -> None:
        assert "Apache-2.0" in notices.notice_text()

    def test_it_names_the_lgpl_components_as_unmodified(self) -> None:
        text = notices.notice_text()
        assert "PySide6-Essentials" in text
        assert "shiboken6" in text
        assert "The Qt Company" in text
        assert "UNMODIFIED" in text

    def test_it_says_exiftool_is_not_bundled(self) -> None:
        """The one component that is not inside the exe, said in as many words."""
        text = notices.notice_text()
        assert "ExifTool" in text
        assert "NOT BUNDLED" in text

    def test_it_points_at_github_issues_and_publishes_no_email(self) -> None:
        text = notices.notice_text()
        assert notices.ISSUES_URL in text
        assert "@" not in text.replace("issues", ""), "an email address reached the notice"

    def test_every_bundled_component_offers_somewhere_to_get_the_source(self) -> None:
        for component in notices.COMPONENTS:
            assert component.source.startswith("http"), component.name

    def test_it_does_not_mention_pyexiv2(self) -> None:
        """It is not in the executable, so naming it in the notice would be a
        claim about the binary that is not true."""
        assert "pyexiv2" not in notices.notice_text().lower()


class TestTheNoticeNamesTheVersionsActuallyShipped:
    """Written-out versions, checked against the pins they describe."""

    @staticmethod
    def _pins(path: Path) -> dict[str, str]:
        pins: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^([A-Za-z0-9_.-]+)==([^\s#]+)", line.strip())
            if match:
                pins[match.group(1).lower().replace("_", "-")] = match.group(2)
        return pins

    def test_every_pinned_component_matches_its_requirements_pin(self) -> None:
        checked = 0
        for component in notices.COMPONENTS:
            if component.pypi is None or component.pinned_in is None:
                continue
            pins = self._pins(REPO_ROOT / component.pinned_in)
            key = component.pypi.lower().replace("_", "-")
            assert key in pins, (
                f"{component.name} is in the licence notice but is not pinned in "
                f"{component.pinned_in}; the notice would name a version nobody installs"
            )
            assert pins[key] == component.version, (
                f"{component.name} is pinned at {pins[key]} and the licence "
                f"notice says {component.version}"
            )
            checked += 1
        assert checked >= 5, "almost nothing was checked; this test proves little"

    def test_the_notice_carries_the_version_of_this_program(self) -> None:
        version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        assert version in notices.notice_text()
