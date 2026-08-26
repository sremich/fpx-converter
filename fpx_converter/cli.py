"""Command line entry point: `python -m fpx_converter <command>`.

Commands available at 0.4.0:
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
import sys
from pathlib import Path

from . import __version__, config, naming, scan
from . import ingest as ingest_mod
from . import manifest as manifest_mod
from . import metadata as metadata_mod
from . import thumbnail as thumbnail_mod
from . import timestamps as timestamps_mod
from . import writer as writer_mod


def _human_mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


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


def cmd_convert(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest) if args.manifest else config.MANIFEST_PATH
    if not manifest_path.is_file():
        print(f"No manifest at {manifest_path} — run `scan` first.", file=sys.stderr)
        return 1

    manifest = manifest_mod.load(manifest_path)
    source_root = Path(manifest["source_root"])
    store_dir = Path(args.store) if args.store else config.FPX_STORE_DIR

    output_base = (
        Path(args.dest) if args.dest else (config.REPO_ROOT / "output")
    )
    dest = config.ensure_outside_source(output_base, source_root, "conversion destination")

    entries = manifest.get("entries", [])
    if args.limit and args.limit > 0:
        entries = entries[: args.limit]

    verb = "Would convert" if args.dry_run else "Converting"
    print(f"{verb} {len(entries)} files -> {dest}")

    converted = 0
    dated_count = 0
    undated_count = 0
    failures: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []

    # Names are resolved for the whole batch up front, from the manifest
    # alone, so two same-named photos in one album cannot resolve to the
    # same output file -- and so a resumed run assigns identical names.
    stems = naming.assign_output_stems(
        [
            (e["sha256"], writer_mod.primary_album(e), e.get("preferred_name", e["store_name"]))
            for e in entries
        ]
    )
    claimed: set[Path] = set()

    for entry in entries:
        store_name = entry["store_name"]
        fpx_path = store_dir / store_name
        if not fpx_path.is_file():
            alt = source_root / entry["preferred_relpath"]
            if alt.is_file():
                fpx_path = alt
            else:
                failures.append((store_name, "source file not found"))
                continue

        try:
            res = writer_mod.write_single_entry_dual_output(
                fpx_path=fpx_path,
                entry=entry,
                output_root=dest,
                source_root=source_root,
                dry_run=args.dry_run,
                stem=stems.get(entry["sha256"]),
                claimed=claimed,
            )
            if res.warnings:
                warnings.extend((store_name, w) for w in res.warnings)
            if res.validation_ok:
                converted += 1
                if res.is_undated:
                    undated_count += 1
                else:
                    dated_count += 1
            else:
                failures.append((store_name, "; ".join(res.errors)))
        except Exception as exc:  # noqa: BLE001
            failures.append((store_name, str(exc)))

    print(
        f"  converted {converted} files ({dated_count} dated, {undated_count} undated)"
    )
    if warnings:
        # Not failures -- the pixels are the source pixels -- but a discarded
        # crop is a difference from the original that has to be visible.
        print(f"  {len(warnings)} files with an unapplied viewing transform:")
        for name, why in warnings:
            print(f"    {name}: {why}")
    if failures:
        for name, why in failures:
            print(f"  FAILED {name}: {why}", file=sys.stderr)
        return 2
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
    p_conv.set_defaults(func=cmd_convert)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (config.ConfigError, config.SourceWriteRefused) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
