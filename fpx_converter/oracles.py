"""Correctness oracles that compare a decode against evidence inside the file.

Split out of `scripts/tier3_sample.py` so tier 1, tier 2 and tier 3 run the
*same* colour check rather than three drifting copies. That mattered here:
the first version of this oracle could not detect colour at all, and having
one definition means fixing it fixes every tier at once.

The greyscale oracle lives in `thumbnail`; this module is the colour half.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

#: Gates for `chroma_agreement`, calibrated against the 685 NIF_RGB files in
#: this corpus and checked against deliberately broken decodes. Baseline
#: spread, then the value each fault produces:
#:
#:   metric        baseline (685 files)      R/B swap   greyscale   wrong neutral
#:   correlation   0.893 .. 0.999            -0.76      0.0         unchanged
#:   scale         0.754 .. 1.179            0.47/1.32  0.0         unchanged
#:   offset        -17.1 .. +9.7             -39 .. +42 unchanged   -50 .. -53
#:
#: The scale range is deliberately tighter than "outside the baseline": at
#: (0.45, 2.2) a decode at half saturation tripped 1% of files and one at
#: double tripped 2%, which is not a gate. (0.65, 1.45) still clears all 687.
#:
#: All three are needed. Correlation catches a swap, scale catches a lost or
#: exaggerated chroma, and offset catches a wrong neutral point -- which is
#: half of the bug this release exists to fix and which the other two cannot
#: see, because a constant shift leaves both unchanged.
CHROMA_MIN_CORRELATION = 0.5
CHROMA_SCALE_RANGE = (0.65, 1.45)
CHROMA_MAX_OFFSET = 30.0

#: Known blind spot, measured rather than assumed. Chroma is `R-G` and `B-G`,
#: so an error confined to the **green** channel moves both signals together
#: and largely cancels: a green gain of x1.10 trips no gate on any of the 687
#: files, while a comparable red gain trips 39% of them. A green-only fault is
#: therefore tier 4's to catch, not this script's.
#:
#: The scale gate's lower bound is also anchored on four files whose decode is
#: ~20% darker than their own thumbnail for reasons nobody has explained yet
#: -- two PhotoYCC and two NIF_RGB. Re-derive these numbers once tier 4 has
#: settled that, rather than treating the current spread as the truth.


def _chroma(image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """`(R-G, B-G)` at 64x64. Chroma, with luma divided out."""
    arr = np.asarray(image.resize((64, 64)).convert("RGB"), dtype=np.float32)
    return arr[:, :, 0] - arr[:, :, 1], arr[:, :, 2] - arr[:, :, 1]


def chroma_agreement(image: Image.Image, thumb: Image.Image) -> dict[str, float]:
    """How the output's colour compares with the embedded DIB thumbnail.

    This is the colour check. `thumbnail.compute_image_correlation` folds both
    images to greyscale before correlating, so it witnesses framing and
    orientation and says nothing whatever about colour. The DIB itself is
    stored as uncompressed RGB by the same software that wrote the pixels, so
    it can answer the colour question -- but only if it is asked properly.

    Correlating the R, G and B channels *separately* is not asking properly,
    and that was this function's first form. Pearson correlation is invariant
    under any per-channel affine map, so a wrong gain or a wrong neutral point
    scores exactly as well as a correct decode. Measured on this corpus, that
    version passed a decode with the wrong PhotoYCC neutral, passed a fully
    desaturated decode, and passed one with red and blue swapped. It caught
    the shipped double-conversion bug only because that also clipped 42% of
    the pixels -- which is not an affine map, and is not what was being
    tested.

    Comparing chroma directly fixes that: `R-G` and `B-G` remove the luma the
    greyscale oracle already covers and leave the part it cannot see.
    Correlation, scale and offset are reported separately because each
    catches a different fault; see the constants above for the numbers.

    It is still not an eye. A 96-pixel thumbnail cannot settle whether a
    photograph looks right, and the tier-4 pass at 1.0.0 is not optional
    because this exists.
    """
    out: dict[str, float] = {}
    image_chroma, thumb_chroma = _chroma(image), _chroma(thumb)
    for name, x, y in zip(("cr", "cb"), image_chroma, thumb_chroma, strict=True):
        sx, sy = float(x.std()), float(y.std())
        # A flat chroma channel is the strongest colour-fault signal there is
        # -- fully desaturated, or fully clipped. The first version scored it
        # 1.0 and called it "not a fault", which made the one unambiguous
        # case the one guaranteed to pass.
        if sy < 1e-6:
            # The *thumbnail* is flat: a genuinely monochrome subject. Nothing
            # to compare against, so only the output being non-flat is odd.
            out[f"{name}_corr"] = 1.0
            out[f"{name}_scale"] = 1.0 if sx < 1e-6 else float("inf")
        elif sx < 1e-6:
            out[f"{name}_corr"] = 0.0
            out[f"{name}_scale"] = 0.0
        else:
            out[f"{name}_corr"] = float(np.corrcoef(x.ravel(), y.ravel())[0, 1])
            out[f"{name}_scale"] = sx / sy
        out[f"{name}_offset"] = float(x.mean() - y.mean())
    return out


def chroma_faults(metrics: dict[str, float]) -> list[str]:
    """Which gates a `chroma_agreement` result trips, by name. Empty is good."""
    faults = []
    for name in ("cr", "cb"):
        if metrics[f"{name}_corr"] < CHROMA_MIN_CORRELATION:
            faults.append(f"{name} correlation {metrics[f'{name}_corr']:.2f}")
        scale = metrics[f"{name}_scale"]
        if not CHROMA_SCALE_RANGE[0] <= scale <= CHROMA_SCALE_RANGE[1]:
            faults.append(f"{name} scale {scale:.2f}")
        if abs(metrics[f"{name}_offset"]) > CHROMA_MAX_OFFSET:
            faults.append(f"{name} offset {metrics[f'{name}_offset']:+.1f}")
    return faults
