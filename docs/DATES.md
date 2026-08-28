# Dates

Why your converted photographs may have no capture date, why some filenames
read `0000-00-00`, and how to give the tool a date it will accept.

This is the single most surprising thing the tool does, and it is deliberate in
every particular.

## There is no capture date in these files

The FlashPix format has a capture-date property. In the archive this tool was
built for, it is **absent from every single file** — 1,265 of them. The cameras
of the era did not write one.

What the files *do* carry is a **Kodak import-batch stamp**: the moment the
photographs were pulled off the camera onto a computer. That is a real fact and
the tool records it faithfully. It is not the same thing as when the picture was
taken.

How different? On the reference archive the import stamp disagrees with what
the folder names say on **7 of 9 dated albums** — sometimes by months, once by a
whole calendar year, with a worst case of 223 days. A shoebox of photographs
imported in one sitting all get the same stamp regardless of when they were
taken.

So:

- The import stamp is written to **`DateTimeDigitized`** and **`xmp:CreateDate`**,
  which is exactly what those fields mean. It is always present.
- It is **never** written to `DateTimeOriginal`.

If your photo application sorts by "date taken" and shows nothing, that is the
tool declining to state something it does not know. It is not a bug and it is
not a missing feature.

## "Defensible" means a single day

`DateTimeOriginal` is written only where a date is independently defensible,
and defensible means **a single, specific day**.

A folder named for a year, a two-year span, a season, or a month does not date a
photograph. EXIF has no way to record a partial date — there is no way to say
"sometime in 2001". Writing the tag at all means naming a day, an hour, a minute
and a second.

The first version of this tool did not draw that line. It accepted any folder
name that parsed, took the first day of the range, and borrowed the hour, minute
and second from the import stamp. The result: **151 of 687 files** carried a
fabricated capture moment, precise to the second, in the one field reserved for
things that are actually known. That is what the rule exists to prevent.

Three sources can produce a `DateTimeOriginal`:

1. **A folder name that gives a single day.**
2. **An owner-supplied album date** — see the round trip below.
3. **An embedded scan date**, on the handful of files that carry one.

Anything coarser is kept, but not as a claim.

## Why some filenames read `0000-00-00`

Coarse dates are still useful, so they are not thrown away. They become
`sort_datetime`, which drives two things:

- the **filesystem modification time** of the output, and
- the **date prefix in the filename**, which by default looks like
  `2001-07-14_143022_name`.

Where a component is unknown, the prefix writes zeros: `2001-00-00_000000_name`
for a photograph the tool can place in a year and no closer.

This looks odd and it is meant to. It sorts correctly, it puts everything from
one year together, and **it can never be mistaken for a date somebody knew**. A
filename prefix is a browsing affordance. `DateTimeOriginal` is a claim. The two
are allowed to disagree, and where they do, the filename is the one being
approximate on purpose.

The same logic applies one level up. A folder may be organised by year or by
year and month using the import stamp, because a folder is a browsing
affordance too. That value never reaches `DateTimeOriginal`. The
`year-month` scheme also never manufactures a month: an album that names only a
year files directly under the year rather than landing everything in January.

## Folder names outrank anything the tool can derive

Somebody typed the folder name about these specific photographs. Nobody typed
the import stamp.

So a source folder with a descriptive name keeps that name as the album,
whatever date the photographs carry — nested under the year when the name gives
one, and sitting beside the year folders when it does not. Only a folder whose
name says nothing (a tool-generated name, a bare sequence number, a placeholder)
gets replaced by a date-based filing folder.

That list of meaningless names is short, explicit, and never a heuristic,
because the two possible mistakes are not symmetric: wrongly calling a folder
meaningless discards something a person wrote and cannot be recovered from the
file, while wrongly calling one meaningful leaves a slightly odd album name.
Extend the list for your own archive with `FPX_NON_DESCRIPTIVE_ALBUMS`.

A file often sits in more than one folder — an event album and a bulk dump it
was also copied into. It is filed under the **most descriptive** one. Taking the
first-listed instead put 52 photographs of one holiday under a folder named
after a zip file, and because the album is also what resolves the date, cost them
the day-precise date their real album gave for free.

### Demoting a folder date you do not trust

`FPX_COARSE_ALBUMS` demotes a named album's folder date to just the year,
however day-precise the name looks. A folder named for a holiday resolves to a
calendar day, but may hold the whole season around it, and only the person who
made the folder knows which.

The setting is deliberately **one-way**: it can take a date claim away, never
add one. Adding one requires a person to type a specific day, which is what the
next section is for.

## The `album-dates.json` round trip

This is **the only route by which a defensible capture date enters the archive
from outside the files.** Somebody who was there is better evidence than a
folder name.

1. Run `convert` once, then `gallery` over the finished run.
2. The QA page lists every album holding an undated photograph — *any* undated
   file, not necessarily all of them, since an album where two files carry scan
   dates still needs the other forty dated — and offers a date box beside each.
3. Fill in the ones you know. The page renders the result as JSON for you to
   save as `album-dates.json`.
4. Run `convert` again. It reads the file back and writes those dates as
   `DateTimeOriginal`, recorded with `date_source: owner-supplied`.

An owner-supplied date ranks above the folder name and far above the import
stamp.

It must be a single day, `YYYY-MM-DD`. A month, a year, a season or a range is
**refused at parse time** — the whole file is rejected before anything is
converted, rather than being rounded to a first day. That refusal is the rule
this project already paid for once. If nobody can name a day, the correct output
is no tag at all, and leaving the box blank is a legitimate answer.

## Where to look afterwards

Every converted file records which of the sources its date came from —
folder-parsed, owner-supplied, or import-stamp-only — in the sidecar and in the
audit report, so the mapping can be reviewed or redone later without
re-converting anything.

The `check-dates` command reports how the import stamps compare against the
folder-name ground truth. It reports by default and only fails under
`--strict`; on the reference corpus the import stamp misses most dated albums,
which is *why* it is not trusted as a capture date. A failing strict gate there
is the expected state, not a regression — its value is in showing you whether
that state gets *worse*.
