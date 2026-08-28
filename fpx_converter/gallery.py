"""The QA gallery: one HTML page for reviewing a whole converted archive.

Two jobs, and the second is the one the project actually needs.

**Look at the run.** Every converted file as a thumbnail, filterable by album
and by audit status, so a person can see 687 photographs at once instead of
reading a JSON report. Failures and warnings come first.

**Date the albums.** `docs/DATES.md` is blunt that there is no capture date
anywhere in this corpus and that a folder naming a year or a season does not
date a photograph. That leaves most of the archive with no
`DateTimeOriginal` -- correctly, because nothing in the files knows one. But
the owner does. This page is where they look at an album and say "that was
the seventeenth", and what they type comes back out as `album-dates.json`,
which `convert` reads on the next run. A date typed by somebody who was there
is better evidence than any folder name, and until this page existed there was
no way to get it in.

The page is deliberately a **single self-contained file**. No server, no
build step, no external asset: thumbnails are inlined as data URIs. It has to
open by double-clicking it in five years' time, on a machine with none of this
installed.

**Thumbnails come from the embedded DIBs, not from the outputs.** They are
already in the source files, they are the size a gallery wants, and reading
them costs no decode. It also keeps the page honest about one thing: the DIB
was written by the camera software, so a thumbnail that disagrees with its
own output is visible here.
"""

from __future__ import annotations

import base64
import html
import io
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import album_dates as album_dates_mod
from . import thumbnail

REPORT_FILENAME = "index.html"
THUMB_MAX = (240, 240)
#: JPEG rather than PNG: a 687-thumbnail page of PNGs runs to tens of
#: megabytes, and at this size the artefacts are invisible. The page is for
#: judging framing, orientation and gross colour, never for judging detail.
THUMB_QUALITY = 72


@dataclass
class GalleryItem:
    """One converted photograph, as the page needs it."""

    store_name: str
    album: str
    status: str
    date_source: str
    date_original: str = ""
    sort_date: str = ""
    outputs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    transform_status: str = ""
    thumb_uri: str = ""

    @property
    def audit_class(self) -> str:
        """What a reviewer is looking for, in the order they care about it."""
        if self.errors or self.status == "failed":
            return "failed"
        if self.warnings:
            return "warning"
        if self.date_original:
            return "dated"
        return "undated"


def thumbnail_data_uri(fpx_path: Path) -> str:
    """The embedded DIB, shrunk and inlined. Empty string where unreadable.

    A file whose thumbnail cannot be read still belongs in the gallery -- more
    so than most, because something about it is unusual. Dropping it would
    hide exactly the file a reviewer should see.
    """
    try:
        image = thumbnail.extract_thumbnail(fpx_path)
    except Exception:  # noqa: BLE001
        return ""
    image = image.convert("RGB")
    image.thumbnail(THUMB_MAX)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=THUMB_QUALITY)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _sidecar_dates(sidecar_dir: Path, store_name: str) -> tuple[str, str]:
    """`(DateTimeOriginal, sort date)` from a sidecar, or blanks."""
    path = sidecar_dir / f"{store_name}.json"
    if not path.is_file():
        return "", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", ""
    stamps = (data.get("derived") or {}).get("timestamps") or {}
    return (
        str(stamps.get("datetime_original_exif") or ""),
        str(stamps.get("sort_datetime") or ""),
    )


def build_items(
    report: dict[str, Any],
    *,
    store_dir: Path,
    sidecar_dir: Path | None = None,
    thumbnails: bool = True,
) -> list[GalleryItem]:
    """Turn an `audit_report.json` into what the page renders."""
    items: list[GalleryItem] = []
    for record in report.get("files", []):
        store_name = record.get("store_name", "")
        # The report is the primary source: it is written by the run itself
        # and always present. Sidecars are optional -- `metadata` may never
        # have been run -- so a gallery that needed them showed a correctly
        # dated archive as entirely undated.
        original = str(record.get("date_original") or "")
        sort_date = ""
        if sidecar_dir:
            sidecar_original, sort_date = _sidecar_dates(sidecar_dir, store_name)
            original = original or sidecar_original
        item = GalleryItem(
            store_name=store_name,
            album=record.get("album") or "(no album)",
            status=record.get("status", ""),
            date_source=record.get("date_source", "none"),
            date_original=original,
            sort_date=sort_date,
            outputs=list(record.get("outputs", [])),
            errors=list(record.get("errors", [])),
            warnings=list(record.get("warnings", [])),
            transform_status=record.get("transform_status", ""),
        )
        if thumbnails:
            item.thumb_uri = thumbnail_data_uri(store_dir / store_name)
        items.append(item)
    return items


def group_by_album(items: list[GalleryItem]) -> dict[str, list[GalleryItem]]:
    groups: dict[str, list[GalleryItem]] = defaultdict(list)
    for item in items:
        groups[item.album].append(item)
    return dict(sorted(groups.items()))


def albums_needing_a_date(items: list[GalleryItem]) -> list[str]:
    """Albums holding at least one photograph with no capture date.

    Deliberately *any*, not *all*. An earlier version listed only albums where
    nothing was dated, on the reasoning that a per-file embedded scan time
    should not be overwritten by an album-wide answer. It had the effect of
    hiding the box entirely from an album of forty photographs the moment two
    of them happened to carry a scan time -- so the other thirty-eight could
    never be dated at all.

    A date supplied here does outrank the scan time; see
    `timestamps.resolve_file_timestamps`. Somebody who was there is better
    evidence about when a photograph was taken than a stamp recording when it
    was digitised.
    """
    by_album = group_by_album(items)
    return [
        album
        for album, group in by_album.items()
        if any(not item.date_original for item in group)
    ]


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def render_html(
    items: list[GalleryItem],
    *,
    report: dict[str, Any],
    existing_dates: album_dates_mod.AlbumDates | None = None,
) -> str:
    """The whole page, self-contained."""
    groups = group_by_album(items)
    needing = set(albums_needing_a_date(items))
    existing = existing_dates or album_dates_mod.AlbumDates()
    counts = report.get("counts", {})

    status_counts: dict[str, int] = defaultdict(int)
    for item in items:
        status_counts[item.audit_class] += 1

    parts: list[str] = [_HEAD]

    parts.append("<header><h1>Conversion review</h1><p class='meta'>")
    parts.append(
        f"{_esc(counts.get('converted', 0))} converted, "
        f"{_esc(counts.get('resumed', 0))} resumed, "
        f"<strong>{_esc(counts.get('failed', 0))} failed</strong> &middot; "
        f"{_esc(len(groups))} albums &middot; run {_esc(report.get('finished', ''))}"
    )
    parts.append("</p>")
    dupes = report.get("expected_pixel_identical_groups") or {}
    if dupes.get("count"):
        parts.append(
            f"<p class='note'>{_esc(dupes['files_involved'])} files in "
            f"{_esc(dupes['count'])} pixel-identical groups. "
            "These are expected, not faults: deduplication keys on the whole "
            "source file, so two files with identical pixels and different "
            "bytes are both kept deliberately.</p>"
        )
    parts.append("</header>")

    parts.append("<nav class='filters'><label>Album <select id='album-filter'>")
    parts.append("<option value=''>all albums</option>")
    for album in groups:
        parts.append(f"<option value='{_esc(album)}'>{_esc(album)}</option>")
    parts.append("</select></label> <label>Status <select id='status-filter'>")
    parts.append("<option value=''>everything</option>")
    for key, label in (
        ("failed", "failed"),
        ("warning", "warnings"),
        ("undated", "no capture date"),
        ("dated", "has a capture date"),
    ):
        parts.append(
            f"<option value='{key}'>{label} ({status_counts.get(key, 0)})</option>"
        )
    parts.append("</select></label>")
    parts.append("<span id='shown' class='meta'></span></nav>")

    parts.append(_DATING_PANEL)

    for album, group in groups.items():
        undated = album in needing
        prefilled = existing.for_album(album)
        parts.append(f"<section class='album' data-album='{_esc(album)}'>")
        parts.append(
            f"<h2>{_esc(album)} <span class='meta'>{len(group)} photos</span></h2>"
        )
        if undated:
            value = prefilled.isoformat() if prefilled else ""
            missing = sum(1 for item in group if not item.date_original)
            parts.append(
                "<div class='date-entry'>"
                f"<p>{missing} of {len(group)} photographs here carry no capture "
                "date. If you know the day these were taken, type it &mdash; a "
                "single day, or leave it blank. A month or a year cannot be "
                "written as a capture date, so a partial answer is worse than "
                "none. What you type applies to the whole album.</p>"
                f"<label>Date <input type='date' class='album-date' "
                f"data-album='{_esc(album)}' value='{_esc(value)}'></label> "
                f"<label>Note <input type='text' class='album-note' "
                f"data-album='{_esc(album)}' placeholder='optional, for your own records' "
                f"value='{_esc(existing.note_for(album))}'></label>"
                "</div>"
            )
        parts.append("<div class='grid'>")
        for item in group:
            parts.append(_render_item(item))
        parts.append("</div></section>")

    parts.append(_SCRIPT)
    parts.append("</body></html>")
    return "\n".join(parts)


def _render_item(item: GalleryItem) -> str:
    detail: list[str] = []
    if item.date_original:
        detail.append(
            f"{_esc(item.date_original)} "
            f"<span class='meta'>({_esc(item.date_source)})</span>"
        )
    elif item.sort_date:
        detail.append(
            f"<span class='meta'>sorts at {_esc(item.sort_date[:10])}, no claim</span>"
        )
    else:
        detail.append("<span class='meta'>undated</span>")
    for error in item.errors:
        detail.append(f"<span class='err'>{_esc(error)}</span>")
    for warning in item.warnings:
        detail.append(f"<span class='warn'>{_esc(warning)}</span>")

    img = (
        f"<img loading='lazy' src='{item.thumb_uri}' alt=''>"
        if item.thumb_uri
        else "<div class='nothumb'>no thumbnail</div>"
    )
    return (
        f"<figure class='card' data-status='{item.audit_class}'>{img}"
        f"<figcaption><code>{_esc(item.store_name)}</code>"
        f"<br>{'<br>'.join(detail)}</figcaption></figure>"
    )


def write_gallery(html_text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")


_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fpx-converter review</title>
<style>
:root { color-scheme: light dark; --line: #8884; }
body { font: 15px/1.5 system-ui, sans-serif; margin: 0; padding: 1.5rem; }
header h1 { margin: 0 0 .25rem; font-size: 1.4rem; }
.meta { opacity: .7; font-size: .85em; }
.note { border-left: 3px solid var(--line); padding-left: .75rem; max-width: 60ch; }
nav.filters { position: sticky; top: 0; z-index: 5; padding: .6rem 0;
  background: Canvas; border-bottom: 1px solid var(--line); display: flex;
  gap: 1rem; align-items: center; flex-wrap: wrap; }
section.album { margin: 1.5rem 0; }
section.album h2 { font-size: 1.05rem; border-bottom: 1px solid var(--line);
  padding-bottom: .3rem; }
.grid { display: grid; gap: .75rem;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }
figure.card { margin: 0; border: 1px solid var(--line); border-radius: 6px;
  padding: .4rem; overflow: hidden; }
figure.card img { width: 100%; height: auto; display: block; border-radius: 3px; }
.nothumb { aspect-ratio: 4/3; display: grid; place-items: center; opacity: .5;
  border: 1px dashed var(--line); border-radius: 3px; }
figcaption { font-size: .78em; margin-top: .35rem; word-break: break-all; }
figure.card[data-status="failed"] { outline: 2px solid #d33; }
figure.card[data-status="warning"] { outline: 2px solid #d90; }
.err { color: #d33; } .warn { color: #a70; }
.date-entry { border: 1px dashed var(--line); border-radius: 6px;
  padding: .6rem .8rem; margin: .5rem 0; max-width: 70ch; }
.date-entry p { margin: 0 0 .5rem; font-size: .88em; }
.date-entry label { margin-right: 1rem; }
#dating { border: 1px solid var(--line); border-radius: 6px; padding: .8rem;
  margin: 1rem 0; }
#dating textarea { width: 100%; min-height: 7rem; font: 12px/1.4 ui-monospace,
  monospace; }
button { font: inherit; padding: .3rem .7rem; }
[hidden] { display: none !important; }
</style></head><body>"""

_DATING_PANEL = """<section id="dating">
<h2>Album dates you have supplied</h2>
<p class="meta">Save this as <code>album-dates.json</code> beside the manifest and
re-run <code>convert</code>. A date typed here is written to
<code>DateTimeOriginal</code> and recorded as <code>owner-supplied</code>, so an
audit can always tell what a person asserted from what the file said. Nothing is
sent anywhere; this page has no network access.</p>
<button id="refresh">Rebuild from the boxes above</button>
<textarea id="dates-json" readonly></textarea>
</section>"""

_SCRIPT = """<script>
(function () {
  const albumFilter = document.getElementById('album-filter');
  const statusFilter = document.getElementById('status-filter');
  const shown = document.getElementById('shown');

  function apply() {
    const album = albumFilter.value, status = statusFilter.value;
    let visible = 0;
    document.querySelectorAll('section.album').forEach(section => {
      const matchesAlbum = !album || section.dataset.album === album;
      let anyCard = false;
      section.querySelectorAll('figure.card').forEach(card => {
        const ok = matchesAlbum && (!status || card.dataset.status === status);
        card.hidden = !ok;
        if (ok) { anyCard = true; visible++; }
      });
      section.hidden = !anyCard;
    });
    shown.textContent = visible + ' shown';
  }

  function rebuild() {
    const dates = {}, notes = {};
    document.querySelectorAll('input.album-date').forEach(input => {
      if (input.value) { dates[input.dataset.album.toLowerCase()] = input.value; }
    });
    document.querySelectorAll('input.album-note').forEach(input => {
      const key = input.dataset.album.toLowerCase();
      if (input.value.trim() && dates[key]) { notes[key] = input.value.trim(); }
    });
    document.getElementById('dates-json').value =
      JSON.stringify({'album dates': dates, notes: notes}, null, 2);
  }

  albumFilter.addEventListener('change', apply);
  statusFilter.addEventListener('change', apply);
  document.getElementById('refresh').addEventListener('click', rebuild);
  document.addEventListener('change', e => {
    if (e.target.matches('input.album-date, input.album-note')) rebuild();
  });
  apply();
  rebuild();
})();
</script>"""
