"""Build private, self-contained HTML digests from worklog checkpoints."""

from __future__ import annotations

import datetime as dt
import html
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .paths import ensure_private_dir, reports_dir
from .report import _plain_text
from .view import Entry, _parse_timestamp


CHECKPOINT_HEADER = re.compile(r"^## (\S+) — (.+)$", re.MULTILINE)
SECTION_HEADER = re.compile(r"^### .+$", re.MULTILINE)
CHECKED_ITEM = re.compile(r"^- \[[xX]\] (.+)$", re.MULTILINE)
UNCHECKED_ITEM = re.compile(r"^- \[ \] (.+)$", re.MULTILINE)
BULLET_ITEM = re.compile(r"^- (?!\[[xX ]\] )(.+)$", re.MULTILINE)
PLAIN_URL = re.compile(r"^https?://[^\s]+$")


@dataclass(frozen=True)
class CheckpointDetails:
    """The human-written sections attached to one checkpoint."""

    done: tuple[str, ...]
    evidence: tuple[str, ...]
    remaining: tuple[str, ...]


def digest_window(
    period: str, *, day: dt.date | None = None
) -> tuple[dt.datetime, dt.datetime]:
    """Return the inclusive local-time window for a daily or weekly digest."""
    reference = day if day is not None else dt.datetime.now().astimezone().date()
    if period == "daily":
        start_day = reference
        next_day = reference + dt.timedelta(days=1)
    elif period == "weekly":
        start_day = reference - dt.timedelta(days=reference.weekday())
        next_day = start_day + dt.timedelta(days=7)
    else:
        raise ValueError("period must be 'daily' or 'weekly'")

    since = dt.datetime.combine(start_day, dt.time.min).astimezone()
    next_start = dt.datetime.combine(next_day, dt.time.min).astimezone()
    return since, next_start - dt.timedelta(microseconds=1)


def _checkpoint_block(text: str, entry: Entry) -> str | None:
    checkpoints = list(CHECKPOINT_HEADER.finditer(text))
    for index, checkpoint in enumerate(checkpoints):
        if checkpoint.group(1) != entry.timestamp:
            continue
        if checkpoint.group(2).strip() != entry.title:
            continue
        end = (
            checkpoints[index + 1].start()
            if index + 1 < len(checkpoints)
            else len(text)
        )
        return text[checkpoint.end() : end]
    return None


def _section(block: str, heading: str) -> str:
    marker = re.search(rf"^### {re.escape(heading)}\s*$", block, re.MULTILINE)
    if marker is None:
        return ""
    following = block[marker.end() :]
    next_section = SECTION_HEADER.search(following)
    return following[: next_section.start()] if next_section is not None else following


def _checkpoint_details(
    entry: Entry, cache: dict[str, str | None]
) -> CheckpointDetails:
    if entry.path not in cache:
        try:
            cache[entry.path] = Path(entry.path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            cache[entry.path] = None
    text = cache[entry.path]
    if text is None:
        return CheckpointDetails((), (), ())
    block = _checkpoint_block(text, entry)
    if block is None:
        return CheckpointDetails((), (), ())

    done = tuple(
        _plain_text(match.group(1))
        for match in CHECKED_ITEM.finditer(_section(block, "Accomplished"))
        if _plain_text(match.group(1))
    )
    evidence = tuple(
        _plain_text(match.group(1))
        for match in BULLET_ITEM.finditer(_section(block, "Evidence"))
        if _plain_text(match.group(1))
    )
    remaining = tuple(
        _plain_text(match.group(1))
        for match in UNCHECKED_ITEM.finditer(_section(block, "Remaining"))
        if _plain_text(match.group(1))
    )
    return CheckpointDetails(done, evidence, remaining)


def _date_label(period: str, since: dt.datetime, until: dt.datetime) -> str:
    start = since.astimezone().date()
    end = until.astimezone().date()
    if period == "daily":
        return f"{start.strftime('%A')}, {start.strftime('%B')} {start.day}, {start.year}"
    if start.year == end.year and start.month == end.month:
        return f"Week of {start.strftime('%B')} {start.day}–{end.day}, {start.year}"
    if start.year == end.year:
        return (
            f"Week of {start.strftime('%B')} {start.day}–"
            f"{end.strftime('%B')} {end.day}, {start.year}"
        )
    return (
        f"Week of {start.strftime('%B')} {start.day}, {start.year}–"
        f"{end.strftime('%B')} {end.day}, {end.year}"
    )


def _entry_time(entry: Entry) -> str:
    return _parse_timestamp(entry.timestamp).astimezone().strftime("%H:%M")


def _safe(value: str) -> str:
    return html.escape(_plain_text(value), quote=True)


def _evidence_item(value: str) -> str:
    safe_value = _safe(value)
    if PLAIN_URL.fullmatch(value.strip()):
        return (
            f'<a href="{html.escape(value.strip(), quote=True)}" '
            f'rel="noreferrer">{safe_value}</a>'
        )
    return safe_value


def _detail_block(details: CheckpointDetails) -> str:
    if not details.done and not details.evidence:
        return ""
    parts = ["<details><summary>Outcome &amp; evidence</summary>"]
    if details.done:
        parts.append('<div class="detail-label">Accomplished</div><ul>')
        parts.extend(f"<li>{_safe(item)}</li>" for item in details.done)
        parts.append("</ul>")
    if details.evidence:
        parts.append('<div class="detail-label">Evidence</div><ul>')
        parts.extend(f"<li>{_evidence_item(item)}</li>" for item in details.evidence)
        parts.append("</ul>")
    parts.append("</details>")
    return "".join(parts)


def build_digest(
    entries: Iterable[Entry],
    *,
    period: str,
    since: dt.datetime,
    until: dt.datetime,
    generated_at: dt.datetime | None = None,
) -> str:
    """Return one self-contained HTML digest with local project navigation."""
    if period not in {"daily", "weekly"}:
        raise ValueError("period must be 'daily' or 'weekly'")
    selected = sorted(
        entries, key=lambda entry: _parse_timestamp(entry.timestamp), reverse=True
    )
    projects = {entry.project for entry in selected}
    agents = {entry.agent for entry in selected}
    completed = sum(entry.status == "completed" for entry in selected)
    partial = len(selected) - completed
    label = _date_label(period, since, until)
    generated = generated_at or dt.datetime.now().astimezone()

    cache: dict[str, str | None] = {}
    details = {entry: _checkpoint_details(entry, cache) for entry in selected}
    remaining: list[tuple[str, str]] = []
    seen_remaining: set[tuple[str, str]] = set()
    for entry in selected:
        for item in details[entry].remaining:
            key = (entry.project.casefold(), item.casefold())
            if key in seen_remaining:
                continue
            seen_remaining.add(key)
            remaining.append((entry.project, item))

    grouped: dict[str, list[Entry]] = defaultdict(list)
    for entry in selected:
        grouped[entry.project].append(entry)
    ordered_projects = sorted(
        grouped.items(),
        key=lambda item: (
            -len(item[1]),
            -_parse_timestamp(item[1][0].timestamp).timestamp(),
            item[0].casefold(),
        ),
    )

    remaining_by_project: dict[str, list[str]] = defaultdict(list)
    for project, item in remaining:
        remaining_by_project[project].append(item)

    picker_options: list[str] = []
    project_cards: list[str] = []
    project_views: list[str] = []
    for project_index, (project, project_entries) in enumerate(ordered_projects):
        project_id = f"project-{project_index}"
        project_open = remaining_by_project[project]
        picker_options.append(
            f'<option value="{project_id}">{_safe(project)} '
            f"({len(project_entries)})</option>"
        )

        if project_index < 12:
            preview_titles = "".join(
                f"<span>{_safe(entry.title)}</span>" for entry in project_entries[:2]
            )
            project_cards.append(
                '<button class="project-card" type="button" '
                f'data-select-project="{project_id}">'
                '<span class="project-card-top">'
                f'<strong>{_safe(project)}</strong><span aria-hidden="true">→</span>'
                "</span>"
                f'<span class="project-count">{len(project_entries)} checkpoint'
                f'{"" if len(project_entries) == 1 else "s"} · '
                f'{len(project_open)} open</span>'
                f'<span class="project-preview">{preview_titles}</span>'
                '<span class="project-link">View project</span>'
                "</button>"
            )

        checkpoints: list[str] = []
        for entry in project_entries:
            state = "complete" if entry.status == "completed" else "partial"
            checkpoints.append(
                '<article class="checkpoint">'
                '<div class="checkpoint-rail">'
                f'<span class="dot {state}"></span>'
                f'<time>{_entry_time(entry)}</time>'
                "</div>"
                '<div class="checkpoint-body">'
                f'<div class="checkpoint-meta"><span>{_safe(entry.agent)}</span>'
                f'<span>{_safe(entry.status)}</span></div>'
                f"<h3>{_safe(entry.title)}</h3>"
                f"{_detail_block(details[entry])}"
                "</div></article>"
            )
        if project_open:
            project_open_items = "".join(
                f"<li><span>{_safe(item)}</span></li>" for item in project_open
            )
        else:
            project_open_items = '<li class="empty">Nothing left open.</li>'

        project_views.append(
            f'<section class="digest-view" id="{project_id}" '
            'data-digest-view hidden>'
            '<button class="back-button" type="button" '
            'data-select-project="overview">← All projects</button>'
            '<div class="project-layout">'
            '<section class="project-detail">'
            '<div class="project-heading">'
            f'<h2 tabindex="-1">{_safe(project)}</h2>'
            f'<span>{len(project_entries)} checkpoint'
            f'{"" if len(project_entries) == 1 else "s"}</span>'
            "</div>"
            f'{"".join(checkpoints)}'
            "</section>"
            '<aside><section class="open"><h2>Still open here</h2><ul>'
            f"{project_open_items}</ul></section></aside>"
            "</div></section>"
        )

    overview_remaining = remaining[:8]
    if overview_remaining:
        overview_open_items = "".join(
            f'<li><span>{_safe(item)}</span><small>{_safe(project)}</small></li>'
            for project, item in overview_remaining
        )
        if len(remaining) > len(overview_remaining):
            overview_open_items += (
                '<li class="more-open">+'
                f"{len(remaining) - len(overview_remaining)} more · select a project"
                "</li>"
            )
    else:
        overview_open_items = '<li class="empty">No remaining items were recorded.</li>'

    if project_cards:
        project_overflow = ""
        if len(ordered_projects) > len(project_cards):
            project_overflow = (
                '<p class="overview-more">+'
                f"{len(ordered_projects) - len(project_cards)} more projects. "
                "Use the selector above to jump directly to one.</p>"
            )
        overview_activity = (
            '<div class="overview-heading"><div><span class="section-kicker">Overview</span>'
            '<h2>Choose what you want to inspect.</h2></div>'
            '<p>Recent outcomes stay visible. Full timelines appear only when you '
            "select a project.</p></div>"
            f'<div class="overview-grid">{"".join(project_cards)}</div>'
            f"{project_overflow}"
        )
    else:
        overview_activity = (
            '<section class="empty-state"><p>No checkpoints were recorded in '
            "this window.</p></section>"
        )

    disabled_selector = " disabled" if not ordered_projects else ""

    period_name = "Daily" if period == "daily" else "Weekly"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{period_name} Worklog — {_safe(label)}</title>
  <style>
    :root {{ --ink:#141414; --paper:#f3f0e8; --card:#fffefa; --muted:#686b73;
      --line:#d9d5ca; --accent:#f06a3c; --accent-soft:#ffe2d6; --good:#18794e; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:var(--paper);
      font:15px/1.55 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    .shell {{ max-width:1040px; margin:0 auto; padding:48px 28px 72px; }}
    .masthead {{ background:var(--ink); color:white; border-radius:4px; padding:38px 42px;
      position:relative; overflow:hidden; }}
    .masthead::after {{ content:""; position:absolute; width:220px; height:220px;
      right:-80px; top:-120px; border:44px solid var(--accent); border-radius:50%; opacity:.9; }}
    .masthead > * {{ position:relative; z-index:1; }}
    .eyebrow {{ color:#ff9a76; font-size:12px; font-weight:800; letter-spacing:.16em;
      text-transform:uppercase; }}
    h1 {{ max-width:720px; margin:12px 0 4px; font:700 42px/1.08 ui-serif,Georgia,serif;
      letter-spacing:-.025em; }}
    .date {{ margin:0; color:#c8c8c8; font-size:16px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:1px; margin:20px 0 34px;
      background:var(--line); border:1px solid var(--line); }}
    .metric {{ background:var(--card); padding:19px 20px; }}
    .metric strong {{ display:block; font:700 28px/1 ui-serif,Georgia,serif; }}
    .metric span {{ color:var(--muted); font-size:12px; text-transform:uppercase;
      letter-spacing:.08em; }}
    .controls {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(280px,420px);
      align-items:end; gap:24px; padding:22px 24px; margin-bottom:24px; background:var(--card);
      border:1px solid var(--line); }}
    .control-kicker,.section-kicker {{ display:block; margin-bottom:3px; color:var(--accent);
      font-size:10px; font-weight:800; letter-spacing:.13em; text-transform:uppercase; }}
    .controls label {{ display:block; font:700 20px/1.2 ui-serif,Georgia,serif; }}
    .controls p {{ margin:5px 0 0; color:var(--muted); font-size:12px; }}
    select {{ width:100%; min-height:46px; padding:10px 42px 10px 13px; color:var(--ink);
      background:var(--paper); border:1px solid #aaa59a; border-radius:0;
      font:600 14px/1.2 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    select:focus-visible,.project-card:focus-visible,.back-button:focus-visible {{ outline:3px solid
      var(--accent-soft); outline-offset:2px; }}
    .digest-view[hidden] {{ display:none !important; }}
    .overview-layout,.project-layout {{ display:grid;
      grid-template-columns:minmax(0,2fr) minmax(250px,1fr); gap:28px; }}
    .overview-heading {{ display:flex; align-items:end; justify-content:space-between; gap:24px;
      margin-bottom:15px; }}
    .overview-heading h2 {{ margin:0; font:700 24px/1.15 ui-serif,Georgia,serif; }}
    .overview-heading p {{ max-width:330px; margin:0; color:var(--muted); font-size:13px; }}
    .overview-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .project-card {{ appearance:none; min-width:0; padding:18px; text-align:left; color:var(--ink);
      background:var(--card); border:1px solid var(--line); border-top:3px solid var(--ink);
      border-radius:0; cursor:pointer; font:inherit; transition:transform .12s ease,border-color .12s ease; }}
    .project-card:hover {{ transform:translateY(-2px); border-color:var(--accent); }}
    .project-card-top {{ display:flex; align-items:start; justify-content:space-between; gap:10px; }}
    .project-card-top strong {{ overflow-wrap:anywhere; font:700 17px/1.25 ui-serif,Georgia,serif; }}
    .project-card-top > span {{ color:var(--accent); font-size:20px; }}
    .project-count {{ display:block; margin:5px 0 13px; color:var(--muted); font-size:11px;
      font-weight:700; letter-spacing:.04em; text-transform:uppercase; }}
    .project-preview {{ display:block; min-height:43px; color:#3f4146; font-size:12px; }}
    .project-preview span {{ display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .project-preview span + span {{ margin-top:3px; color:var(--muted); }}
    .project-link {{ display:block; margin-top:14px; color:#b8431d; font-size:11px; font-weight:800;
      letter-spacing:.06em; text-transform:uppercase; }}
    .overview-more {{ margin:14px 0 0; padding:12px 14px; color:var(--muted);
      background:#e9e5dc; font-size:12px; }}
    .back-button {{ appearance:none; margin:0 0 14px; padding:0; color:#9b3819; background:none;
      border:0; cursor:pointer; font:800 12px/1.3 ui-sans-serif,-apple-system,BlinkMacSystemFont,
      "Segoe UI",sans-serif; letter-spacing:.04em; text-transform:uppercase; }}
    .project-detail {{ background:var(--card); border:1px solid var(--line); }}
    .project-heading {{ display:flex; align-items:baseline; justify-content:space-between;
      padding:19px 22px; border-bottom:1px solid var(--line); }}
    .project-heading h2 {{ margin:0; font:700 20px/1.2 ui-serif,Georgia,serif; }}
    .project-heading h2:focus {{ outline:none; }}
    .project-heading span {{ color:var(--muted); font-size:12px; }}
    .checkpoint {{ display:grid; grid-template-columns:58px 1fr; padding:20px 22px 21px 0;
      border-bottom:1px solid #ebe8e0; }}
    .checkpoint:last-child {{ border-bottom:0; }}
    .checkpoint-rail {{ display:flex; flex-direction:column; align-items:center; gap:7px;
      color:var(--muted); font:11px/1 ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .dot {{ width:10px; height:10px; border-radius:50%; background:var(--accent); }}
    .dot.complete {{ background:var(--good); }}
    .checkpoint-meta {{ display:flex; gap:8px; margin-bottom:6px; }}
    .checkpoint-meta span {{ padding:2px 7px; background:#efede6; color:var(--muted);
      font-size:10px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }}
    .checkpoint h3 {{ margin:0; font-size:16px; line-height:1.35; }}
    details {{ margin-top:12px; color:var(--muted); font-size:13px; }}
    summary {{ cursor:pointer; color:var(--ink); font-weight:700; }}
    details ul {{ margin:7px 0 10px; padding-left:20px; }}
    .detail-label {{ margin-top:9px; color:var(--muted); font-size:10px; font-weight:800;
      letter-spacing:.08em; text-transform:uppercase; }}
    a {{ color:#b8431d; text-underline-offset:2px; }}
    aside {{ align-self:start; position:sticky; top:20px; }}
    .open {{ background:var(--ink); color:white; padding:24px; }}
    .open h2 {{ margin:0 0 15px; font:700 20px/1.2 ui-serif,Georgia,serif; }}
    .open ul {{ margin:0; padding:0; list-style:none; }}
    .open li {{ padding:12px 0; border-top:1px solid #3a3a3a; }}
    .open li:first-child {{ border-top:0; }}
    .open small {{ display:block; margin-top:3px; color:#ff9a76; }}
    .open .empty,.open .more-open {{ color:#b9b9b9; }}
    .empty-state {{ border:1px dashed var(--line); background:var(--card); padding:46px;
      text-align:center; color:var(--muted); }}
    footer {{ margin-top:34px; padding-top:17px; border-top:1px solid var(--line);
      display:flex; justify-content:space-between; color:var(--muted); font-size:11px; }}
    @media (max-width:760px) {{ .shell{{padding:20px 14px 46px}} .masthead{{padding:30px 24px}}
      .masthead::after{{right:-132px;top:-112px}} h1{{font-size:32px}}
      .metrics{{grid-template-columns:repeat(2,1fr)}}
      .controls{{grid-template-columns:1fr;gap:14px}} .overview-layout,.project-layout{{grid-template-columns:1fr}}
      .overview-heading{{display:block}} .overview-heading p{{margin-top:7px}} .overview-grid{{grid-template-columns:1fr}}
      aside{{position:static}} footer{{display:block}} footer span{{display:block}} footer span + span{{margin-top:4px}} }}
    @media print {{ body{{background:white}} .shell{{max-width:none;padding:0}}
      .masthead{{break-inside:avoid}} .controls,.back-button{{display:none}} aside{{position:static}}
      details{{display:none}} }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="masthead">
      <div class="eyebrow">{period_name} worklog</div>
      <h1>What the agents actually got done.</h1>
      <p class="date">{_safe(label)}</p>
    </header>
    <section class="metrics" aria-label="Digest summary">
      <div class="metric"><strong>{len(selected)}</strong><span>checkpoints</span></div>
      <div class="metric"><strong>{len(projects)}</strong><span>projects</span></div>
      <div class="metric"><strong>{len(agents)}</strong><span>agents</span></div>
      <div class="metric"><strong>{completed}/{partial}</strong><span>done / partial</span></div>
    </section>
    <section class="controls" aria-labelledby="project-picker-label">
      <div><span class="control-kicker">Focus the digest</span>
        <label id="project-picker-label" for="project-picker">Choose a project</label>
        <p>Showing <strong id="current-view-label">All projects overview</strong></p>
      </div>
      <select id="project-picker"{disabled_selector}>
        <option value="overview">All projects overview</option>
        {"".join(picker_options)}
      </select>
    </section>
    <section class="digest-view" id="overview" data-digest-view>
      <div class="overview-layout">
        <div>{overview_activity}</div>
        <aside><section class="open"><h2>Still open</h2><ul>{overview_open_items}</ul></section></aside>
      </div>
    </section>
    {"".join(project_views)}
    <footer>
      <span>Generated by Worklog · private, local, evidence-based</span>
      <span>{generated.strftime('%Y-%m-%d %H:%M %Z')}</span>
    </footer>
  </main>
  <script>
    (() => {{
      const picker = document.getElementById("project-picker");
      const currentLabel = document.getElementById("current-view-label");
      const views = Array.from(document.querySelectorAll("[data-digest-view]"));

      function showView(requestedId, moveFocus) {{
        const requested = document.getElementById(requestedId);
        const selected = requested && requested.hasAttribute("data-digest-view")
          ? requested : document.getElementById("overview");
        views.forEach((view) => {{ view.hidden = view !== selected; }});
        picker.value = selected.id;
        const option = picker.options[picker.selectedIndex];
        currentLabel.textContent = option ? option.textContent : "All projects overview";
        if (moveFocus && selected.id !== "overview") {{
          const heading = selected.querySelector("h2");
          if (heading) heading.focus();
        }}
        try {{
          const hash = selected.id === "overview" ? "" : `#${{selected.id}}`;
          history.replaceState(null, "", `${{location.pathname}}${{location.search}}${{hash}}`);
        }} catch (error) {{
          // Navigation still works when a browser restricts history on local files.
        }}
      }}

      picker.addEventListener("change", () => showView(picker.value, true));
      document.querySelectorAll("[data-select-project]").forEach((button) => {{
        button.addEventListener("click", () => showView(button.dataset.selectProject, true));
      }});
      showView(location.hash.slice(1) || "overview", false);
    }})();
  </script>
</body>
</html>
"""


def write_digest(text: str, *, period: str, day: dt.date) -> Path:
    """Atomically write one digest with private filesystem permissions."""
    if period == "daily":
        name = f"daily-{day.isoformat()}.html"
    elif period == "weekly":
        iso_year, iso_week, _ = day.isocalendar()
        name = f"weekly-{iso_year}-W{iso_week:02d}.html"
    else:
        raise ValueError("period must be 'daily' or 'weekly'")

    directory = ensure_private_dir(reports_dir() / "digests")
    path = directory / name
    descriptor, temporary_name = tempfile.mkstemp(prefix=".worklog-digest-", dir=directory)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as digest_file:
            digest_file.write(text)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)
    return path
