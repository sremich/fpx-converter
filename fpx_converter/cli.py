"""Command line entry point: `python -m fpx_converter <command>`.

Commands (the version lives in `VERSION`; `--version` prints it):
- `scan`: walk the source archive read-only and write `manifest.json`.
- `ingest`: copy one file per distinct hash into the local store.
- `verify`: re-hash the local store against the manifest.
- `metadata`: extract full metadata and emit raw `.fpx.json` sidecars.
- `check-dates`: execute the automated album folder ground-truth date gate.
- `thumbnail`: extract embedded DIB thumbnails as PNG images.
- `convert`: execute dual output conversion (Deflate TIFF + q95 4:4:4 JPEG).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__, batch, config, decoder, gallery, layout, naming, outputs, scan
from . import album_dates as album_dates_mod
from . import ingest as ingest_mod
from . import manifest as manifest_mod
from . import metadata as metadata_mod
from . import thumbnail as thumbnail_mod
from . import timestamps as timestamps_mod
from . import writer as writer_mod


def _human_mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


def _echo_line(line: str) -> None:
    """One conversion-log line onto stdout, flushed.

    Flushed on purpose: stdout to a pipe is block-buffered, so a reader
    watching a long run would otherwise get the whole trail at the end,
    which is the opposite of progress.
    """
    print(line, flush=True)


def cmd_scan(args: argparse.Namespace) -> int:
    source_root = (
        Path(args.source).resolve() if args.source else config.Settings.load().source_root
    )
    requested = Path(args.manifest) if args.manifest else config.MANIFEST_PATH
    manifest_path = config.ensure_outside_source(requested, source_root, "manifest path")

    if args.resample < 0:
        print("--resample must not be negative.", file=sys.stderr)
        return 1

    print(f"Scanning (read-only): {source_root}")
    scanned, snapshot = scan.scan_tree(source_root, progress_every=args.progress_every)
    if not scanned:
        print("No .fpx files found.", file=sys.stderr)
        return 1

    print()
    print("Verifying the source tree is unchanged...")
    hashes = {str(item.path): item.sha256 for item in scanned}
    report = scan.verify_unchanged(snapshot, source_root, hashes, sample_size=args.resample)

    manifest = manifest_mod.build(
        scanned,
        source_root=source_root,
        tool_version=__version__,
        verification=report.as_dict(),
    )
    manifest_mod.write(manifest_path, manifest)

    counts = manifest["counts"]
    seen_mb = _human_mb(counts["bytes_seen"])
    distinct_mb = _human_mb(counts["bytes_distinct"])
    print()
    print(f"  files seen        {counts['files_seen']:>6}  ({seen_mb})")
    print(f"  distinct sha256   {counts['distinct_sha256']:>6}  ({distinct_mb})")
    print(f"  human-named       {counts['human_authored_names']:>6}")
    print(f"  not OLE2          {counts['not_ole']:>6}")
    print(f"  manifest          {manifest_path}")

    print()
    if report.ok:
        print(
            f"  source tree unchanged: {report.checked} files stat-checked, "
            f"{report.resampled} re-hashed, no additions"
        )
        if report.resampled == 0:
            print("  WARNING: --resample 0 means no file content was re-verified.")
    else:
        for label, items in (
            ("MODIFIED", report.modified),
            ("VANISHED", report.vanished),
            ("ADDED", report.added),
            ("HASH MISMATCH", report.rehash_mismatches),
        ):
            for path in items:
                print(f"  {label}: {path}", file=sys.stderr)
        print("SOURCE TREE CHANGED — investigate before ingesting.", file=sys.stderr)
        return 2

    if counts["not_ole"]:
        print(
            f"  WARNING: {counts['not_ole']} file(s) are not parseable OLE2 documents.",
            file=sys.stderr,
        )
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest) if args.manifest else config.MANIFEST_PATH
    if not manifest_path.is_file():
        print(f"No manifest at {manifest_path} — run `scan` first.", file=sys.stderr)
        return 1

    manifest = manifest_mod.load(manifest_path)
    source_root = Path(manifest["source_root"])

    if not ingest_mod.manifest_is_verified(manifest) and not args.allow_unverified:
        print(
            "This manifest's scan did not prove the source tree was unchanged.\n"
            "Re-run `scan`, or pass --allow-unverified if you know why.",
            file=sys.stderr,
        )
        return 1

    dest = config.ensure_outside_source(
        Path(args.dest) if args.dest else config.FPX_STORE_DIR,
        source_root,
        "ingest destination",
    )

    verb = "Would copy" if args.dry_run else "Copying"
    print(f"{verb} {len(manifest['entries'])} distinct files -> {dest}")
    report = ingest_mod.ingest(
        manifest, source_root=source_root, dest_dir=dest, dry_run=args.dry_run
    )
    print(f"  copied  {report.copied}  ({_human_mb(report.bytes_copied)})")
    print(f"  skipped {report.skipped}  (already present and correct)")
    for name, why in report.failures:
        print(f"  FAILED {name}: {why}", file=sys.stderr)
    return 0 if report.ok else 2


def cmd_verify(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest) if args.manifest else config.MANIFEST_PATH
    if not manifest_path.is_file():
        print(f"No manifest at {manifest_path} — run `scan` first.", file=sys.stderr)
        return 1
    manifest = manifest_mod.load(manifest_path)
    dest = Path(args.dest) if args.dest else config.FPX_STORE_DIR
    problems = ingest_mod.verify_store(manifest, dest_dir=dest)
    if not problems:
        print(f"All {len(manifest['entries'])} ingested copies match the manifest.")
        return 0
    for name, why in problems:
        print(f"  {name}: {why}", file=sys.stderr)
    print(f"{len(problems)} problem(s).", file=sys.stderr)
    return 2


def cmd_metadata(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest) if args.manifest else config.MANIFEST_PATH
    if not manifest_path.is_file():
        print(f"No manifest at {manifest_path} — run `scan` first.", file=sys.stderr)
        return 1

    manifest = manifest_mod.load(manifest_path)
    source_root = Path(manifest["source_root"])
    store_dir = Path(args.store) if args.store else config.FPX_STORE_DIR

    output_base = Path(args.dest) if args.dest else (config.REPO_ROOT / "output" / "sidecars")
    dest = config.ensure_outside_source(output_base, source_root, "sidecar destination")

    verb = "Would dump" if args.dry_run else "Dumping"
    print(f"{verb} {len(manifest['entries'])} sidecars -> {dest}")
    report = metadata_mod.dump_sidecars(
        manifest,
        fpx_dir=store_dir,
        output_dir=dest,
        source_root=source_root,
        dry_run=args.dry_run,
    )
    print(f"  written {report.written} sidecars")
    if report.failures:
        for name, why in report.failures:
            print(f"  FAILED {name}: {why}", file=sys.stderr)
        return 2
    return 0


def cmd_check_dates(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest) if args.manifest else config.MANIFEST_PATH
    if not manifest_path.is_file():
        print(f"No manifest at {manifest_path} — run `scan` first.", file=sys.stderr)
        return 1

    manifest = manifest_mod.load(manifest_path)
    source_root = Path(manifest["source_root"])
    store_dir = Path(args.store) if args.store else config.FPX_STORE_DIR

    timestamps_by_hash: dict[str, datetime.datetime] = {}
    for entry in manifest["entries"]:
        sha = entry["sha256"]
        fpx_path = store_dir / entry["store_name"]
        if not fpx_path.is_file():
            alt = source_root / entry["preferred_relpath"]
            if alt.is_file():
                fpx_path = alt
        if fpx_path.is_file():
            meta = metadata_mod.extract_fpx_metadata(fpx_path, manifest_entry=entry)
            ts_iso = meta.derived["timestamps"].get("import_datetime")
            if ts_iso:
                timestamps_by_hash[sha] = datetime.datetime.fromisoformat(ts_iso)

    report = timestamps_mod.check_manifest_ground_truth(manifest, timestamps_by_hash)

    print("Album Ground-Truth Date Report:")
    header_fmt = (
        f"{'Album':<32} {'Files':>5} {'Parsed Date':<15} "
        f"{'Import Dates':<22} {'Verdict':<8} {'Notes'}"
    )
    print(header_fmt)
    print("-" * 100)
    for res in report.results:
        imp_summary = (
            f"{res.earliest_import}..{res.latest_import}"
            if res.earliest_import != res.latest_import
            else res.earliest_import
        )
        row = (
            f"{res.album:<32} {res.file_count:>5} {res.expected_display:<15} "
            f"{imp_summary:<22} {res.verdict:<8} {res.notes}"
        )
        print(row)
    print("-" * 100)
    summary_line = (
        f"Total albums: {report.total_albums} | Dated: {report.dated_albums} "
        f"(PASS: {report.passed_albums}, NEAR: {report.near_albums}, "
        f"FAIL: {report.failed_albums}) | Undated: {report.undated_albums}"
    )
    print(summary_line)

    # The milestone calls this an automated gate, so it has to be able to
    # fail. It is opt-in because failing is the *expected* result on this
    # corpus -- the import stamp misses 7 of 9 dated albums, one by a whole
    # year, which is exactly why `DateTimeOriginal` is not taken from it.
    # `--strict` is for asking "has this got worse?", not "is it perfect?".
    if getattr(args, "strict", False) and not report.ok:
        print(
            f"\nFAIL: {report.failed_albums} album(s) disagree with the import "
            f"timestamps. Re-run without --strict to inspect the table above.",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_thumbnail(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest) if args.manifest else config.MANIFEST_PATH
    if not manifest_path.is_file():
        print(f"No manifest at {manifest_path} — run `scan` first.", file=sys.stderr)
        return 1

    manifest = manifest_mod.load(manifest_path)
    source_root = Path(manifest["source_root"])
    store_dir = Path(args.store) if args.store else config.FPX_STORE_DIR

    output_base = (
        Path(args.dest) if args.dest else (config.REPO_ROOT / "output" / "thumbnails")
    )
    dest = config.ensure_outside_source(output_base, source_root, "thumbnail destination")

    if not args.dry_run:
        dest.mkdir(parents=True, exist_ok=True)

    entries = manifest.get("entries", [])
    verb = "Would extract" if args.dry_run else "Extracting"
    print(f"{verb} {len(entries)} thumbnails -> {dest}")

    extracted = 0
    failures: list[tuple[str, str]] = []
    for entry in entries:
        store_name = entry["store_name"]
        fpx_path = store_dir / store_name
        if not fpx_path.is_file():
            alt = source_root / entry["preferred_relpath"]
            if alt.is_file():
                fpx_path = alt
            else:
                failures.append((store_name, "file not found"))
                continue

        try:
            thumb = thumbnail_mod.extract_thumbnail(fpx_path)
            if not args.dry_run:
                out_path = dest / f"{Path(store_name).stem}_thumb.png"
                thumb.save(out_path, format="PNG")
            extracted += 1
        except Exception as exc:  # noqa: BLE001
            failures.append((store_name, str(exc)))

    print(f"  extracted {extracted} thumbnails")
    if failures:
        for name, why in failures:
            print(f"  FAILED {name}: {why}", file=sys.stderr)
        return 2
    return 0


def _remove_stop_file(path: Path, log: batch.ConversionLog | None = None) -> None:
    """Delete the stop marker, and never let that end the run.

    `unlink` raises `PermissionError` on Windows for a file an indexer or a
    virus scanner has open for a moment, and for a path that turns out to be a
    directory. Both were able to escape the loop from the one code path whose
    entire purpose is making sure the audit report still gets written.

    Suppressed but not silent: a failure that nothing mentions is how the
    first version of this wedged a destination with no way to find out why.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        if log is not None:
            log.write(
                f"NOTE could not remove the stop marker at {path} ({exc}). "
                "It will be ignored by later runs, which only honour a marker "
                "newer than the run itself, but it is worth deleting by hand."
            )


def _stop_requested(path: Path, since: float) -> bool:
    """Has somebody asked *this* run to stop?

    Not "does a marker exist" -- "was one left since this run began". Asking
    the first question meant a marker written moments after the child started,
    but before it finished loading the manifest, was deleted by the run it was
    meant to stop; and a marker that could not be deleted stopped every future
    run for ever. Both disappear once the marker has to be newer than the run.
    """
    try:
        return path.stat().st_mtime >= since
    except OSError:
        return False


def cmd_convert(args: argparse.Namespace) -> int:
    """Convert the manifest, resuming what is done and never stopping on one file."""
    # Stamped first, before the manifest load and the stem assignment over
    # every entry, because a Cancel arriving during that work is still a
    # Cancel of this run. `_stop_requested` compares against it.
    run_started = time.time()
    manifest_path = Path(args.manifest) if args.manifest else config.MANIFEST_PATH
    if not manifest_path.is_file():
        print(f"No manifest at {manifest_path} - run `scan` first.", file=sys.stderr)
        return 1

    manifest = manifest_mod.load(manifest_path)
    source_root = Path(manifest["source_root"])
    store_dir = Path(args.store) if args.store else config.FPX_STORE_DIR

    output_base = Path(args.dest) if args.dest else (config.REPO_ROOT / "output")
    dest = config.ensure_outside_source(output_base, source_root, "conversion destination")

    try:
        supplied = album_dates_mod.load(_album_dates_path(args, manifest_path))
    except album_dates_mod.AlbumDateError as exc:
        # Refused, not ignored. Somebody wrote this file down deliberately;
        # dropping it silently would lose exactly the evidence it carries.
        print(f"album dates: {exc}", file=sys.stderr)
        return 1
    if supplied:
        print(f"  album dates supplied for {len(supplied.dates)} albums")

    try:
        specs = outputs.build_specs(
            archive=not args.no_archive,
            sharing=not args.no_sharing,
            archive_format=args.archive_format,
            archive_framing=args.archive_framing,
            sharing_format=args.sharing_format,
            sharing_framing=args.sharing_framing,
        )
    except outputs.OutputSpecError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    all_entries = manifest.get("entries", [])
    entries = all_entries[: args.limit] if args.limit and args.limit > 0 else all_entries

    # Names are resolved from the WHOLE manifest, not from the slice being
    # converted. `--limit` must not change where a file lands: if it did, a
    # limited run and a full run would disagree about which of two same-named
    # photos keeps the bare stem, and the same photo would exist at two paths.
    stems = naming.assign_output_stems(
        [
            (e["sha256"], layout.stem_scope(e), e.get("preferred_name", e["store_name"]))
            for e in all_entries
        ]
    )

    verb = "Would convert" if args.dry_run else "Converting"
    print(f"{verb} {len(entries)} files -> {dest}")
    print(f"  outputs: {', '.join(spec.label for spec in specs)}")

    if args.dry_run:
        return _convert_dry_run(entries, store_dir, source_root, specs)

    dest.mkdir(parents=True, exist_ok=True)
    state = batch.RunState(dest / batch.STATE_FILENAME, specs)
    if args.no_resume:
        state.done.clear()

    records: list[batch.FileRecord] = []
    # Paths this run must not write over. Files that are *skipped* add theirs
    # as they are skipped (see `_handle_entry`), so the guard still sees a
    # collision with something an earlier run wrote. Pre-seeding it from the
    # whole state instead was wrong in a way only a test caught: a file whose
    # output had been deleted was correctly chosen for re-conversion and then
    # refused permission to rewrite its own path.
    claimed: set[Path] = set()
    started, t0 = batch.now_iso(), time.time()
    interrupted = False

    # `--progress` mirrors the per-file log lines onto stdout. Nothing else
    # does: the trail has always gone to `conversion.log` alone, so anything
    # watching the process -- the desktop front end, a terminal on a long
    # run -- saw a header, an hour of silence, and a summary.
    echo = _echo_line if args.progress else None

    # `--stop-file` is the portable way to ask a run to stop and still get a
    # report. Ctrl+C and Ctrl+Break are the direct ones and are better where
    # they work -- they land immediately -- but a parent process cannot always
    # deliver a console signal to a child on Windows, and a caller that cannot
    # stop a run politely is a caller that has to kill it. Killing it is the
    # one ending that leaves no audit report at all.
    stop_file = Path(args.stop_file) if args.stop_file else None
    if stop_file is not None:
        # Guarded like every other path this command writes to, and for a
        # sharper reason than most: both uses below are deletes, so a stop
        # file inside the archive would destroy a source photograph and the
        # run would report success. `verify_unchanged` cannot catch it -- it
        # belongs to `scan`, which ran earlier.
        stop_file = config.ensure_outside_source(stop_file, source_root, "stop file")
        # Deliberately not deleted here. A marker left by an earlier run is
        # older than `run_started` and is ignored, so there is nothing to
        # clean up -- and nothing to race against a Cancel that arrives while
        # this run is still starting up.

    with batch.ConversionLog(dest / batch.LOG_FILENAME, echo=echo) as log:
        labels = ", ".join(s.label for s in specs)
        log.write(f"=== run start: {len(entries)} entries, outputs {labels}")
        # The whole loop, not just the conversion. The handler used to wrap
        # `_convert_one` alone, so a Ctrl-C landing in `state.save()` or in a
        # log write escaped and no audit report was written -- which is the
        # opposite of what an interruptible batch engine is for.
        try:
            for index, entry in enumerate(entries, start=1):
                if stop_file is not None and _stop_requested(stop_file, run_started):
                    # Checked between files, so the stop lands on a boundary
                    # rather than in the middle of a write. Raised rather than
                    # broken out of, so it takes the same road an interrupt
                    # takes and the report is written the same way.
                    log.write("STOP requested")
                    _remove_stop_file(stop_file, log)
                    raise KeyboardInterrupt
                record = _handle_entry(
                    entry=entry,
                    index=index,
                    total=len(entries),
                    state=state,
                    log=log,
                    store_dir=store_dir,
                    source_root=source_root,
                    dest=dest,
                    stems=stems,
                    claimed=claimed,
                    specs=specs,
                    supplied=supplied,
                )
                records.append(record)
        except KeyboardInterrupt:
            interrupted = True
            log.write("INTERRUPTED by the operator")

        # Always leave a state file behind, even for a run where nothing
        # converted. A destination with a report but no state reads as though
        # the bookkeeping were lost, and the next run cannot tell an empty
        # state from a missing one.
        state.save()

        report = batch.build_audit_report(
            records,
            specs=specs,
            output_root=dest,
            started=started,
            elapsed=batch.elapsed_since(t0),
            total_entries=len(entries),
            manifest_entries=len(all_entries),
            interrupted=interrupted,
        )
        batch.write_audit_report(report, dest / batch.REPORT_FILENAME)
        log.write(f"=== run end: {report['counts']}")

    print(batch.summarise(report))
    print(f"  report: {dest / batch.REPORT_FILENAME}")
    if report["failures"]:
        for failure in report["failures"][:20]:
            joined = "; ".join(failure["errors"])
            print(f"  FAILED {failure['store_name']}: {joined}", file=sys.stderr)
        if len(report["failures"]) > 20:
            print(
                f"  ... and {len(report['failures']) - 20} more, see the report",
                file=sys.stderr,
            )
        return 2
    return 1 if interrupted else 0


def _handle_entry(
    *,
    entry: dict[str, Any],
    index: int,
    total: int,
    state: batch.RunState,
    log: batch.ConversionLog,
    store_dir: Path,
    source_root: Path,
    dest: Path,
    stems: dict[str, str],
    claimed: set[Path],
    specs: tuple[outputs.OutputSpec, ...],
    supplied: album_dates_mod.AlbumDates,
) -> batch.FileRecord:
    """One manifest entry: resume it, convert it, or record why it failed.

    Never raises for a bad file. `KeyboardInterrupt` is deliberately allowed
    through -- the caller stops the run and still writes the report.
    """
    sha = entry["sha256"]
    store_name = entry["store_name"]
    album = layout.choose_album(entry)

    if state.is_done(sha, dest):
        stored = state.recall(sha)
        record = (
            batch.record_from_json(stored)
            if stored
            else batch.FileRecord(
                sha256=sha, store_name=store_name, album=album, status="resumed"
            )
        )
        # A skipped file still owns its paths. Without this the collision
        # guard could not see a clash with something an earlier run wrote,
        # and silently overwriting a converted photograph is exactly the
        # failure it exists to prevent.
        claimed.update(dest / rel for rel in record.outputs)
        return record

    try:
        record = _convert_one(
            entry=entry,
            store_dir=store_dir,
            source_root=source_root,
            dest=dest,
            stem=stems.get(sha),
            claimed=claimed,
            specs=specs,
            album=album,
            album_dates=supplied,
        )
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        # The whole point of the engine: one bad file is a line in the report,
        # not the end of a run over an irreplaceable archive.
        record = batch.FileRecord(
            sha256=sha,
            store_name=store_name,
            album=album,
            status="failed",
            errors=[f"{type(exc).__name__}: {exc}"],
        )

    if record.status == "converted":
        # Marked only on success, so a failure is retried by the next run
        # rather than remembered as done.
        state.mark(sha, record)
        state.save()
        log.write(
            f"OK   [{index}/{total}] {store_name} -> "
            f"{len(record.outputs)} files in {record.seconds:.1f}s"
        )
    else:
        log.write(f"FAIL [{index}/{total}] {store_name}: {'; '.join(record.errors)}")
    for warning in record.warnings:
        log.write(f"WARN {store_name}: {warning}")
    return record


def _resolve_fpx_path(
    entry: dict[str, Any], store_dir: Path, source_root: Path
) -> Path | None:
    path = store_dir / entry["store_name"]
    if path.is_file():
        return path
    alt = source_root / entry["preferred_relpath"]
    return alt if alt.is_file() else None


def _convert_one(
    *,
    entry: dict[str, Any],
    store_dir: Path,
    source_root: Path,
    dest: Path,
    stem: str | None,
    claimed: set[Path],
    specs: tuple[outputs.OutputSpec, ...],
    album: str,
    album_dates: album_dates_mod.AlbumDates | None = None,
) -> batch.FileRecord:
    sha, store_name = entry["sha256"], entry["store_name"]
    fpx_path = _resolve_fpx_path(entry, store_dir, source_root)
    if fpx_path is None:
        return batch.FileRecord(
            sha256=sha,
            store_name=store_name,
            album=album,
            status="failed",
            errors=["source file not found"],
        )

    started = time.time()
    res = writer_mod.write_single_entry_dual_output(
        fpx_path=fpx_path,
        entry=entry,
        output_root=dest,
        source_root=source_root,
        stem=stem,
        claimed=claimed,
        specs=specs,
        album_dates=album_dates,
    )
    # Everything this entry put on disk, images and source copy alike. The
    # resume check tests all of them, so a deleted sidecar brings the file
    # back rather than being skipped as done.
    relpaths = [str(path.relative_to(dest)) for path, _ in res.written]
    relpaths += [str(path.relative_to(dest)) for path in res.side_artifacts]

    pixel_sha = None
    if res.validation_ok and res.written:
        try:
            pixel_sha = batch.pixel_digest(decoder.decode_fpx(fpx_path).image)
        except Exception:  # noqa: BLE001
            # Only used to explain expected duplicates in the report. Failing
            # to compute it must not fail a conversion that already validated.
            pixel_sha = None

    return batch.FileRecord(
        sha256=sha,
        store_name=store_name,
        album=album,
        status="converted" if res.validation_ok else "failed",
        date_source=res.date_source,
        is_undated=res.is_undated,
        date_original=res.date_original,
        transform_status=res.transform_status,
        crop_applied=res.crop_applied,
        outputs=relpaths,
        pixel_sha256=pixel_sha,
        errors=res.errors,
        warnings=res.warnings,
        seconds=time.time() - started,
    )


def _convert_dry_run(
    entries: list[dict[str, Any]],
    store_dir: Path,
    source_root: Path,
    specs: tuple[outputs.OutputSpec, ...],
) -> int:
    """Walk without writing, and say what is missing before a real run finds out."""
    missing = 0
    for entry in entries:
        if _resolve_fpx_path(entry, store_dir, source_root) is None:
            missing += 1
            print(f"  missing source: {entry['store_name']}", file=sys.stderr)
    print(f"  {len(entries)} entries, {len(entries) * len(specs)} images would be written")
    if missing:
        print(f"  {missing} source files could not be found", file=sys.stderr)
        return 2
    return 0


def _album_dates_path(args: argparse.Namespace, manifest_path: Path) -> Path:
    """Where the owner's album dates live.

    Beside the manifest by default: it names albums, so it is local-only
    working material like everything else that does.
    """
    explicit = getattr(args, "album_dates", None)
    if explicit:
        return Path(explicit)
    return manifest_path.parent / album_dates_mod.DEFAULT_FILENAME


def cmd_gallery(args: argparse.Namespace) -> int:
    """Build the QA review page from a completed run."""
    dest = Path(args.dest) if args.dest else (config.REPO_ROOT / "output")
    report_path = Path(args.report) if args.report else dest / batch.REPORT_FILENAME
    if not report_path.is_file():
        print(
            f"No audit report at {report_path} - run `convert` first.", file=sys.stderr
        )
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    store_dir = Path(args.store) if args.store else config.FPX_STORE_DIR
    manifest_path = Path(args.manifest) if args.manifest else config.MANIFEST_PATH

    try:
        existing = album_dates_mod.load(_album_dates_path(args, manifest_path))
    except album_dates_mod.AlbumDateError as exc:
        print(f"album dates: {exc}", file=sys.stderr)
        return 1

    sidecar_dir = Path(args.sidecars) if args.sidecars else None
    items = gallery.build_items(
        report,
        store_dir=store_dir,
        sidecar_dir=sidecar_dir,
        thumbnails=not args.no_thumbnails,
    )
    if not items:
        print("The audit report lists no files.", file=sys.stderr)
        return 1

    # Beside the run it describes, not in a fixed repo-root directory: two
    # runs would otherwise overwrite each other's page, and a page that
    # describes a different run than the one you opened it for is worse than
    # no page at all.
    default_out = dest / "report" / gallery.REPORT_FILENAME
    out_path = Path(args.out) if args.out else default_out
    gallery.write_gallery(
        gallery.render_html(items, report=report, existing_dates=existing), out_path
    )

    needing = gallery.albums_needing_a_date(items)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Wrote {out_path} ({size_mb:.1f} MB, {len(items)} photos)")
    print(f"  {len(gallery.group_by_album(items))} albums, {len(needing)} with no capture date")
    if needing:
        print(
            "  Open it, fill in the dates you know, save the JSON it produces as "
            f"{_album_dates_path(args, manifest_path)}, and re-run convert."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpx-converter",
        description="Archival conversion of Kodak FlashPix (.fpx) photos. "
        "The source archive is read-only and is never modified.",
    )
    parser.add_argument("--version", action="version", version=f"fpx-converter {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # 1. scan
    p_scan = sub.add_parser("scan", help="walk the source tree read-only and write the manifest")
    p_scan.add_argument("--source", help="override FPX_SOURCE_ROOT")
    p_scan.add_argument("--manifest", help="where to write the manifest")
    p_scan.add_argument("--progress-every", type=int, default=100, metavar="N")
    p_scan.add_argument(
        "--resample",
        type=int,
        default=25,
        metavar="N",
        help="how many files to re-hash when proving the source is unchanged "
        "(0 disables content re-verification)",
    )
    p_scan.set_defaults(func=cmd_scan)

    # 2. ingest
    p_ingest = sub.add_parser("ingest", help="copy one file per distinct hash into the local store")
    p_ingest.add_argument("--manifest")
    p_ingest.add_argument("--dest")
    p_ingest.add_argument("--dry-run", action="store_true")
    p_ingest.add_argument(
        "--allow-unverified",
        action="store_true",
        help="ingest from a manifest whose scan did not prove the source unchanged",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    # 3. verify
    p_verify = sub.add_parser("verify", help="re-hash the local store against the manifest")
    p_verify.add_argument("--manifest")
    p_verify.add_argument("--dest")
    p_verify.set_defaults(func=cmd_verify)

    # 4. metadata
    p_meta = sub.add_parser(
        "metadata", help="extract metadata and emit raw .fpx.json sidecars"
    )
    p_meta.add_argument("--manifest")
    p_meta.add_argument("--store", help="path to ingested .fpx store directory")
    p_meta.add_argument("--dest", help="output directory for sidecars")
    p_meta.add_argument("--dry-run", action="store_true")
    p_meta.set_defaults(func=cmd_metadata)

    # 5. check-dates
    p_dates = sub.add_parser(
        "check-dates", help="run automated album folder ground-truth date check"
    )
    p_dates.add_argument("--manifest")
    p_dates.add_argument("--store", help="path to ingested .fpx store directory")
    p_dates.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when any album's import stamps disagree with its "
        "folder name (the gate; off by default because failing is expected here)",
    )
    p_dates.set_defaults(func=cmd_check_dates)

    # 6. thumbnail
    p_thumb = sub.add_parser(
        "thumbnail", help="extract embedded DIB thumbnails as PNG images"
    )
    p_thumb.add_argument("--manifest")
    p_thumb.add_argument("--store", help="path to ingested .fpx store directory")
    p_thumb.add_argument("--dest", help="output directory for thumbnails")
    p_thumb.add_argument("--dry-run", action="store_true")
    p_thumb.set_defaults(func=cmd_thumbnail)

    # 7. convert
    p_conv = sub.add_parser(
        "convert", help="execute dual output conversion (Deflate TIFF + q95 4:4:4 JPEG)"
    )
    p_conv.add_argument("--manifest")
    p_conv.add_argument("--store", help="path to ingested .fpx store directory")
    p_conv.add_argument("--dest", help="output root directory (defaults to output/)")
    p_conv.add_argument("--limit", type=int, help="limit number of files to convert")
    p_conv.add_argument("--dry-run", action="store_true")
    p_conv.add_argument(
        "--no-resume", action="store_true",
        help="convert every entry again, ignoring what a previous run recorded "
             "(resume is on by default: a killed run costs the file in flight, "
             "not the batch)",
    )

    # Format and framing are independent axes. They used to be welded to the
    # tree -- archive meant full-frame TIFF and sharing meant cropped JPEG --
    # so a full-frame JPEG could not be asked for at all. Defaults are the
    # shipped behaviour, so an existing command line is unchanged.
    fmt_choices = tuple(outputs.FORMATS)
    p_conv.add_argument(
        "--archive-format", choices=fmt_choices, default="tiff",
        help="file format for the archive tree (default: tiff, Deflate and lossless)",
    )
    p_conv.add_argument(
        "--archive-framing", choices=outputs.FRAMINGS, default="full",
        help="which pixels the archive copy keeps (default: full, every captured pixel)",
    )
    p_conv.add_argument(
        "--sharing-format", choices=fmt_choices, default="jpeg",
        help="file format for the sharing tree (default: jpeg, q95 4:4:4)",
    )
    p_conv.add_argument(
        "--sharing-framing", choices=outputs.FRAMINGS, default="cropped",
        help=(
            "which pixels the sharing copy keeps (default: cropped, the composition "
            "framed at the time); 'full' gives the largest uncropped image in an "
            "everyday format"
        ),
    )
    p_conv.add_argument(
        "--no-archive", action="store_true", help="do not write the archive tree"
    )
    p_conv.add_argument(
        "--no-sharing", action="store_true",
        help="do not write the sharing tree; with the defaults this leaves only the "
             "full-frame lossless TIFF",
    )
    p_conv.add_argument(
        "--stop-file",
        metavar="PATH",
        help="stop cleanly at the next file boundary if PATH appears, still "
             "writing the audit report (a caller that cannot deliver Ctrl+C to "
             "this process can create the file instead of killing it)",
    )
    p_conv.add_argument(
        "--progress",
        action="store_true",
        help="also print each per-file log line to stdout, so a long run can be "
             "watched (the desktop front end reads this to drive its progress bar)",
    )
    p_conv.add_argument(
        "--album-dates",
        help="JSON file of album -> YYYY-MM-DD dates you supplied via the gallery "
             "(default: album-dates.json beside the manifest)",
    )
    p_conv.set_defaults(func=cmd_convert)

    # 8. gallery
    p_gal = sub.add_parser(
        "gallery", help="build the QA review page from a completed run"
    )
    p_gal.add_argument("--dest", help="conversion output root (defaults to output/)")
    p_gal.add_argument("--report", help="path to audit_report.json")
    p_gal.add_argument("--manifest")
    p_gal.add_argument("--store", help="path to the ingested .fpx store directory")
    p_gal.add_argument("--sidecars", help="directory of .fpx.json sidecars, for dates")
    p_gal.add_argument("--album-dates", help="JSON file of dates you already supplied")
    p_gal.add_argument(
        "--out", help="where to write the page (defaults to <dest>/report/index.html)"
    )
    p_gal.add_argument(
        "--no-thumbnails",
        action="store_true",
        help="skip the embedded thumbnails; much faster and much less useful",
    )
    p_gal.set_defaults(func=cmd_gallery)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (config.ConfigError, config.SourceWriteRefused) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
