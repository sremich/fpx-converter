"""Tier-1: `.env` parsing and settings resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from fpx_converter.config import ConfigError, Settings, parse_env_file


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
