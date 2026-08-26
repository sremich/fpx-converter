"""Command line entry point: `python -m fpx_converter <command>`.

Commands available at 0.1.0 are the read-only ones — `scan`, `ingest`, and
`verify`. Nothing here converts a photo; the decoder and the batch engine
arrive at 0.3.0 and 0.5.0.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config, scan
from . import ingest as ingest_mod
from . import manifest as manifest_mod


def _human_mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


def cmd_scan(args: argparse.Namespace) -> int:
    # An explicit --source stands alone: settings are only consulted when the
    # caller did not say which tree to walk, so a one-off scan does not
    # require a populated .env.
    source_root = (
        Path(args.source).resolve() if args.source else config.Settings.load().source_root
    )
    manifest_path = Path(args.manifest) if args.manifest else config.MANIFEST_PATH

    print(f"Scanning (read-only): {source_root}")
    scanned, snapshot = scan.scan_tree(source_root, progress_every=args.progress_every)
    if not scanned:
        print("No .fpx files found.", file=sys.stderr)
        return 1

    manifest = manifest_mod.build(
        scanned, source_root=source_root, tool_version=__version__
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
    print("Verifying the source tree is unchanged...")
    hashes = {str(item.path): item.sha256 for item in scanned}
    report = scan.verify_unchanged(snapshot, hashes, sample_size=args.resample)
    print(f"  stat-checked {report.checked}, re-hashed {report.resampled}")
    if report.ok:
        print("  source tree is byte-identical to before the scan")
    else:
        for label, items in (
            ("MODIFIED", report.modified),
            ("VANISHED", report.vanished),
            ("HASH MISMATCH", report.rehash_mismatches),
        ):
            for path in items:
                print(f"  {label}: {path}", file=sys.stderr)
        return 2
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    # No Settings.load() here on purpose: the manifest records the source root
    # it was built from, and ingest must copy from exactly that tree. Reading
    # .env again would let a since-edited path silently repoint the copy.
    manifest_path = Path(args.manifest) if args.manifest else config.MANIFEST_PATH
    if not manifest_path.is_file():
        print(f"No manifest at {manifest_path} — run `scan` first.", file=sys.stderr)
        return 1

    manifest = manifest_mod.load(manifest_path)
    dest = Path(args.dest) if args.dest else config.FPX_STORE_DIR
    source_root = Path(manifest["source_root"])

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fpx-converter",
        description="Archival conversion of Kodak FlashPix (.fpx) photos. "
        "The source archive is read-only and is never modified.",
    )
    parser.add_argument("--version", action="version", version=f"fpx-converter {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="walk the source tree read-only and write the manifest")
    p_scan.add_argument("--source", help="override FPX_SOURCE_ROOT")
    p_scan.add_argument("--manifest", help="where to write the manifest")
    p_scan.add_argument("--progress-every", type=int, default=100, metavar="N")
    p_scan.add_argument(
        "--resample",
        type=int,
        default=25,
        metavar="N",
        help="how many files to re-hash when proving the source is unchanged",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_ingest = sub.add_parser("ingest", help="copy one file per distinct hash into the local store")
    p_ingest.add_argument("--manifest")
    p_ingest.add_argument("--dest")
    p_ingest.add_argument("--dry-run", action="store_true")
    p_ingest.set_defaults(func=cmd_ingest)

    p_verify = sub.add_parser("verify", help="re-hash the local store against the manifest")
    p_verify.add_argument("--manifest")
    p_verify.add_argument("--dest")
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except config.ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
