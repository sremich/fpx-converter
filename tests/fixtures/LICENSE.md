# Licence and provenance of the test fixtures

**Nothing in this directory is covered by the repository's Apache-2.0
licence.** That licence covers the software. These are photographs, they were
not made by this project, and two different sets of terms apply to them. If
you fork this repository, redistribute it, or vendor it into something else,
the `.fpx` files here do **not** come with the permissions that `LICENSE` at
the repository root grants for the code.

There are 37 files, in two groups, and the split is by who made the
photograph rather than by what it is used to test.

## Group 1 — Origin not established (16 files)

Sixteen files whose authorship this project cannot determine. They are
redistributed here **unmodified**, as historical test data for a file format
that is no longer produced by anything.

They were found inside the owner's archive in folders named `Sample`,
`Sample/Burst` and `Sample/TimeLapse`, and were long assumed to be sample
images bundled with Kodak's Picture Easy software. That assumption does not
survive examination and **this project no longer makes it**. Their measured
properties point the other way: nine of them are 1152×864 and two are
640×480, which are exactly the full and reduced resolutions of the KODAK
DC200/DC210 that produced Group 2; nine consecutive frames of one sky taken
twenty seconds apart is what a camera transfer looks like, not a curated
sample set; and `mask` and `squirrel` are at sizes matching no Photo CD level
and no camera mode. Against that, none of them records a camera identity, all
carry 1998 timestamps two years before the rest of the archive, and the owner
does not recognise any of them.

The honest position is that we do not know. Some may be bundled sample
imagery; some may be photographs that reached the archive by a route nobody
now remembers.

```
Clouds01.fpx      clouds05.fpx      harbor.fpx        squirrel.fpx
clouds02.fpx      clouds06.fpx      mask.fpx          starfish.fpx
clouds03.fpx      clouds07.fpx      P0000016.FPX      storm-fence.fpx
clouds04.fpx      clouds08.fpx                        train-platform.fpx
                  clouds09.fpx
```

**Origin: unknown. No authorship is asserted over these files by anyone.**

**Terms: no licence is claimed over these files by this project.** They may
not be this project's to license, so none is offered — not Apache-2.0, not
any other. They are retained as unmodified historical test data. If you hold
rights in any of them and want them removed, please open an issue at
<https://github.com/sremich/fpx-converter/issues> and they will be removed
without argument.

Three of them (`starfish`, `storm-fence`, and in part `harbor`) carry a 1998
film-scanner pedigree in their metadata — Kodak Photo CD scanning equipment,
at Photo CD Base and 4Base dimensions in PhotoYCC. The owner of this
repository has never had film scanned to Photo CD and has never owned a film
scanner. **The 1998 scanner stamps in this directory are not his and must not
be attributed to him.**

`P0000016.FPX` shows three distant, unidentifiable figures on a public
railway platform. It is kept deliberately — see the note on the screening
standard below.

## Group 2 — The repository owner's own photographs (21 files)

Photographs taken by Stevie Remich between 2001 and 2002 on a KODAK DC200 or
DC210, all 1152×864, all NIF_RGB. They are the corpus this tool was written
for, and they are here because a tool that reads a 25-year-old camera format
cannot be tested honestly against anything but real files from that camera.

```
clay01.fpx           conservatory05.fpx   dragonfly01.fpx   foliage04.fpx
clay02.fpx           conservatory06.fpx   dragonfly02.fpx   giraffe.fpx
clay03.fpx           conservatory07.fpx   foliage01.fpx     pond-bed01.fpx
clay04.fpx           conservatory08.fpx   foliage02.fpx     pond-bed02.fpx
conservatory01.fpx                        foliage03.fpx
conservatory02.fpx
conservatory03.fpx
conservatory04.fpx
```

**Copyright 2026 Stevie Remich. All rights reserved.**

**Terms: test use only.** They are included so that this project's tests can
run, and so that anyone who forks it can run them too. That is the whole of
the permission granted: you may keep them in a fork of this repository and
use them as inputs to this project's test suite. No other use is licensed —
not publication, not redistribution as images, not inclusion in a dataset,
not training, and not any commercial use. They are explicitly **not** under
the Apache-2.0 licence that covers the code.

Every one of the 21 was screened by eye and contains no people at all.

## The screening standard, stated exactly

The rule that governs this directory is about **identifiability**, not about
whether any human shape appears anywhere in the frame. Stating it precisely,
because a looser wording was previously in this repository and the fixtures
did not match it:

- **No file may contain an identifiable person.** A face, a distinguishing
  feature, a name, or anything that lets a viewer work out who someone is.
- **No file may contain anyone connected to the repository owner**,
  identifiable or not.
- A **distant, unidentifiable figure in a public place** does not
  disqualify a file. `P0000016.FPX` is the only fixture in this category:
  three people at a distance on a railway platform, faces not resolvable at
  the file's 640×480.

That standard has been enforced against real files. `feeder01.fpx`,
`feeder02.fpx` and `feeder-crop.fpx` were committed, then found on
re-screening to contain a person standing in the background of a butterfly
house — close enough to read as an individual — and were removed on
2026-08-27, before this repository was made public. Removing `feeder-crop.fpx`
cost this project its only committed cover for the crop path, and it went
anyway: **the rule outranks the test coverage.**

If you believe you can identify a person in any file here, please open an
issue at <https://github.com/sremich/fpx-converter/issues> and it will be
removed.

## If you are removing files from this directory

Read the coverage section of [`README.md`](README.md) first. The two groups
are not interchangeable: deleting the Kodak files would take both PhotoYCC
files, five of the six declared image sizes, the only uncompressed-tile file
and the only single-colour-fill tiles with them, and the test suite would
still pass while covering far less than it claims to.

There is exactly one reason that outranks the coverage, and it has been
exercised: a file containing a person goes, whatever it was testing. When it
happens, the tests that covered it are inverted or skipped with a reason —
never quietly deleted — and README's "What they do *not* cover" section is
updated to say what the repository has stopped testing.
