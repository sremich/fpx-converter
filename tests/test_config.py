"""Tier-1: `.env` parsing and settings resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from fpx_converter import config
from fpx_converter.config import (
    ConfigError,
    Settings,
    parse_album_tz_overrides,
    parse_env_file,
    timezone_settings,
)


def test_parses_simple_pairs() -> None:
    assert parse_env_file("A=1\nB=two\n") == {"A": "1", "B": "two"}


def test_ignores_comments_and_blank_lines() -> None:
    text = "# a comment\n\nA=1\n   # indented comment\nB=2\n"
    assert parse_env_file(text) == {"A": "1", "B": "2"}


def test_windows_path_survives_intact() -> None:
    """No escape processing: a backslash path must come through unharmed."""
    parsed = parse_env_file(r"FPX_SOURCE_ROOT=C:\path\to\backups\CDDVD")
    assert parsed["FPX_SOURCE_ROOT"] == r"C:\path\to\backups\CDDVD"


def test_strips_matching_quotes_only() -> None:
    parsed = parse_env_file("A=\"quoted\"\nB='single'\nC=\"mismatched'\n")
    assert parsed["A"] == "quoted"
    assert parsed["B"] == "single"
    assert parsed["C"] == "\"mismatched'"


def test_value_may_contain_equals_signs() -> None:
    parsed = parse_env_file('FPX_TZ_OVERRIDES={"Trip":"America/New_York"}\nA=x=y')
    assert parsed["A"] == "x=y"
    assert parsed["FPX_TZ_OVERRIDES"] == '{"Trip":"America/New_York"}'


def test_line_without_equals_is_skipped() -> None:
    assert parse_env_file("junk\nA=1") == {"A": "1"}


class TestSettings:
    def test_missing_source_root_is_a_config_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in [k for k in __import__("os").environ if k.startswith("FPX_")]:
            monkeypatch.delenv(key, raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("FPX_LOG_LEVEL=INFO\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="FPX_SOURCE_ROOT"):
            Settings.load(env_file)

    def test_nonexistent_source_root_is_a_config_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in [k for k in __import__("os").environ if k.startswith("FPX_")]:
            monkeypatch.delenv(key, raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text(f"FPX_SOURCE_ROOT={tmp_path / 'nope'}\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="does not exist"):
            Settings.load(env_file)

    def test_environment_overrides_the_env_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        wanted = tmp_path / "wanted"
        wanted.mkdir()
        env_file = tmp_path / ".env"
        env_file.write_text(f"FPX_SOURCE_ROOT={tmp_path / 'from-file'}\n", encoding="utf-8")
        monkeypatch.setenv("FPX_SOURCE_ROOT", str(wanted))
        assert Settings.load(env_file).source_root == wanted.resolve()

    def test_default_timezone_when_unset_is_this_machines_own(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not the zone the tool was written in.

        It shipped `America/Chicago` as the silent default, so a first run in
        London stamped US Central onto every photograph -- and an
        `OffsetTime*` is written exactly as confidently when it is wrong.
        """
        from fpx_converter import timestamps

        for key in [k for k in __import__("os").environ if k.startswith("FPX_")]:
            monkeypatch.delenv(key, raising=False)
        source = tmp_path / "src"
        source.mkdir()
        env_file = tmp_path / ".env"
        env_file.write_text(f"FPX_SOURCE_ROOT={source}\n", encoding="utf-8")
        detected = timestamps.system_timezone()
        if detected is None:
            pytest.skip("this machine's zone could not be identified")
        assert Settings.load(env_file).default_tz == detected

    def test_a_configured_timezone_beats_the_machine(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in [k for k in __import__("os").environ if k.startswith("FPX_")]:
            monkeypatch.delenv(key, raising=False)
        source = tmp_path / "src"
        source.mkdir()
        env_file = tmp_path / ".env"
        env_file.write_text(
            f"FPX_SOURCE_ROOT={source}\nFPX_DEFAULT_TZ=Asia/Tokyo\n", encoding="utf-8"
        )
        assert Settings.load(env_file).default_tz == "Asia/Tokyo"


class TestTheWorkRoot:
    """Where default paths hang off, for somebody who did not clone the repo.

    `Path(__file__).parent.parent` is the repository in a checkout and
    `site-packages` in a `pip install`, and roughly nineteen CLI defaults were
    built on it -- so a first run aimed a manifest, an ingested photo store
    and two output trees at the inside of a virtual environment.
    """

    @staticmethod
    def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FPX_WORK_DIR", raising=False)
        config.set_work_dir(None)

    def test_a_checkout_still_uses_the_checkout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The developer's `output/` and `source-files/` do not move."""
        self._clear(monkeypatch)
        monkeypatch.setattr(config, "is_source_checkout", lambda path: True)
        assert config.work_root() == config.PACKAGE_ROOT

    def test_an_installed_copy_uses_the_working_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear(monkeypatch)
        monkeypatch.setattr(config, "is_source_checkout", lambda path: False)
        monkeypatch.chdir(tmp_path)
        assert config.work_root() == tmp_path
        assert config.manifest_path() == tmp_path / "source-files" / "manifest.json"
        assert config.fpx_store_dir() == tmp_path / "source-files" / "fpx"

    def test_never_the_package_directory_when_it_is_not_a_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The defect itself: nothing may default to inside site-packages."""
        self._clear(monkeypatch)
        monkeypatch.setattr(config, "is_source_checkout", lambda path: False)
        monkeypatch.chdir(tmp_path)
        for path in (
            config.work_root(),
            config.manifest_path(),
            config.fpx_store_dir(),
            config.output_root_default(),
        ):
            assert config.PACKAGE_ROOT not in path.parents
            assert path != config.PACKAGE_ROOT

    def test_the_environment_variable_and_the_flag_both_win(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear(monkeypatch)
        monkeypatch.setenv("FPX_WORK_DIR", str(tmp_path / "from-env"))
        assert config.work_root() == tmp_path / "from-env"
        config.set_work_dir(tmp_path / "from-flag")
        try:
            assert config.work_root() == tmp_path / "from-flag"
        finally:
            config.set_work_dir(None)

    def test_a_marker_beside_the_package_is_what_makes_it_a_checkout(
        self, tmp_path: Path
    ) -> None:
        assert not config.is_source_checkout(tmp_path)
        (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        assert config.is_source_checkout(tmp_path)


class TestWhereTheEnvFileIsLookedFor:
    """The working directory first, not the package folder only.

    It read `REPO_ROOT/.env` and nothing else, so an installed copy looked for
    settings in a directory the person running it has never seen.
    """

    def test_the_working_directory_comes_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FPX_DEFAULT_TZ", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("FPX_DEFAULT_TZ=Asia/Tokyo\n", encoding="utf-8")
        assert config.load_env()["FPX_DEFAULT_TZ"] == "Asia/Tokyo"

    def test_then_the_user_config_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FPX_DEFAULT_TZ", raising=False)
        empty = tmp_path / "cwd"
        empty.mkdir()
        monkeypatch.chdir(empty)
        user_dir = tmp_path / "config"
        user_dir.mkdir()
        (user_dir / ".env").write_text("FPX_DEFAULT_TZ=Europe/Paris\n", encoding="utf-8")
        monkeypatch.setattr(config, "user_config_dir", lambda: user_dir)
        assert config.load_env()["FPX_DEFAULT_TZ"] == "Europe/Paris"

    def test_the_search_order_is_first_hit_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FPX_DEFAULT_TZ", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("FPX_DEFAULT_TZ=Asia/Tokyo\n", encoding="utf-8")
        user_dir = tmp_path / "config"
        user_dir.mkdir()
        (user_dir / ".env").write_text("FPX_DEFAULT_TZ=Europe/Paris\n", encoding="utf-8")
        monkeypatch.setattr(config, "user_config_dir", lambda: user_dir)
        assert config.load_env()["FPX_DEFAULT_TZ"] == "Asia/Tokyo"

    def test_an_explicit_env_file_replaces_the_search(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FPX_DEFAULT_TZ", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("FPX_DEFAULT_TZ=Asia/Tokyo\n", encoding="utf-8")
        chosen = tmp_path / "elsewhere.env"
        chosen.write_text("FPX_DEFAULT_TZ=Europe/Paris\n", encoding="utf-8")
        config.set_env_file(chosen)
        try:
            assert config.load_env()["FPX_DEFAULT_TZ"] == "Europe/Paris"
        finally:
            config.set_env_file(None)

    def test_an_env_file_that_is_not_there_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="does not exist"):
            config.set_env_file(tmp_path / "nope.env")

    def test_the_environment_still_beats_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("FPX_DEFAULT_TZ=Asia/Tokyo\n", encoding="utf-8")
        monkeypatch.setenv("FPX_DEFAULT_TZ", "Europe/Paris")
        assert config.load_env()["FPX_DEFAULT_TZ"] == "Europe/Paris"


class TestTheDefaultOutputRoot:
    def test_fpx_output_root_is_finally_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It was parsed into `Settings` and used by nothing for six releases."""
        monkeypatch.setenv("FPX_OUTPUT_ROOT", str(tmp_path / "converted"))
        assert config.output_root_default() == tmp_path / "converted"

    def test_without_it_the_output_sits_under_the_work_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FPX_OUTPUT_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("", encoding="utf-8")
        config.set_work_dir(tmp_path)
        try:
            assert config.output_root_default() == tmp_path / "output"
        finally:
            config.set_work_dir(None)


class TestWhichTimezoneAnswers:
    """`--timezone`, then `FPX_DEFAULT_TZ`, then the machine."""

    def test_the_flag_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FPX_DEFAULT_TZ", "Asia/Tokyo")
        assert config.resolve_default_timezone("Europe/London") == "Europe/London"

    def test_then_the_configured_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FPX_DEFAULT_TZ", "Asia/Tokyo")
        assert config.resolve_default_timezone(None) == "Asia/Tokyo"

    def test_blank_is_not_an_answer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FPX_DEFAULT_TZ", "Asia/Tokyo")
        assert config.resolve_default_timezone("   ") == "Asia/Tokyo"

    def test_an_unidentifiable_machine_is_refused_rather_than_guessed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fpx_converter import timestamps

        monkeypatch.delenv("FPX_DEFAULT_TZ", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("", encoding="utf-8")
        monkeypatch.setattr(timestamps, "system_timezone", lambda: None)
        with pytest.raises(ConfigError, match="time zone could not be identified"):
            config.resolve_default_timezone(None)


class TestAlbumTimezoneOverrides:
    """Album-name -> timezone overrides live in `.env`, never in the source.

    The keys are album folder names, which are personal content. They used
    to be hardcoded in `timestamps.py`.
    """

    def test_parses_the_documented_json_form(self) -> None:
        parsed = parse_album_tz_overrides('{"Some Trip":"America/New_York"}')
        assert parsed == {"some trip": "America/New_York"}

    def test_empty_is_no_overrides_not_an_error(self) -> None:
        # A checkout with no `.env` must still work.
        assert parse_album_tz_overrides("") == {}
        assert parse_album_tz_overrides("   ") == {}

    @pytest.mark.parametrize("raw", ['{"a": 1}', "[1, 2]", "{not json"])
    def test_malformed_overrides_are_refused_loudly(self, raw: str) -> None:
        # A silently ignored override writes a wrong OffsetTime, and nothing
        # downstream can tell that from a right one.
        with pytest.raises(ConfigError):
            parse_album_tz_overrides(raw)

    def test_timezone_settings_reads_env_without_needing_a_source_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Converting from an ingested store must not require FPX_SOURCE_ROOT.
        for var in ("FPX_SOURCE_ROOT", "FPX_DEFAULT_TZ", "FPX_TZ_OVERRIDES"):
            monkeypatch.delenv(var, raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "FPX_DEFAULT_TZ=America/Denver",
                    'FPX_TZ_OVERRIDES={"beach trip":"Pacific/Honolulu"}',
                ]
            ),
            encoding="utf-8",
        )
        default_tz, overrides = timezone_settings(env_file)
        assert default_tz == "America/Denver"
        assert overrides == {"beach trip": "Pacific/Honolulu"}


class TestAlbumListSettings:
    """`FPX_NON_DESCRIPTIVE_ALBUMS` and `FPX_COARSE_ALBUMS`.

    Both decide something irreversible about an archive -- where photographs
    are filed, and whether a capture date is claimed for them -- and both live
    in `.env` because album names are personal content. A malformed value that
    was silently ignored would change the answer with nothing to show for it,
    so every refusal here is deliberate.
    """

    @staticmethod
    def _env(tmp_path, body: str):
        path = tmp_path / ".env"
        path.write_text(body, encoding="utf-8")
        return path

    def test_an_absent_setting_is_an_empty_set_not_an_error(self, tmp_path) -> None:
        env = self._env(tmp_path, "FPX_DEFAULT_TZ=UTC\n")
        assert config.extra_non_descriptive_albums(env) == frozenset()
        assert config.coarse_albums(env) == frozenset()

    def test_names_are_lowercased_and_stripped_for_matching(self, tmp_path) -> None:
        env = self._env(tmp_path, 'FPX_COARSE_ALBUMS=["  Winterfest 1994 ", "A Day Out"]\n')
        assert config.coarse_albums(env) == frozenset({"winterfest 1994", "a day out"})

    def test_malformed_json_is_refused_loudly(self, tmp_path) -> None:
        env = self._env(tmp_path, 'FPX_COARSE_ALBUMS=["unterminated\n')
        with pytest.raises(config.ConfigError, match="not valid JSON"):
            config.coarse_albums(env)

    def test_the_wrong_shape_is_refused(self, tmp_path) -> None:
        env = self._env(tmp_path, 'FPX_NON_DESCRIPTIVE_ALBUMS={"a": 1}\n')
        with pytest.raises(config.ConfigError, match="list of strings"):
            config.extra_non_descriptive_albums(env)

    def test_a_list_of_non_strings_is_refused(self, tmp_path) -> None:
        env = self._env(tmp_path, "FPX_COARSE_ALBUMS=[1994]\n")
        with pytest.raises(config.ConfigError, match="list of strings"):
            config.coarse_albums(env)

    def test_blank_entries_are_dropped_rather_than_matching_everything(
        self, tmp_path
    ) -> None:
        """An empty string is a substring of every album name."""
        env = self._env(tmp_path, 'FPX_COARSE_ALBUMS=["", "  ", "Winterfest 1994"]\n')
        assert config.coarse_albums(env) == frozenset({"winterfest 1994"})

    def test_the_two_settings_are_independent(self, tmp_path) -> None:
        env = self._env(
            tmp_path,
            'FPX_COARSE_ALBUMS=["Winterfest 1994"]\n'
            'FPX_NON_DESCRIPTIVE_ALBUMS=["Dump Folder"]\n',
        )
        assert config.coarse_albums(env) == frozenset({"winterfest 1994"})
        assert config.extra_non_descriptive_albums(env) == frozenset({"dump folder"})
