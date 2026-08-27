"""Shared test setup.

One job: **stop the developer's machine from changing what the tests mean.**

Two settings are archive-specific and therefore live in `.env`, which is
local-only and untracked — the album lists for `FPX_NON_DESCRIPTIVE_ALBUMS`
and `FPX_COARSE_ALBUMS`. Both are read through an `lru_cache` on first use, so
whichever test happened to touch them first decided the value for the whole
session. On the machine that has an `.env` the tier-1 suite was quietly
testing different behaviour than CI, which is the one difference a test suite
must never have.

Every test now starts from empty lists. A test that wants an entry patches the
same seams itself, and says so.
"""

from __future__ import annotations

import pytest

from fpx_converter import layout, timestamps


@pytest.fixture(autouse=True)
def _no_local_env_album_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the two `.env`-driven album lists for every test.

    Patched at the cached helper rather than at `config`, so a stale
    `lru_cache` populated by an earlier test cannot leak through either.
    """
    monkeypatch.setattr(layout, "_extra_non_descriptive", frozenset)
    monkeypatch.setattr(timestamps, "_coarse_albums", frozenset)
