"""Tier 3: a sample batch over the real corpus, with the checks that gate a merge.

`CLAUDE.md` requires this before merging any branch that touches decode or
metadata. It was previously run by hand, which meant the evidence for it was a
paragraph in a commit message and a directory whose timestamps did not line up
with the code being released -- both auditors caught that, independently. This
script exists so the run is reproducible and leaves an artifact.

The sample covers every album, every declared size, both colour spaces and all
four transform outcomes (untouched / crop / rotation / rotation+crop), then:

* converts through the real writer, ExifTool included
* re-reads every output with pyexiv2 -- a different tool than the one that wrote
* takes pixel statistics, so a decode that silently produced grey or clipped
  output is visible without opening a file
* runs the embedded-thumbnail oracle over the cropped files (geometry only --
  it is greyscale, so it says nothing about colour)
* compares each output's **chroma** against its thumbnail (`R-G`, `B-G`),
  which is the colour check -- correlating the channels separately is not,
  because Pearson correlation is invariant under a per-channel affine map
* runs the album ground-truth date check

Reads the source archive. Writes only under `--dest`, which must be outside it.

    python scripts/tier3_sample.py --dest output/tier3-<version>
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from fpx_converter import (  # noqa: E402
    config,
    decoder,
    layout,
    metadata,
    naming,
    oracles,
    thumbnail,
    timestamps,
    validator,
    writer,
)

# The colour oracle lives in the package now, so tiers 1 and 2 use the very
# same code. Re-exported under the old names to keep this script readable.
CHROMA_MIN_CORRELATION = oracles.CHROMA_MIN_CORRELATION
CHROMA_SCALE_RANGE = oracles.CHROMA_SCALE_RANGE
CHROMA_MAX_OFFSET = oracles.CHROMA_MAX_OFFSET
chroma_agreement = oracles.chroma_agreement
chroma_faults = oracles.chroma_faults

SAMPLE_TARGET = 50


def profile(path: Path) -> tuple[str, str, str] | None:
    """`(transform outcome, declared size, colour space)` for one file."""
    try:
        dec = decoder.decode_fpx(path)
    except Exception as exc:  # noqa: BLE001
        return ("DECODE-FAIL: " + type(exc).__name__, "", "")
    cropped = dec.crop_applied is not None
    if dec.rotation_applied == 90:
        kind = "rotation+crop" if cropped else "rotation"
    elif cropped:
        kind = "crop"
    else:
        kind = dec.transform_status
    return (kind, f"{dec.declared_width}x{dec.declared_height}", dec.colour_space)


def pixel_stats(image) -> tuple[float, float, float]:
    """`(mean, stdev, fraction of pixels clipped at 0 or 255)`.

    A decode that fell back to a single fill colour, or that clipped a
    channel, is invisible in a size check and obvious here.
    """
    arr = np.asarray(image.convert("RGB"), dtype=np.uint8)
    clipped = float(np.mean((arr == 0) | (arr == 255)))
    return float(arr.mean()), float(arr.std()), clipped




def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default="output/tier3", type=Path)
    parser.add_argument("--manifest", default=None, type=Path)
    parser.add_argument("--store", default=None, type=Path)
    args = parser.parse_args()

    store = args.store or (REPO_ROOT / "source-files" / "fpx")
    manifest_path = args.manifest or (REPO_ROOT / "source-files" / "manifest.json")
    dest = (REPO_ROOT / args.dest).resolve() if not args.dest.is_absolute() else args.dest
    # The read-only rule is enforced in code, not left to whoever runs this.
    config.ensure_outside_source(dest, store.parent, "tier-3 destination")

    entries = json.loads(manifest_path.read_text(encoding="utf-8"))["entries"]
    by_sha = {e["sha256"]: e for e in entries}

    t0 = time.time()
    print(f"profiling {len(entries)} manifest entries...")
    profiles: dict[str, tuple[str, str, str]] = {}
    album_of: dict[str, str] = {}
    for entry in entries:
        path = store / entry["store_name"]
        if not path.is_file():
            continue
        prof = profile(path)
        if prof is not None:
            profiles[entry["sha256"]] = prof
            album_of[entry["sha256"]] = layout.choose_album(entry)

    albums = set(album_of.values())
    print(f"  {len(profiles)} files, {len(albums)} albums, {time.time() - t0:.0f}s")
    print("  transform outcomes:", dict(collections.Counter(p[0] for p in profiles.values())))
    print("  declared sizes:    ", dict(collections.Counter(p[1] for p in profiles.values())))
    print("  colour spaces:     ", dict(collections.Counter(p[2] for p in profiles.values())))

    # Sample: cover every value of every axis, then top up.
    picked: dict[str, dict] = {}

    def cover(key, want: int) -> None:
        seen: collections.Counter = collections.Counter()
        for sha in profiles:
            value = key(sha)
            if seen[value] < want:
                seen[value] += 1
                picked[sha] = by_sha[sha]

    cover(lambda s: profiles[s][0], 4)  # transform outcome
    cover(lambda s: profiles[s][1], 2)  # declared size
    cover(lambda s: profiles[s][2], 2)  # colour space
    cover(lambda s: album_of[s], 2)  # album
    for sha in profiles:
        if len(picked) >= SAMPLE_TARGET:
            break
        picked.setdefault(sha, by_sha[sha])

    print(f"\nsample of {len(picked)}:")
    print("  transform outcomes:", dict(collections.Counter(profiles[s][0] for s in picked)))
    print("  declared sizes:    ", dict(collections.Counter(profiles[s][1] for s in picked)))
    print("  colour spaces:     ", dict(collections.Counter(profiles[s][2] for s in picked)))
    print(f"  albums:             {len({album_of[s] for s in picked})} of {len(albums)}")

    # Stems come from the whole manifest, not the sample, so the names a
    # sample run produces are the names the full run would.
    stems = naming.assign_output_stems(
        [
            (e["sha256"], layout.stem_scope(e), e.get("preferred_name", e["store_name"]))
            for e in entries
        ]
    )

    print("\nconverting...")
    t1 = time.time()
    claimed: set[Path] = set()
    results: dict[str, object] = {}
    failures: list[str] = []
    for sha, entry in picked.items():
        try:
            results[sha] = writer.write_single_entry_dual_output(
                store / entry["store_name"],
                entry,
                output_root=dest,
                source_root=store.parent,
                stem=stems.get(sha),
                claimed=claimed,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{sha[:8]} raised {type(exc).__name__}: {exc}")
    print(f"  {len(results)} converted in {time.time() - t1:.0f}s")

    errored = [r for r in results.values() if r.errors]  # type: ignore[attr-defined]
    warned = [r for r in results.values() if r.warnings]  # type: ignore[attr-defined]
    cropped_out = [r for r in results.values() if r.crop_applied]  # type: ignore[attr-defined]
    print(f"  clean: {len(results) - len(errored)} / {len(results)}")
    print(f"  cropped JPEGs: {len(cropped_out)}")
    for r in errored:
        failures.append(f"errors: {r.errors[:2]}")  # type: ignore[attr-defined]
    for r in warned:
        print(f"  WARNING {r.warnings[:1]}")  # type: ignore[attr-defined]

    # --- pixel statistics and colour ---------------------------------------
    print("\npixel statistics and colour over the sample:")
    means, stdevs, flat, suspect_clip, off_colour, no_thumb = [], [], [], [], [], []
    worst_corr, worst_offset = 1.0, 0.0
    for sha in picked:
        path = store / by_sha[sha]["store_name"]
        dec = decoder.decode_fpx(path)
        mean, stdev, clip = pixel_stats(dec.image)
        means.append(mean)
        stdevs.append(stdev)
        if stdev < 1.0:
            flat.append(sha[:8])

        try:
            thumb = thumbnail.extract_thumbnail(path)
        except Exception as exc:  # noqa: BLE001
            # Counted and printed, never skipped in silence. A file the colour
            # check could not examine is a gap in the run, not a pass.
            no_thumb.append(f"{sha[:8]} ({type(exc).__name__})")
            continue

        # Against the cropped image, not the full frame: the thumbnail shows
        # the composition somebody framed, so a cropped file's full frame
        # disagrees with it for reasons that have nothing to do with colour.
        metrics = chroma_agreement(dec.cropped_image(), thumb)
        worst_corr = min(worst_corr, metrics["cr_corr"], metrics["cb_corr"])
        worst_offset = max(
            worst_offset, abs(metrics["cr_offset"]), abs(metrics["cb_offset"])
        )
        faults = chroma_faults(metrics)
        if faults:
            off_colour.append(f"{sha[:8]}: {', '.join(faults)}")

        # Heavy clipping is a fault only when the thumbnail disagrees: some
        # photographs really are blown out, and their own thumbnail says so.
        # The gate is 25%, not 50% -- the double-conversion bug this check was
        # written for clipped 42%, and a threshold its own motivating defect
        # slides under is decoration.
        if clip > 0.25:
            _, _, thumb_clip = pixel_stats(thumb)
            if thumb_clip < clip / 2:
                suspect_clip.append(f"{sha[:8]} ({clip:.0%} vs thumbnail {thumb_clip:.0%})")
    print(f"  mean brightness  {min(means):.1f} .. {max(means):.1f}")
    print(f"  stdev            {min(stdevs):.1f} .. {max(stdevs):.1f}")
    print(f"  median stdev     {statistics.median(stdevs):.1f}")
    print(f"  worst chroma correlation {worst_corr:.3f} (gate {CHROMA_MIN_CORRELATION})")
    print(f"  worst chroma offset      {worst_offset:+.1f} (gate {CHROMA_MAX_OFFSET})")
    if flat:
        failures.append(f"near-flat images (a fill-tile fallback would look like this): {flat}")
    if suspect_clip:
        failures.append(f"clipped far more than their own thumbnail: {suspect_clip}")
    if off_colour:
        failures.append(f"colour disagrees with the embedded thumbnail: {off_colour}")
    if no_thumb:
        failures.append(f"no thumbnail, so colour could not be checked at all: {no_thumb}")
    print(
        f"  near-flat: {len(flat)}   suspect clipping: {len(suspect_clip)}   "
        f"off-colour: {len(off_colour)}   unchecked: {len(no_thumb)}"
    )

    # --- thumbnail oracle, geometry only ----------------------------------
    deltas = []
    for sha in picked:
        if profiles[sha][0] not in ("crop", "rotation+crop"):
            continue
        path = store / by_sha[sha]["store_name"]
        dec = decoder.decode_fpx(path)
        thumb = thumbnail.extract_thumbnail(path)
        deltas.append(
            thumbnail.compute_image_correlation(dec.cropped_image(), thumb)
            - thumbnail.compute_image_correlation(dec.image, thumb)
        )
    print("\nthumbnail oracle over the cropped files in the sample (geometry only):")
    if deltas:
        print(
            f"  improved on {sum(1 for d in deltas if d > 0)} of {len(deltas)}, "
            f"mean {sum(deltas) / len(deltas):+.3f}, min {min(deltas):+.3f}"
        )
        if any(d < 0 for d in deltas):
            failures.append("cropping moved a file away from its own thumbnail")

    # --- independent read-back -------------------------------------------
    print("\nre-reading every output with pyexiv2:")
    violations = 0
    for sha, entry in picked.items():
        meta = metadata.extract_fpx_metadata(store / entry["store_name"], manifest_entry=entry)
        stem = stems.get(sha)
        tif = dest / "archive" / writer.build_output_relpath(entry, meta.derived, "tif", stem)
        jpg = dest / "sharing" / writer.build_output_relpath(entry, meta.derived, "jpg", stem)
        if not tif.is_file() or not jpg.is_file():
            failures.append(f"{sha[:8]}: output missing on disk")
            violations += 1
            continue
        result = validator.validate_dual_output(tif, jpg, meta.derived)
        if not result.ok:
            violations += 1
            failures.append(f"{sha[:8]}: {result.errors[:3]}")
    print(f"  {len(picked)} pairs read back, {violations} with violations")

    # --- album ground truth ----------------------------------------------
    # A report, not a gate. On this corpus the import stamp misses most dated
    # albums, which is precisely why it is not trusted as a capture date --
    # so a failing verdict here is the expected state, not a regression.
    print("\nalbum ground-truth date check (report, not a gate -- see CLAUDE.md):")
    stamps: dict[str, datetime.datetime] = {}
    for sha in picked:
        derived = metadata.extract_fpx_metadata(
            store / by_sha[sha]["store_name"], manifest_entry=by_sha[sha]
        ).derived
        iso = derived.get("timestamps", {}).get("import_datetime")
        if iso:
            stamps[sha] = datetime.datetime.fromisoformat(iso)
    report = timestamps.check_manifest_ground_truth({"entries": entries}, stamps)
    print(
        f"  {report.total_albums} albums represented: {report.passed_albums} pass, "
        f"{report.near_albums} near, {report.failed_albums} fail, "
        f"{report.undated_albums} undated"
    )

    print(f"\ntotal {time.time() - t0:.0f}s")
    if failures:
        print(f"\nTIER 3 FAILED -- {len(failures)} problems:")
        for line in failures[:20]:
            print(f"  {line}")
        return 1
    print("\nTIER 3 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
