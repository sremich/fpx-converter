# [PROJECT NAME] — decisions and hard-won lessons

> **Append-only.** Entries are never rewritten, reordered, or trimmed — a
> superseded decision gets a new entry pointing back, not an edit. This file
> exists because HANDOVER.md churns every session while lessons must not.
> It is **committed to the repo** so decisions survive into clones,
> worktrees, and CI/cloud agent sessions — write entries public-safe (no
> real IPs, hostnames, or credentials; that context belongs in HANDOVER.md,
> which stays local-only).
>
> Add an entry when: a design trade-off is chosen (and why), a debugging
> session yields a non-obvious fact, an incident teaches a rule, or an
> approach is deliberately rejected.

Format:

```
## YYYY-MM-DD — Short title
**Decision/Lesson:** what was decided or learned.
**Why:** the reasoning or the incident.
**Implication:** what future work must respect because of this.
```

---

## [DATE] — [First entry]
**Decision/Lesson:** …
**Why:** …
**Implication:** …
