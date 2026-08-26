"""Tier-2: end-to-end pixel decoding over real committed `.fpx` fixtures.

The four fixtures are non-personal Kodak stock sample images that shipped with
Picture Easy. Never add personal photos here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

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
