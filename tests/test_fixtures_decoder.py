"""Tier-2: end-to-end pixel decoding over real committed `.fpx` fixtures.

No fixture contains an identifiable person: sixteen files of unknown origin
plus twenty-one archive photographs screened by eye and renamed to a neutral
stem. Never add a photograph with a recognisable person in it, and never keep
a filename somebody typed -- this project treats filenames as the archive's
captions. See `tests/fixtures/LICENSE.md` for the exact screening standard.

`EXPECTED_FIXTURES` below pins the originals in detail. The parametrised
tests run over everything in the directory, so a fixture added later is
covered the moment it lands rather than when somebody remembers to add it to
a list.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from fixture_coverage import NO_CROPPED_FIXTURE_REASON

from fpx_converter import decoder, thumbnail

pytestmark = pytest.mark.fixtures

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_FIXTURES = {
    "Clouds01.fpx": {
        "width": 1152,
        "height": 864,
        "num_resolutions": 6,
        "min_thumb_corr": 0.97,
    },
    "P0000016.FPX": {
        "width": 640,
        "height": 480,
        "num_resolutions": 5,
        "min_thumb_corr": 0.97,
    },
    "harbor.fpx": {
        "width": 768,
        "height": 512,
        "num_resolutions": 5,
        "min_thumb_corr": 0.99,
    },
    "squirrel.fpx": {
        "width": 996,
        "height": 1536,
        "num_resolutions": 6,
        "min_thumb_corr": 0.97,
    },
}


def test_decodes_all_real_fixtures_and_correlates_with_thumbnail() -> None:
    for filename, expected in EXPECTED_FIXTURES.items():
        fpx_path = FIXTURES / filename
        assert fpx_path.is_file()

        # 1. Decode full resolution image
        decoded = decoder.decode_fpx(fpx_path)
        img = decoded.image
        assert (
            img.size == (expected["width"], expected["height"])
        ), f"{filename} dimensions mismatch"
        assert img.mode == "RGB"

        # 2. Assert non-black, non-uniform pixel statistics
        arr = np.asarray(img, dtype=np.float32)
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))
        assert mean_val > 30.0, f"{filename} decoded nearly black (mean={mean_val})"
        assert std_val > 25.0, f"{filename} decoded flat/uniform (std={std_val})"

        # 3. Extract embedded thumbnail and correlate
        thumb = thumbnail.extract_thumbnail(fpx_path)
        assert thumb.mode == "RGB"

        corr = thumbnail.compute_image_correlation(img, thumb)
        assert corr >= expected["min_thumb_corr"], (
            f"{filename} thumb corr {corr:.4f} < {expected['min_thumb_corr']}"
        )


def test_decodes_all_pyramid_levels_on_clouds() -> None:
    fpx_path = FIXTURES / "Clouds01.fpx"
    expected_resolutions = [
        (0, 36, 27),
        (1, 72, 54),
        (2, 144, 108),
        (3, 288, 216),
        (4, 576, 432),
        (5, 1152, 864),
    ]
    for r_idx, exp_w, exp_h in expected_resolutions:
        decoded = decoder.decode_fpx(fpx_path, resolution_index=r_idx)
        assert decoded.image.size == (exp_w, exp_h), f"Res {r_idx} size mismatch"
        assert decoded.image.mode == "RGB"


def test_uncompressed_harbor_matches_pillow_oracle_in_subprocess() -> None:
    """Compare custom decoder against Pillow's FpxImagePlugin on uncompressed fixture.

    Pillow is executed in an isolated subprocess to protect against potential interpreter crashes.
    """
    harbor_path = FIXTURES / "harbor.fpx"
    custom_decoded = decoder.decode_fpx(harbor_path).image
    cmd = [
        sys.executable,
        "-c",
        """
import sys, json
from PIL import Image
import numpy as np

fpx_path = sys.argv[1]
with Image.open(fpx_path) as im:
    im.load()
    arr = np.asarray(im.convert("RGB"))
    # Output stats
    res = {
        "shape": list(arr.shape),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "sample": arr[100:110, 100:110, :].tolist()
    }
    print(json.dumps(res))
""",
        str(harbor_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    pil_info = json.loads(proc.stdout)

    assert pil_info["shape"] == [512, 768, 3]

    custom_arr = np.asarray(custom_decoded)
    custom_mean = float(np.mean(custom_arr))
    custom_std = float(np.std(custom_arr))

    # Mean difference on uncompressed raw pixels should be exactly 0.0
    assert pytest.approx(custom_mean, abs=1e-3) == pil_info["mean"]
    assert pytest.approx(custom_std, abs=1e-3) == pil_info["std"]
    assert custom_arr[100:110, 100:110, :].tolist() == pil_info["sample"]


#: Greyscale correlation against the file's own embedded DIB. Measured, not
#: guessed: 36 of the 37 fixtures score 0.957 or better and most exceed 0.99.
GEOMETRY_FLOOR = 0.95

#: One exception, recorded rather than explained away. `starfish.fpx` scores
#: 0.882 -- a wide smooth gradient of wet sand at sunset has little structure
#: for a 96-pixel greyscale correlation to lock onto, and this is also one of
#: the four files whose decode is ~20% darker than its own thumbnail for
#: reasons still open (see HANDOVER). Its framing is right; the metric is
#: weak on this subject. Do not raise the general floor by loosening it here.
GEOMETRY_FLOORS = {"starfish.fpx": 0.85}


def _all_fixtures() -> list[Path]:
    return sorted(p for p in FIXTURES.iterdir() if p.suffix.lower() == ".fpx")


@pytest.mark.parametrize("path", _all_fixtures(), ids=lambda p: p.name)
def test_every_fixture_decodes_at_its_own_declared_size(path: Path) -> None:
    """Never hardcode 1152x864: the size is read per file and used everywhere.

    Seven declared sizes exist in this archive. Asserting against the
    decoder's own `declared_width`/`declared_height` rather than a constant is
    the point -- a decode that quietly produced the wrong grid would still
    match a hardcoded expectation.
    """
    decoded = decoder.decode_fpx(path)
    assert decoded.image.mode == "RGB"
    assert decoded.image.size == (decoded.declared_width, decoded.declared_height)
    assert decoded.colour_space in {"NIF_RGB", "PhotoYCC"}


@pytest.mark.parametrize("path", _all_fixtures(), ids=lambda p: p.name)
def test_every_fixture_agrees_with_its_own_thumbnail_geometry(path: Path) -> None:
    """The greyscale oracle: framing and orientation, and nothing about colour.

    Deliberately not cited anywhere as evidence about colour -- that is
    `test_fixtures_colour.py`, and conflating the two is how two solidly green
    files passed every check this project had.
    """
    decoded = decoder.decode_fpx(path)
    thumb = thumbnail.extract_thumbnail(path)
    corr = thumbnail.compute_image_correlation(decoded.cropped_image(), thumb)
    floor = GEOMETRY_FLOORS.get(path.name, GEOMETRY_FLOOR)
    assert corr >= floor, f"{path.name} geometry correlation {corr:.3f} < {floor}"


@pytest.mark.skip(reason=NO_CROPPED_FIXTURE_REASON)
def test_a_cropped_fixture_crops_and_the_crop_is_the_right_box() -> None:
    """The committed cover for the crop branch. Kept, skipped, not deleted.

    Both of this project's crop defects shipped because no fixture carried a
    viewing transform: 53 files cropped where 70 should have been, then 14
    rotated files dropping their crop entirely. A matrix's shape does not tell
    you whether it crops -- the box is the authority -- so this asserts the
    box does something, and that doing it moves the image *towards* the
    thumbnail rather than away.

    It ran against `feeder-crop.fpx` until 2026-08-27, when that file was
    deleted for containing a person; see `NO_CROPPED_FIXTURE_REASON`. The body
    below no longer names a fixture, so restoring this test is deleting one
    decorator -- and `test_fixtures_colour.py` goes red to tell you to, the
    moment a cropped fixture is committed again.
    """
    candidates = [p for p in _all_fixtures() if decoder.decode_fpx(p).crop_applied]
    assert candidates, "no cropped fixture: this test should still be skipped"
    path = candidates[0]
    decoded = decoder.decode_fpx(path)

    assert decoded.crop_applied is not None, "the crop fixture stopped carrying a crop"
    left, top, right, bottom = decoded.crop_applied
    assert 0 <= left < right <= decoded.declared_width
    assert 0 <= top < bottom <= decoded.declared_height
    assert decoded.cropped_image().size != decoded.image.size

    # `image` always keeps the full frame -- archive/ preserves every captured
    # pixel -- so the crop must be visible only through `cropped_image()`.
    assert decoded.image.size == (decoded.declared_width, decoded.declared_height)

    thumb = thumbnail.extract_thumbnail(path)
    full = thumbnail.compute_image_correlation(decoded.image, thumb)
    cropped = thumbnail.compute_image_correlation(decoded.cropped_image(), thumb)
    assert cropped > full, (
        f"cropping moved the image away from its own thumbnail "
        f"({full:.3f} -> {cropped:.3f})"
    )
