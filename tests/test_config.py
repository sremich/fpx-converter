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

    def test_default_timezone_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for key in [k for k in __import__("os").environ if k.startswith("FPX_")]:
            monkeypatch.delenv(key, raising=False)
        source = tmp_path / "src"
        source.mkdir()
        env_file = tmp_path / ".env"
        env_file.write_text(f"FPX_SOURCE_ROOT={source}\n", encoding="utf-8")
        assert Settings.load(env_file).default_tz == "America/Chicago"


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
