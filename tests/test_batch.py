"""Tier-1: the batch engine's three promises.

Never abort on one bad file, resume exactly, and report honestly. Each is
tested for the failure it exists to prevent rather than for its happy path --
a resume that skips a file it never wrote, and an audit that buries real
failures under expected ones, both look like success from the outside.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from fpx_converter import batch, outputs

SPECS = outputs.DEFAULT_SPECS
OTHER_SPECS = outputs.build_specs(sharing_framing="full")


def _mark(state: batch.RunState, sha: str, relpaths: list[str]) -> None:
    """Mark a file done. The engine stores the whole record, not just paths."""
    state.mark(sha, _record(sha, outputs=relpaths))


def _record(sha: str, status: str = "converted", **kw) -> batch.FileRecord:
    kw.setdefault("store_name", f"{sha[:4]}.fpx")
    kw.setdefault("album", "Sample")
    return batch.FileRecord(sha256=sha, status=status, **kw)


class TestRunState:
    def test_a_fresh_destination_has_nothing_done(self, tmp_path: Path) -> None:
        state = batch.RunState(tmp_path / batch.STATE_FILENAME, SPECS)
        assert not state.is_done("a" * 64, tmp_path)

    def test_a_marked_file_is_skipped_on_the_next_run(self, tmp_path: Path) -> None:
        (tmp_path / "archive").mkdir()
        (tmp_path / "archive" / "x.tif").write_bytes(b"x")
        state = batch.RunState(tmp_path / batch.STATE_FILENAME, SPECS)
        _mark(state, "a" * 64, ["archive/x.tif"])
        state.save()

        resumed = batch.RunState(tmp_path / batch.STATE_FILENAME, SPECS)
        assert resumed.is_done("a" * 64, tmp_path)

    def test_a_file_recorded_but_no_longer_on_disk_is_not_done(self, tmp_path: Path) -> None:
        """Somebody deleting the output tree must get their files back.

        A resume that trusts its own bookkeeping over the filesystem would
        skip everything and report success, leaving an empty output tree and a
        run that looked clean.
        """
        state = batch.RunState(tmp_path / batch.STATE_FILENAME, SPECS)
        _mark(state, "a" * 64, ["archive/gone.tif"])
        state.save()

        resumed = batch.RunState(tmp_path / batch.STATE_FILENAME, SPECS)
        assert not resumed.is_done("a" * 64, tmp_path)

    def test_changing_the_output_specs_discards_the_resume(self, tmp_path: Path) -> None:
        """Different specs mean different files, so it is not the same run.

        Resuming across the change would leave a tree half in one shape and
        half in the other, with nothing to show which files were which.
        """
        (tmp_path / "archive").mkdir()
        (tmp_path / "archive" / "x.tif").write_bytes(b"x")
        state = batch.RunState(tmp_path / batch.STATE_FILENAME, SPECS)
        _mark(state, "a" * 64, ["archive/x.tif"])
        state.save()

        assert not batch.RunState(tmp_path / batch.STATE_FILENAME, OTHER_SPECS).is_done(
            "a" * 64, tmp_path
        )

    def test_a_truncated_state_file_costs_a_reconversion_not_a_skip(
        self, tmp_path: Path
    ) -> None:
        """A run killed mid-write leaves half a JSON document.

        Losing it costs time. Trusting it could skip a file that was never
        actually written, and nothing downstream would notice the gap.
        """
        path = tmp_path / batch.STATE_FILENAME
        path.write_text('{"state_version": 2, "done": {"aaa": ', encoding="utf-8")
        assert not batch.RunState(path, SPECS).is_done("aaa", tmp_path)

    def test_a_state_file_from_an_older_engine_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / batch.STATE_FILENAME
        path.write_text(
            json.dumps({"state_version": batch.STATE_VERSION - 1, "done": {"aaa": {}}}),
            encoding="utf-8",
        )
        assert batch.RunState(path, SPECS).done == {}

    def test_the_state_file_is_replaced_atomically(self, tmp_path: Path) -> None:
        """Written to a temp name then renamed, so a kill cannot truncate it."""
        path = tmp_path / batch.STATE_FILENAME
        state = batch.RunState(path, SPECS)
        _mark(state, "a" * 64, [])
        state.save()
        _mark(state, "b" * 64, [])
        state.save()
        assert not path.with_suffix(".tmp").exists()
        assert len(json.loads(path.read_text(encoding="utf-8"))["done"]) == 2


class TestConversionLog:
    def test_every_line_is_flushed_as_it_is_written(self, tmp_path: Path) -> None:
        """A kill -9 must keep what the log already had.

        Buffering would lose exactly the lines describing whatever the run was
        doing when it died, which is the part worth having.
        """
        path = tmp_path / batch.LOG_FILENAME
        log = batch.ConversionLog(path)
        log.write("first")
        assert "first" in path.read_text(encoding="utf-8")
        log.close()

    def test_a_second_run_appends_rather_than_replacing(self, tmp_path: Path) -> None:
        path = tmp_path / batch.LOG_FILENAME
        with batch.ConversionLog(path) as log:
            log.write("run one")
        with batch.ConversionLog(path) as log:
            log.write("run two")
        text = path.read_text(encoding="utf-8")
        assert "run one" in text and "run two" in text


class TestPixelDigest:
    def test_identical_pixels_hash_the_same(self) -> None:
        a = Image.new("RGB", (8, 8), (1, 2, 3))
        b = Image.new("RGB", (8, 8), (1, 2, 3))
        assert batch.pixel_digest(a) == batch.pixel_digest(b)

    def test_different_pixels_do_not(self) -> None:
        a = Image.new("RGB", (8, 8), (1, 2, 3))
        b = Image.new("RGB", (8, 8), (1, 2, 4))
        assert batch.pixel_digest(a) != batch.pixel_digest(b)


class TestAuditReport:
    @staticmethod
    def _report(records: list[batch.FileRecord], **kw) -> dict:
        return batch.build_audit_report(
            records,
            specs=SPECS,
            output_root=Path("out"),
            started="2026-08-27T10:00:00",
            elapsed=1.5,
            total_entries=kw.pop("total_entries", len(records)),
            **kw,
        )

    def test_counts_separate_converted_resumed_and_failed(self) -> None:
        report = self._report(
            [
                _record("a" * 64),
                _record("b" * 64, status="resumed"),
                _record("c" * 64, status="failed", errors=["boom"]),
            ]
        )
        assert report["counts"]["converted"] == 1
        assert report["counts"]["resumed"] == 1
        assert report["counts"]["failed"] == 1

    def test_the_release_gate_reads_one_number(self) -> None:
        """`unexplained_failures` is what 1.0.0 requires to be zero."""
        clean = self._report([_record("a" * 64)])
        assert clean["unexplained_failures"] == 0
        broken = self._report([_record("a" * 64, status="failed", errors=["boom"])])
        assert broken["unexplained_failures"] == 1

    def test_pixel_identical_outputs_are_explained_and_not_counted_as_failures(
        self,
    ) -> None:
        """The 146-pair trap.

        Dedup keys on the whole source file, so pixel-identical outputs from
        byte-different sources are expected. An audit that called them faults
        would bury the real failures under 146 false ones.
        """
        shared = "f" * 64
        report = self._report(
            [
                _record("a" * 64, pixel_sha256=shared),
                _record("b" * 64, pixel_sha256=shared),
                _record("c" * 64, pixel_sha256="9" * 64),
            ]
        )
        dupes = report["expected_pixel_identical_groups"]
        assert dupes["count"] == 1
        assert dupes["files_involved"] == 2
        assert report["unexplained_failures"] == 0
        assert "not faults" in dupes["note"].lower()

    def test_a_file_with_a_unique_pixel_hash_forms_no_group(self) -> None:
        report = self._report([_record("a" * 64, pixel_sha256="1" * 64)])
        assert report["expected_pixel_identical_groups"]["count"] == 0

    def test_failures_carry_their_reasons(self) -> None:
        report = self._report([_record("a" * 64, status="failed", errors=["tile 3 short"])])
        assert report["failures"][0]["errors"] == ["tile 3 short"]

    def test_warnings_are_reported_without_failing_the_file(self) -> None:
        """A discarded viewing transform is not a failure -- the pixels are the
        source pixels -- but it is a difference from the original."""
        report = self._report([_record("a" * 64, warnings=["unsupported matrix"])])
        assert report["counts"]["with_warnings"] == 1
        assert report["unexplained_failures"] == 0

    def test_an_interrupted_run_says_so(self) -> None:
        report = self._report([_record("a" * 64)], interrupted=True)
        assert report["interrupted"] is True
        assert "INTERRUPTED" in batch.summarise(report)

    def test_the_summary_names_the_duplicates_as_expected(self) -> None:
        shared = "f" * 64
        report = self._report(
            [_record("a" * 64, pixel_sha256=shared), _record("b" * 64, pixel_sha256=shared)]
        )
        assert "expected, not faults" in batch.summarise(report)

    def test_the_report_round_trips_as_json(self, tmp_path: Path) -> None:
        report = self._report([_record("a" * 64, crop_applied=(1, 2, 3, 4))])
        path = tmp_path / batch.REPORT_FILENAME
        batch.write_audit_report(report, path)
        assert json.loads(path.read_text(encoding="utf-8")) == report

    def test_the_report_describes_the_tree_not_the_invocation(self) -> None:
        """A resumed file still counts, carrying the detail stored for it.

        A corpus converted across three sessions must produce one complete
        report at the end. Counting only what this invocation did would show a
        finished archive as a run that converted nothing, and the 1.0.0 gate
        reads this file.
        """
        report = self._report(
            [
                _record("a" * 64, date_source="folder"),
                _record("b" * 64, status="resumed", date_source="folder"),
                _record("c" * 64, status="failed", date_source="none", errors=["boom"]),
            ]
        )
        assert report["date_sources"] == {"folder": 2}
        assert report["counts"]["converted"] == 1
        assert report["counts"]["resumed"] == 1

    def test_a_failed_file_contributes_no_statistics(self) -> None:
        """It produced no output, so counting its date source would describe a
        file that is not in the tree."""
        report = self._report([_record("a" * 64, status="failed", date_source="folder")])
        assert report["date_sources"] == {}


def test_a_record_with_no_crop_serialises_as_null() -> None:
    assert _record("a" * 64).to_json()["crop_applied"] is None


@pytest.mark.parametrize("status", ["converted", "resumed", "failed"])
def test_every_status_survives_serialisation(status: str) -> None:
    assert _record("a" * 64, status=status).to_json()["status"] == status


class TestResumeKeepsTheDetail:
    """The stored record is the reason a resumed report is still complete."""

    def test_a_stored_record_comes_back_with_its_detail(self, tmp_path: Path) -> None:
        state = batch.RunState(tmp_path / batch.STATE_FILENAME, SPECS)
        state.mark(
            "a" * 64,
            _record(
                "a" * 64,
                date_source="folder",
                transform_status="crop",
                crop_applied=(1, 2, 3, 4),
                pixel_sha256="9" * 64,
                outputs=["archive/x.tif"],
            ),
        )
        state.save()

        recalled = batch.record_from_json(
            batch.RunState(tmp_path / batch.STATE_FILENAME, SPECS).recall("a" * 64)
        )
        assert recalled.date_source == "folder"
        assert recalled.transform_status == "crop"
        assert recalled.crop_applied == (1, 2, 3, 4)
        assert recalled.pixel_sha256 == "9" * 64

    def test_it_comes_back_as_resumed_not_converted(self, tmp_path: Path) -> None:
        """This run did not do the work.

        Reporting it as converted would misstate the run's own throughput and
        elapsed time, which is the one thing the invocation *does* know.
        """
        state = batch.RunState(tmp_path / batch.STATE_FILENAME, SPECS)
        state.mark("a" * 64, _record("a" * 64, seconds=12.0))
        state.save()
        assert batch.record_from_json(state.recall("a" * 64)).status == "resumed"

    def test_recall_on_an_unknown_file_is_none_not_an_error(self, tmp_path: Path) -> None:
        state = batch.RunState(tmp_path / batch.STATE_FILENAME, SPECS)
        assert state.recall("z" * 64) is None
