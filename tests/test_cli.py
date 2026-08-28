"""Tier-1: CLI exit codes and the guards that sit on the command boundary.

Exit codes are the contract a batch script depends on, and the containment
guard is only useful if the CLI actually applies it to caller-supplied
paths — which is exactly where a mistyped flag arrives.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpx_converter import manifest as manifest_mod
from fpx_converter.cli import main

FIXTURES = Path(__file__).parent / "fixtures"

#: Counted, not pinned. The fixture set grew from 4 to 40 when the
#: person-free archive photos were adopted, and every one of these
#: assertions was a bare `== 4` that had to be found and edited. Deriving it
#: keeps the assertion about "the CLI processed everything it was given".
FIXTURE_COUNT = len([p for p in FIXTURES.iterdir() if p.suffix.lower() == ".fpx"])


def scan_argv(source: Path, manifest: Path, *extra: str) -> list[str]:
    return [
        "scan",
        "--source",
        str(source),
        "--manifest",
        str(manifest),
        "--progress-every",
        "0",
        *extra,
    ]


class TestScan:
    def test_scans_and_writes_a_verified_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        assert main(scan_argv(FIXTURES, manifest_path)) == 0
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["counts"]["files_seen"] == FIXTURE_COUNT
        assert data["verification"]["ok"] is True
        assert data["verification"]["files_rehashed"] > 0

    def test_records_which_files_were_rehashed(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path, "--resample", "2"))
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(data["verification"]["sampled"]) == 2

    def test_empty_tree_exits_1(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert main(scan_argv(empty, tmp_path / "m.json")) == 1

    def test_negative_resample_exits_1(self, tmp_path: Path) -> None:
        assert main(scan_argv(FIXTURES, tmp_path / "m.json", "--resample", "-1")) == 1

    def test_refuses_a_manifest_path_inside_the_source(self, tmp_path: Path, capsys) -> None:
        """A mistyped --manifest must not write into the archive."""
        source = tmp_path / "archive"
        source.mkdir()
        assert main(scan_argv(source, source / "m.json")) == 1
        assert "read-only source archive" in capsys.readouterr().err

    def test_warns_when_content_verification_is_disabled(self, tmp_path: Path, capsys) -> None:
        assert main(scan_argv(FIXTURES, tmp_path / "m.json", "--resample", "0")) == 0
        assert "no file content was re-verified" in capsys.readouterr().out


class TestIngest:
    def test_missing_manifest_exits_1(self, tmp_path: Path) -> None:
        assert main(["ingest", "--manifest", str(tmp_path / "nope.json")]) == 1

    def test_copies_from_a_verified_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        dest = tmp_path / "store"
        assert main(["ingest", "--manifest", str(manifest_path), "--dest", str(dest)]) == 0
        assert len(list(dest.iterdir())) == FIXTURE_COUNT

    def test_refuses_an_unverified_manifest(self, tmp_path: Path, capsys) -> None:
        """A manifest whose scan could not prove the source was untouched is
        not a safe thing to copy from."""
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["verification"]["ok"] = False
        manifest_mod.write(manifest_path, data)

        dest = tmp_path / "store"
        assert main(["ingest", "--manifest", str(manifest_path), "--dest", str(dest)]) == 1
        assert "did not prove the source tree was unchanged" in capsys.readouterr().err
        assert not dest.exists()

    def test_a_manifest_with_no_verification_block_counts_as_unverified(
        self, tmp_path: Path
    ) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        del data["verification"]
        manifest_mod.write(manifest_path, data)
        argv = ["ingest", "--manifest", str(manifest_path), "--dest", str(tmp_path / "s")]
        assert main(argv) == 1

    def test_allow_unverified_overrides_the_refusal(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["verification"]["ok"] = False
        manifest_mod.write(manifest_path, data)
        dest = tmp_path / "store"
        argv = ["ingest", "--manifest", str(manifest_path), "--dest", str(dest)]
        assert main([*argv, "--allow-unverified"]) == 0

    def test_refuses_a_destination_inside_the_source(self, tmp_path: Path, capsys) -> None:
        """The finding that mattered most: --dest pointed at the archive
        would mkdir there and overwrite source files on a name match."""
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        argv = ["ingest", "--manifest", str(manifest_path), "--dest", str(FIXTURES / "sub")]
        assert main(argv) == 1
        assert "read-only source archive" in capsys.readouterr().err
        assert not (FIXTURES / "sub").exists()

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        dest = tmp_path / "store"
        argv = ["ingest", "--manifest", str(manifest_path), "--dest", str(dest), "--dry-run"]
        assert main(argv) == 0
        assert not dest.exists()


class TestVerify:
    def test_missing_manifest_exits_1(self, tmp_path: Path) -> None:
        assert main(["verify", "--manifest", str(tmp_path / "nope.json")]) == 1

    def test_clean_store_exits_0(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        dest = tmp_path / "store"
        main(["ingest", "--manifest", str(manifest_path), "--dest", str(dest)])
        assert main(["verify", "--manifest", str(manifest_path), "--dest", str(dest)]) == 0

    def test_corrupted_store_exits_2(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        dest = tmp_path / "store"
        main(["ingest", "--manifest", str(manifest_path), "--dest", str(dest)])
        next(iter(dest.iterdir())).write_bytes(b"corrupted")
        assert main(["verify", "--manifest", str(manifest_path), "--dest", str(dest)]) == 2


class TestMetadataCLI:
    def test_missing_manifest_exits_1(self, tmp_path: Path) -> None:
        assert main(["metadata", "--manifest", str(tmp_path / "nope.json")]) == 1

    def test_dumps_sidecars_from_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        dest = tmp_path / "sidecars"
        argv = [
            "metadata",
            "--manifest",
            str(manifest_path),
            "--store",
            str(FIXTURES),
            "--dest",
            str(dest),
        ]
        assert main(argv) == 0
        assert len(list(dest.glob("*.json"))) == FIXTURE_COUNT

    def test_dry_run_writes_no_sidecars(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        dest = tmp_path / "sidecars"
        argv = [
            "metadata",
            "--manifest",
            str(manifest_path),
            "--store",
            str(FIXTURES),
            "--dest",
            str(dest),
            "--dry-run",
        ]
        assert main(argv) == 0
        assert not dest.exists()

    def test_refuses_sidecar_dest_inside_source(self, tmp_path: Path, capsys) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        argv = [
            "metadata",
            "--manifest",
            str(manifest_path),
            "--store",
            str(FIXTURES),
            "--dest",
            str(FIXTURES / "sidecars"),
        ]
        assert main(argv) == 1
        assert "read-only source archive" in capsys.readouterr().err


class TestCheckDatesCLI:
    def test_missing_manifest_exits_1(self, tmp_path: Path) -> None:
        assert main(["check-dates", "--manifest", str(tmp_path / "nope.json")]) == 1

    def test_runs_check_dates_on_manifest(self, tmp_path: Path, capsys) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        argv = [
            "check-dates",
            "--manifest",
            str(manifest_path),
            "--store",
            str(FIXTURES),
        ]
        assert main(argv) == 0
        out = capsys.readouterr().out
        assert "Album Ground-Truth Date Report" in out
        assert "Total albums:" in out


class TestThumbnailCLI:
    def test_missing_manifest_exits_1(self, tmp_path: Path) -> None:
        assert main(["thumbnail", "--manifest", str(tmp_path / "nope.json")]) == 1

    def test_extracts_thumbnails_to_destination(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        dest = tmp_path / "thumbs"
        argv = [
            "thumbnail",
            "--manifest",
            str(manifest_path),
            "--store",
            str(FIXTURES),
            "--dest",
            str(dest),
        ]
        assert main(argv) == 0
        pngs = list(dest.glob("*.png"))
        assert len(pngs) == FIXTURE_COUNT

    def test_dry_run_writes_no_thumbnails(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        dest = tmp_path / "thumbs"
        argv = [
            "thumbnail",
            "--manifest",
            str(manifest_path),
            "--store",
            str(FIXTURES),
            "--dest",
            str(dest),
            "--dry-run",
        ]
        assert main(argv) == 0
        assert not dest.exists()

    def test_refuses_thumbnail_dest_inside_source(self, tmp_path: Path, capsys) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        argv = [
            "thumbnail",
            "--manifest",
            str(manifest_path),
            "--store",
            str(FIXTURES),
            "--dest",
            str(FIXTURES / "thumbs"),
        ]
        assert main(argv) == 1
        assert "read-only source archive" in capsys.readouterr().err


class TestConvertCLI:
    def test_missing_manifest_exits_1(self, tmp_path: Path) -> None:
        assert main(["convert", "--manifest", str(tmp_path / "nope.json")]) == 1

    def test_converts_fixtures_to_dual_output(self, tmp_path: Path) -> None:
        """Everything a run can write, asked for at once.

        The `.fpx` copy and the `.fpx.json` sidecar are opt-in, so this asks
        for them by flag. That makes the test cover more than it did when they
        came for free: it now also proves the two flags reach the writer.
        """
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        dest = tmp_path / "output"
        argv = [
            "convert",
            "--manifest",
            str(manifest_path),
            "--store",
            str(FIXTURES),
            "--dest",
            str(dest),
            "--source-copy",
            "--sidecar",
        ]
        assert main(argv) == 0
        archive_tifs = list((dest / "archive").rglob("*.tif"))
        sharing_jpgs = list((dest / "sharing").rglob("*.jpg"))
        archive_fpxs = list((dest / "archive").rglob("*.fpx"))
        archive_sidecars = list((dest / "archive").rglob("*.fpx.json"))

        assert len(archive_tifs) == FIXTURE_COUNT
        assert len(sharing_jpgs) == FIXTURE_COUNT
        assert len(archive_fpxs) == FIXTURE_COUNT
        assert len(archive_sidecars) == FIXTURE_COUNT

    def test_dry_run_writes_no_conversion_files(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        dest = tmp_path / "output"
        argv = [
            "convert",
            "--manifest",
            str(manifest_path),
            "--store",
            str(FIXTURES),
            "--dest",
            str(dest),
            "--dry-run",
        ]
        assert main(argv) == 0
        assert not (dest / "archive").exists()
        assert not (dest / "sharing").exists()

    def test_refuses_convert_dest_inside_source(self, tmp_path: Path, capsys) -> None:
        manifest_path = tmp_path / "m.json"
        main(scan_argv(FIXTURES, manifest_path))
        argv = [
            "convert",
            "--manifest",
            str(manifest_path),
            "--store",
            str(FIXTURES),
            "--dest",
            str(FIXTURES / "output"),
        ]
        assert main(argv) == 1
        assert "read-only source archive" in capsys.readouterr().err


def test_version_reports_the_version_file() -> None:
    from fpx_converter import __version__

    expected = (Path(__file__).parent.parent / "VERSION").read_text(encoding="utf-8").strip()
    assert __version__ == expected


def test_no_subcommand_is_an_error() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0



class TestScanTakesTheSourceAsAnArgument:
    """`fpx-converter scan ./photos` -- the first thing anybody types.

    It used to be `--source`, with `FPX_SOURCE_ROOT` in a `.env` file as the
    only other way to say it, so a fresh install with no configuration
    refused to do anything at all.
    """

    def test_a_positional_source_is_scanned(self, tmp_path: Path) -> None:
        manifest = tmp_path / "m.json"
        argv = ["scan", str(FIXTURES), "--manifest", str(manifest), "--progress-every", "0"]
        assert main(argv) == 0
        assert manifest.is_file()

    def test_the_option_spelling_still_works(self, tmp_path: Path) -> None:
        """Existing commands and documentation use `--source`."""
        manifest = tmp_path / "m.json"
        assert main(scan_argv(FIXTURES, manifest)) == 0
        assert manifest.is_file()

    def test_a_folder_that_is_not_there_is_a_sentence_not_a_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        argv = ["scan", str(tmp_path / "nope"), "--manifest", str(tmp_path / "m.json")]
        assert main(argv) == 1
        assert "No such folder" in capsys.readouterr().err

    def test_with_nothing_at_all_it_says_what_to_type(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("FPX_SOURCE_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("", encoding="utf-8")
        assert main(["scan", "--manifest", str(tmp_path / "m.json")]) == 1
        err = capsys.readouterr().err
        assert "fpx-converter scan" in err
        assert "convenience rather than a requirement" in err


class TestTheWorkDirectoryReachesTheDefaults:
    def test_work_dir_moves_the_default_manifest(self, tmp_path: Path) -> None:
        """Without it the default sits beside the package -- `site-packages`
        for anybody who installed this rather than cloning it."""
        work = tmp_path / "work"
        work.mkdir()
        assert main(["--work-dir", str(work), "scan", str(FIXTURES), "--progress-every", "0"]) == 0
        assert (work / "source-files" / "manifest.json").is_file()

    def test_the_setting_does_not_survive_the_call(self, tmp_path: Path) -> None:
        """It is process-wide state, and `main` is called more than once."""
        from fpx_converter import config

        work = tmp_path / "work"
        work.mkdir()
        main(["--work-dir", str(work), "scan", str(FIXTURES), "--progress-every", "0"])
        assert config._work_dir_override is None

    def test_env_file_points_the_settings_somewhere_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("FPX_SOURCE_ROOT", raising=False)
        chosen = tmp_path / "settings.env"
        chosen.write_text(f"FPX_SOURCE_ROOT={FIXTURES}\n", encoding="utf-8")
        argv = [
            "--env-file", str(chosen),
            "scan",
            "--manifest", str(tmp_path / "m.json"),
            "--progress-every", "0",
        ]
        assert main(argv) == 0
        assert str(FIXTURES) in capsys.readouterr().out

    def test_an_env_file_that_is_not_there_is_a_sentence(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        argv = ["--env-file", str(tmp_path / "nope.env"), "scan", str(FIXTURES)]
        assert main(argv) == 1
        assert "does not exist" in capsys.readouterr().err
