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
from typing import Callable, Iterable

from .paths import ensure_private_dir, reports_dir
from .report import _plain_text
from .view import Entry, _parse_timestamp


CHECKPOINT_HEADER = re.compile(r"^## (\S+) — (.+)$", re.MULTILINE)
SECTION_HEADER = re.compile(r"^### .+$", re.MULTILINE)
CHECKED_ITEM = re.compile(r"^- \[[xX]\] (.+)$", re.MULTILINE)
UNCHECKED_ITEM = re.compile(r"^- \[ \] (.+)$", re.MULTILINE)
BULLET_ITEM = re.compile(r"^- (?!\[[xX ]\] )(.+)$", re.MULTILINE)
MACHINE_ITEM = re.compile(r"^- \*\*Machine:\*\*\s+(.+)$", re.MULTILINE)
PLAIN_URL = re.compile(r"^https?://[^\s]+$")


@dataclass(frozen=True)
class CheckpointDetails:
    """The human-written sections attached to one checkpoint."""

    done: tuple[str, ...]
    evidence: tuple[str, ...]
    remaining: tuple[str, ...]
    machine: str | None


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
        return CheckpointDetails((), (), (), None)
    block = _checkpoint_block(text, entry)
    if block is None:
        return CheckpointDetails((), (), (), None)

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
    machine_match = MACHINE_ITEM.search(block)
    machine = None
    if machine_match is not None:
        machine = _plain_text(machine_match.group(1))
        if len(machine) >= 2 and machine.startswith("`") and machine.endswith("`"):
            machine = machine[1:-1].strip()
        if not machine:
            machine = None
    return CheckpointDetails(done, evidence, remaining, machine)


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
    """Return one self-contained HTML digest with local multidimensional navigation."""
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
    computers = {details[entry].machine or "Unknown computer" for entry in selected}
    remaining: list[tuple[str, str]] = []
    seen_remaining: set[tuple[str, str]] = set()
    for entry in selected:
        for item in details[entry].remaining:
            key = (entry.project.casefold(), item.casefold())
            if key in seen_remaining:
                continue
            seen_remaining.add(key)
            remaining.append((entry.project, item))

    def ordered_groups(
        key_for_entry: Callable[[Entry], str],
    ) -> list[tuple[str, list[Entry]]]:
        grouped: dict[str, list[Entry]] = defaultdict(list)
        for entry in selected:
            grouped[key_for_entry(entry)].append(entry)
        return sorted(
            grouped.items(),
            key=lambda item: (
                -len(item[1]),
                -_parse_timestamp(item[1][0].timestamp).timestamp(),
                item[0].casefold(),
            ),
        )

    def computer_for(entry: Entry) -> str:
        return details[entry].machine or "Unknown computer"

    def open_items_for(view_entries: list[Entry]) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for entry in view_entries:
            for item in details[entry].remaining:
                key = (entry.project.casefold(), item.casefold())
                if key in seen:
                    continue
                seen.add(key)
                items.append((entry.project, item))
        return items

    def checkpoint_markup(entry: Entry, dimension: str) -> str:
        state = "complete" if entry.status == "completed" else "partial"
        metadata: list[str] = []
        if dimension != "contributor":
            metadata.append(entry.agent)
        if dimension != "project":
            metadata.append(entry.project)
        if dimension != "computer":
            metadata.append(computer_for(entry))
        metadata.append(entry.status)
        meta_markup = "".join(f"<span>{_safe(item)}</span>" for item in metadata)
        return (
            '<article class="checkpoint">'
            '<div class="checkpoint-rail">'
            f'<span class="dot {state}"></span>'
            f'<time>{_entry_time(entry)}</time>'
            "</div>"
            '<div class="checkpoint-body">'
            f'<div class="checkpoint-meta">{meta_markup}</div>'
            f"<h3>{_safe(entry.title)}</h3>"
            f"{_detail_block(details[entry])}"
            "</div></article>"
        )

    ordered_projects = ordered_groups(lambda entry: entry.project)
    ordered_contributors = ordered_groups(lambda entry: entry.agent)
    ordered_computers = ordered_groups(computer_for)

    picker_groups: list[str] = []
    project_cards: list[str] = []
    focus_views: list[str] = []
    dimensions = (
        ("project", "Projects", "Project", ordered_projects),
        ("contributor", "Contributors", "Contributor", ordered_contributors),
        ("computer", "Computers", "Computer", ordered_computers),
    )
    for dimension, group_label, view_label, groups in dimensions:
        options: list[str] = []
        for group_index, (group_name, group_entries) in enumerate(groups):
            view_id = f"{dimension}-{group_index}"
            options.append(
                f'<option value="{view_id}">{_safe(group_name)} '
                f"({len(group_entries)})</option>"
            )

            view_open = open_items_for(group_entries)
            if dimension == "project" and group_index < 12:
                preview_titles = "".join(
                    f"<span>{_safe(entry.title)}</span>" for entry in group_entries[:2]
                )
                project_cards.append(
                    '<button class="project-card" type="button" '
                    f'data-select-view="{view_id}">'
                    '<span class="project-card-top">'
                    f'<strong>{_safe(group_name)}</strong><span aria-hidden="true">→</span>'
                    "</span>"
                    f'<span class="project-count">{len(group_entries)} checkpoint'
                    f'{"" if len(group_entries) == 1 else "s"} · '
                    f'{len(view_open)} open</span>'
                    f'<span class="project-preview">{preview_titles}</span>'
                    '<span class="project-link">View project</span>'
                    "</button>"
                )

            checkpoints = "".join(
                checkpoint_markup(entry, dimension) for entry in group_entries
            )
            if view_open:
                show_project = dimension != "project"
                view_open_items = "".join(
                    f'<li><span>{_safe(item)}</span>'
                    + (f"<small>{_safe(project)}</small>" if show_project else "")
                    + "</li>"
                    for project, item in view_open
                )
            else:
                view_open_items = '<li class="empty">Nothing left open.</li>'

            focus_views.append(
                f'<section class="digest-view" id="{view_id}" '
                'data-digest-view hidden>'
                '<button class="back-button" type="button" '
                'data-select-view="overview">← All work</button>'
                '<div class="project-layout">'
                '<section class="project-detail">'
                '<div class="project-heading"><div>'
                f'<span class="view-kind">{view_label}</span>'
                f'<h2 tabindex="-1">{_safe(group_name)}</h2></div>'
                f'<span>{len(group_entries)} checkpoint'
                f'{"" if len(group_entries) == 1 else "s"}</span>'
                "</div>"
                f"{checkpoints}"
                "</section>"
                '<aside><section class="open"><h2>Still open here</h2><ul>'
                f"{view_open_items}</ul></section></aside>"
                "</div></section>"
            )
        if options:
            picker_groups.append(
                f'<optgroup label="{group_label}">{"".join(options)}</optgroup>'
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
                f"{len(remaining) - len(overview_remaining)} more · choose a view"
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
            '<h2>Choose a project.</h2></div>'
            '<p>Scan projects here, or use the selector to focus by project, contributor, '
            "or computer.</p></div>"
            f'<div class="overview-grid">{"".join(project_cards)}</div>'
            f"{project_overflow}"
        )
    else:
        overview_activity = (
            '<section class="empty-state"><p>No checkpoints were recorded in '
            "this window.</p></section>"
        )

    disabled_selector = " disabled" if not selected else ""

    period_name = "Daily" if period == "daily" else "Weekly"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{period_name} Worklog — {_safe(label)}</title>
  <style>
    :root {{ --paper:#f5f4ed; --paper-2:#efeee5; --ink:#0b0d0b; --muted:#52534e;
      --soft:#65655c; --rule:rgba(11,13,11,.12); --rule-soft:rgba(11,13,11,.06);
      --accent:#f7591f; --accent-tint:rgba(247,89,31,.1); --good:#18794e;
      --font-serif:"Instrument Serif","Times New Roman",serif;
      --font-sans:"Inter",system-ui,-apple-system,"Segoe UI",sans-serif;
      --font-mono:"Geist Mono",ui-monospace,SFMono-Regular,Menlo,Monaco,monospace; }}
    *,*::before,*::after {{ box-sizing:border-box; }}
    html {{ color-scheme:light; }}
    body {{ margin:0; color:var(--ink); background:var(--paper);
      font:15px/1.55 var(--font-sans); }}
    button,select {{ font:inherit; }}
    .shell {{ max-width:1120px; margin:0 auto; padding:28px 32px 72px; }}
    .site-header {{ display:flex; align-items:baseline; justify-content:space-between; gap:24px;
      padding:0 0 18px; border-bottom:1px solid var(--rule); }}
    .wordmark {{ font:400 27px/1 var(--font-serif); letter-spacing:-.01em; }}
    .colophon,.eyebrow,.control-kicker,.section-kicker {{ font:500 10px/1.3 var(--font-mono);
      letter-spacing:.16em; text-transform:uppercase; }}
    .colophon {{ color:var(--soft); }}
    .masthead {{ display:grid; grid-template-columns:minmax(0,1.35fr) minmax(220px,.65fr);
      align-items:end; gap:64px; padding:68px 0 62px; border-bottom:1px solid var(--rule); }}
    .eyebrow,.control-kicker,.section-kicker {{ color:var(--accent); }}
    h1 {{ max-width:780px; margin:15px 0 16px; font:400 clamp(3.2rem,6.2vw,5.3rem)/.96
      var(--font-serif); letter-spacing:-.022em; }}
    h1 em {{ color:var(--accent); font-weight:400; }}
    .date {{ margin:0; color:var(--muted); font-size:17px; }}
    .hero-note {{ padding-left:20px; border-left:2px solid var(--accent); }}
    .hero-note strong {{ display:block; margin-bottom:6px; font:400 23px/1.1 var(--font-serif); }}
    .hero-note span {{ color:var(--muted); font-size:13px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(5,1fr); margin:0 0 56px;
      border-bottom:1px solid var(--rule); }}
    .metric {{ min-width:0; padding:24px 20px 27px; border-right:1px solid var(--rule); }}
    .metric:first-child {{ padding-left:0; }}
    .metric:last-child {{ border-right:0; }}
    .metric strong {{ display:block; font:400 34px/1 var(--font-serif); }}
    .metric span {{ display:block; margin-top:7px; color:var(--soft); font:500 10px/1.2 var(--font-mono);
      letter-spacing:.14em; text-transform:uppercase; }}
    .controls {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(280px,420px);
      align-items:end; gap:32px; padding:24px; margin-bottom:56px; background:var(--paper-2);
      border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); }}
    .control-kicker,.section-kicker {{ display:block; margin-bottom:7px; }}
    .controls label {{ display:block; font:400 28px/1.05 var(--font-serif); letter-spacing:-.012em; }}
    .controls p {{ margin:7px 0 0; color:var(--muted); font-size:12px; }}
    select {{ width:100%; min-height:48px; padding:10px 42px 10px 14px; color:var(--ink);
      background:var(--paper); border:1px solid rgba(11,13,11,.28); border-radius:6px; }}
    select:focus-visible,.project-card:focus-visible,.back-button:focus-visible {{ outline:3px solid
      var(--accent-tint); outline-offset:3px; }}
    .digest-view[hidden] {{ display:none !important; }}
    .overview-layout,.project-layout {{ display:grid;
      grid-template-columns:minmax(0,1fr) minmax(250px,300px); gap:64px; }}
    .overview-heading {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(220px,.8fr);
      align-items:end; gap:32px; margin-bottom:24px; }}
    .overview-heading h2 {{ margin:0; font:400 34px/1.05 var(--font-serif); letter-spacing:-.014em; }}
    .overview-heading p {{ margin:0; color:var(--muted); font-size:13px; }}
    .overview-grid {{ border-top:1px solid var(--rule); }}
    .project-card {{ appearance:none; display:grid; grid-template-columns:minmax(140px,.7fr)
      minmax(0,1.3fr) auto; grid-template-areas:"top preview link" "count preview link";
      width:100%; min-width:0; padding:23px 0; text-align:left; color:var(--ink);
      background:transparent; border:0; border-bottom:1px solid var(--rule); border-radius:0;
      cursor:pointer; transition:color .15s ease; }}
    .project-card:hover {{ color:var(--accent); }}
    .project-card-top {{ grid-area:top; display:block; min-width:0; padding-right:20px; }}
    .project-card-top strong {{ display:block; overflow:hidden; text-overflow:ellipsis;
      white-space:nowrap; font:400 24px/1.08 var(--font-serif); letter-spacing:-.008em; }}
    .project-card-top > span {{ display:none; }}
    .project-count {{ grid-area:count; display:block; margin-top:7px; color:var(--soft);
      font:500 9px/1.2 var(--font-mono); letter-spacing:.12em; text-transform:uppercase; }}
    .project-preview {{ grid-area:preview; align-self:center; display:block; min-width:0;
      padding-right:24px; color:var(--muted); font-size:12px; }}
    .project-preview span {{ display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    .project-preview span + span {{ margin-top:4px; color:var(--soft); }}
    .project-link {{ grid-area:link; align-self:center; color:var(--soft); font:500 10px/1.2 var(--font-mono);
      letter-spacing:.12em; text-transform:uppercase; white-space:nowrap; }}
    .project-link::after {{ content:" →"; color:var(--accent); }}
    .overview-more {{ margin:18px 0 0; color:var(--muted); font-size:12px; }}
    .back-button {{ appearance:none; margin:0 0 20px; padding:0; color:var(--ink); background:none;
      border:0; cursor:pointer; font:500 10px/1.3 var(--font-mono); letter-spacing:.13em;
      text-transform:uppercase; transition:color .15s ease; }}
    .back-button:hover {{ color:var(--accent); }}
    .project-detail {{ border-top:1px solid var(--rule); border-bottom:1px solid var(--rule); }}
    .project-heading {{ display:flex; align-items:baseline; justify-content:space-between; gap:24px;
      padding:24px 0; border-bottom:1px solid var(--rule); }}
    .project-heading h2 {{ margin:0; font:400 40px/1 var(--font-serif); letter-spacing:-.015em; }}
    .project-heading h2:focus {{ outline:none; }}
    .project-heading span {{ color:var(--soft); font:500 10px/1.2 var(--font-mono);
      letter-spacing:.12em; text-transform:uppercase; }}
    .project-heading .view-kind {{ display:block; margin-bottom:8px; color:var(--accent); }}
    .checkpoint {{ display:grid; grid-template-columns:96px 1fr; padding:27px 0;
      border-bottom:1px solid var(--rule); }}
    .checkpoint:last-child {{ border-bottom:0; }}
    .checkpoint-rail {{ display:flex; align-items:center; align-self:start; gap:9px; color:var(--soft);
      font:500 10px/1 var(--font-mono); letter-spacing:.08em; }}
    .dot {{ width:7px; height:7px; border-radius:50%; background:var(--accent); }}
    .dot.complete {{ background:var(--good); }}
    .checkpoint-meta {{ display:flex; gap:9px; margin-bottom:7px; color:var(--soft);
      font:500 9px/1.2 var(--font-mono); letter-spacing:.12em; text-transform:uppercase; }}
    .checkpoint-meta span + span::before {{ content:"·"; margin-right:9px; color:var(--rule); }}
    .checkpoint h3 {{ margin:0; font:400 24px/1.15 var(--font-serif); letter-spacing:-.006em; }}
    details {{ margin-top:13px; color:var(--muted); font-size:13px; }}
    summary {{ cursor:pointer; color:var(--ink); font-weight:500; text-decoration:underline;
      text-decoration-color:var(--rule); text-underline-offset:4px; }}
    details ul {{ margin:8px 0 11px; padding-left:20px; }}
    .detail-label {{ margin-top:11px; color:var(--soft); font:500 9px/1.2 var(--font-mono);
      letter-spacing:.14em; text-transform:uppercase; }}
    a {{ color:var(--ink); text-underline-offset:4px; }}
    a:hover {{ color:var(--accent); }}
    aside {{ align-self:start; position:sticky; top:24px; }}
    .open {{ padding-top:20px; border-top:2px solid var(--accent); }}
    .open h2 {{ margin:0 0 15px; font:400 27px/1.05 var(--font-serif); }}
    .open ul {{ margin:0; padding:0; list-style:none; }}
    .open li {{ padding:14px 0; border-top:1px solid var(--rule); }}
    .open li span {{ display:block; }}
    .open small {{ display:block; margin-top:4px; color:var(--accent); font:500 9px/1.2 var(--font-mono);
      letter-spacing:.1em; text-transform:uppercase; }}
    .open .empty,.open .more-open {{ color:var(--soft); }}
    .empty-state {{ padding:46px 0; border-top:1px solid var(--rule); border-bottom:1px solid var(--rule);
      text-align:center; color:var(--muted); }}
    footer {{ margin-top:72px; padding-top:22px; border-top:1px solid var(--rule);
      display:flex; justify-content:space-between; gap:24px; color:var(--soft);
      font:500 9px/1.4 var(--font-mono); letter-spacing:.08em; text-transform:uppercase; }}
    @media (max-width:760px) {{
      .shell{{padding:20px 18px 46px}} .colophon{{display:none}}
      .masthead{{grid-template-columns:1fr;gap:34px;padding:48px 0 42px}}
      h1{{font-size:clamp(3rem,15vw,4.35rem)}} .hero-note{{max-width:280px}}
      .metrics{{grid-template-columns:repeat(2,1fr);margin-bottom:44px}}
      .metric{{padding:20px 12px 22px}} .metric:first-child{{padding-left:0}}
      .metric:nth-child(2){{border-right:0}} .metric:nth-child(3){{padding-left:0}}
      .metric:nth-child(4){{border-right:0}} .metric-status{{grid-column:1/-1;padding-left:0;border-right:0}}
      .controls{{grid-template-columns:1fr;gap:18px;padding:22px 18px;margin-bottom:44px}}
      .overview-layout,.project-layout{{grid-template-columns:1fr;gap:42px}}
      .overview-heading{{grid-template-columns:1fr;gap:10px}}
      .project-card{{grid-template-columns:minmax(0,1fr) auto;
        grid-template-areas:"top link" "count count" "preview preview";gap:0}}
      .project-preview{{padding:15px 0 0}} .project-link{{font-size:0}}
      .project-link::after{{content:"→";font-size:16px}}
      .project-heading h2{{font-size:34px}}
      .checkpoint{{grid-template-columns:1fr;gap:13px}}
      aside{{position:static}} footer{{display:block}} footer span{{display:block}}
      footer span + span{{margin-top:5px}}
    }}
    @media (prefers-reduced-motion:reduce) {{ *{{scroll-behavior:auto!important;transition:none!important}} }}
    @media print {{ body{{background:white}} .shell{{max-width:none;padding:0}}
      .site-header,.controls,.back-button{{display:none}} aside{{position:static}} details{{display:none}} }}
  </style>
</head>
<body>
  <main class="shell">
    <header class="site-header">
      <span class="wordmark">Worklog</span>
      <span class="colophon">Cathryn Lavery · local work ledger</span>
    </header>
    <section class="masthead">
      <div>
        <div class="eyebrow">{period_name} worklog</div>
        <h1>What <em>actually got done.</em></h1>
        <p class="date">{_safe(label)}</p>
      </div>
      <p class="hero-note"><strong>Evidence, not activity.</strong>
        <span>A private record of completed work, proof, and what remains.</span></p>
    </section>
    <section class="metrics" aria-label="Digest summary">
      <div class="metric"><strong>{len(selected)}</strong><span>checkpoints</span></div>
      <div class="metric"><strong>{len(projects)}</strong><span>projects</span></div>
      <div class="metric"><strong>{len(agents)}</strong><span>contributors</span></div>
      <div class="metric"><strong>{len(computers)}</strong><span>computers</span></div>
      <div class="metric metric-status"><strong>{completed}/{partial}</strong><span>done / partial</span></div>
    </section>
    <section class="controls" aria-labelledby="view-picker-label">
      <div><span class="control-kicker">Focus the digest</span>
        <label id="view-picker-label" for="view-picker">Choose a view</label>
        <p>Showing <strong id="current-view-label">All work overview</strong></p>
      </div>
      <select id="view-picker"{disabled_selector}>
        <option value="overview">All work overview</option>
        {"".join(picker_groups)}
      </select>
    </section>
    <section class="digest-view" id="overview" data-digest-view>
      <div class="overview-layout">
        <div>{overview_activity}</div>
        <aside><section class="open"><h2>Still open</h2><ul>{overview_open_items}</ul></section></aside>
      </div>
    </section>
    {"".join(focus_views)}
    <footer>
      <span>Generated by Worklog · private, local, evidence-based</span>
      <span>{generated.strftime('%Y-%m-%d %H:%M %Z')}</span>
    </footer>
  </main>
  <script>
    (() => {{
      const picker = document.getElementById("view-picker");
      const currentLabel = document.getElementById("current-view-label");
      const views = Array.from(document.querySelectorAll("[data-digest-view]"));

      function showView(requestedId, moveFocus) {{
        const requested = document.getElementById(requestedId);
        const selected = requested && requested.hasAttribute("data-digest-view")
          ? requested : document.getElementById("overview");
        views.forEach((view) => {{ view.hidden = view !== selected; }});
        picker.value = selected.id;
        const option = picker.options[picker.selectedIndex];
        currentLabel.textContent = option ? option.textContent : "All work overview";
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
      document.querySelectorAll("[data-select-view]").forEach((button) => {{
        button.addEventListener("click", () => showView(button.dataset.selectView, true));
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
