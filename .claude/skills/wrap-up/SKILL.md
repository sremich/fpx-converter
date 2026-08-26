---
name: wrap-up
description: Run the session-close checklist — tests, commit+push, CHANGELOG, DECISIONS, HANDOVER update. Use whenever Stevie says they're wrapping up, done for the day, or switching machines, and before ending any session that changed anything.
---

# Session wrap-up

Stevie roams between machines; GitHub and `HANDOVER.md` are what follow
him, not this conversation. Close the session so the next agent — on any
machine — can cold-start from the files alone.

Run the **session-close checklist at the top of `HANDOVER.md`** explicitly
and show the ticks in the conversation. In substance:

1. Tests green (tier 1 minimum; higher tiers if their triggers applied).
2. Everything committed AND pushed — GitHub is the source of truth, not
   OneDrive. Verify `git status` clean and local == origin.
3. `CHANGELOG.md` Unreleased section reflects this session's changes.
4. Anything decision-worthy from this session appended to `DECISIONS.md`
   (append-only, never edit old entries).
5. `HANDOVER.md` updated: Current state, Open items (park any mid-session
   ideas here), Session log entry, and the `_Last updated_` line.
6. If a release happened this session: compose pin bumped and the
   `/release` skill's checklist was completed.

If a checklist item can't be ticked (e.g. tests red, work half-done), say
so plainly in HANDOVER's Current state rather than skipping it silently —
"in flight, tier-1 failing on X" is exactly what the next session needs.
