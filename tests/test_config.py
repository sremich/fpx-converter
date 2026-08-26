"""Tier-1: `.env` parsing and settings resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

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
