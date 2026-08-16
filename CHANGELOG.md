# Changelog

All notable changes to Worklog are documented here.

## 0.1.0 — 2026-08-16

### Added

- Evidence-required checkpoints grouped by stable agent session.
- Claude Code, Codex, and generic-agent adapters.
- Private Markdown daily reports and scheduled report generation on macOS and Linux.
- Self-contained daily and weekly HTML digests with project timelines, agent/status labels, expandable evidence, and open-item rollups.
- Nightly HTML digest scheduling with `worklog install-digests`.
- Ledger import with idempotent conflict-aware merge mode.
- Installation diagnostics, permissions checks, redaction, and cutover verification.
- Standard Python packaging and a `worklog --version` command.

### Security

- Ledger directories use mode `0700`; checkpoint, report, digest, and scheduler-log files use mode `0600`.
- HTML output escapes checkpoint content and contains no JavaScript or external assets.
