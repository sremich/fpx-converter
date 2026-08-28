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

The same job, for the same reason, is done for the default time zone. From
1.3.0 the default is *this machine's own* zone rather than a built-in name, so
the expectations that spell out `-06:00` stopped being true anywhere outside
US Central -- red on a UK laptop and red in CI, where `windows-latest` is UTC.
The zone is therefore pinned here, once, instead of being re-hardcoded in each
test that happens to notice.
"""

from __future__ import annotations

import pytest

from fpx_converter import layout, timestamps

#: The zone every test runs in unless it says otherwise.
#:
#: US Central because that is the zone the fixture expectation tables were
#: written against -- the `-06:00` offsets in `test_fixtures_output.py` are
#: only the right answer there. It is a test-suite constant and not a default
#: the shipped tool has: `config.resolve_default_timezone` asks the machine,
#: and pinning it here is exactly what stops that machine's answer leaking
#: into an assertion.
TEST_DEFAULT_TZ = "America/Chicago"


@pytest.fixture(autouse=True)
def _no_local_env_album_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the two `.env`-driven album lists for every test.

    Patched at the cached helper rather than at `config`, so a stale
    `lru_cache` populated by an earlier test cannot leak through either.
    """
    monkeypatch.setattr(layout, "_extra_non_descriptive", frozenset)
    monkeypatch.setattr(timestamps, "_coarse_albums", frozenset)


@pytest.fixture(autouse=True)
def _pinned_default_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin `FPX_DEFAULT_TZ` for every test, so none of them asks the machine.

    `monkeypatch.setenv`, so it is undone after each test and a test that
    wants the machine's own answer -- or a different configured one -- takes
    it back with `delenv`/`setenv` and says why. Several already do.
    """
    monkeypatch.setenv("FPX_DEFAULT_TZ", TEST_DEFAULT_TZ)
