# Changelog

All notable changes to Worklog are documented here.

## Unreleased

### Added

- Session-aware prompt-hook context: the full checkpoint rule is sent on the first turn of a session and a short reminder on later turns, cutting about 60% of the per-prompt instruction. The full rule is re-sent after a compaction and every 25 turns.
- A `hook context` diagnostic in `worklog doctor` reporting the current savings, the number of tracked sessions, and whether compaction detection is active.
- `WORKLOG_STATE_DIR` and `XDG_STATE_HOME` support for relocating hook state.

### Security

- Hook state lives outside the ledger in `~/.local/state/worklog/hook-sessions`, with directory mode `0700` and file mode `0600`. Session IDs are sanitized and digest-suffixed before use as filenames, and state files are replaced atomically.
- Hook state directories worklog owns are tightened to `0700` even when they already existed with group or world access, so a permissive directory cannot expose session-derived filenames or activity metadata. A `WORKLOG_STATE_DIR` the caller named is never re-permissioned, and a symlinked state directory is left alone rather than having its target re-permissioned; `worklog doctor` reports either case instead.

## 0.1.0 — 2026-08-16

### Added

- Evidence-required checkpoints grouped by stable agent session.
- Claude Code, Codex, and generic-agent adapters.
- Private Markdown daily reports and scheduled report generation on macOS and Linux.
- Self-contained daily and weekly HTML digests with a compact project overview, grouped project/contributor/computer selector, focused timelines, expandable evidence, and open-item rollups.
- Little Might-aligned digest styling with a warm-paper palette, serif-led hierarchy, restrained coral accents, and editorial hairline rows.
- Nightly HTML digest scheduling with `worklog install-digests`.
- Ledger import with idempotent conflict-aware merge mode.
- Installation diagnostics, permissions checks, redaction, and cutover verification.
- Standard Python packaging and a `worklog --version` command.

### Changed

- Replaced the example checkpoint with a synthetic public fixture. The previous example linked a private repository.
- Documented the `agent-worklog` package name and the Python 3.10+ requirement in the README and contributing guide.

### Security

- Ledger directories use mode `0700`; checkpoint, report, digest, and scheduler-log files use mode `0600`.
- HTML output escapes checkpoint content; its fixed inline selector loads no external code or assets and makes no network requests.
