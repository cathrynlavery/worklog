# worklog

A private, evidence-based work journal for coding-agent sessions.

The author spent years making a paper journal that asked, “what did you actually
get done today?” Worklog is the same idea for a terminal.

## A checkpoint

This is the on-disk artifact:

```markdown
# Session accomplishment ledger

- **Session ID:** `public-example`
- **Agent:** `claude`
- **Created:** 2026-07-26T01:07:35Z

## 2026-07-26T01:07:35Z — NTTD: retire Day vocabulary + fix term nav scroll

- **Status:** partial
- **Project:** `nontechnical-dev`
- **Working directory:** `/path/to/nontechnical-dev`
- **Branch:** `fix/term-nav-scroll-to-top`
- **Commit:** `e07b91a`
- **Working tree:** clean
- **Machine:** `mac.lan`

### Accomplished

- [x] PR #10 migrates source vocabulary Day->Term with all 101 term pages byte-identical in the build.
- [x] PR #11 fixes next/prev landing at the bottom of the new page.

### Evidence

- https://github.com/cathrynlavery/nontechnical-dev/pull/10
- https://github.com/cathrynlavery/nontechnical-dev/pull/11
- `dist` diff vs main: only `index.html` + client bundle.

### Remaining

- [ ] Both PRs unmerged.
- [ ] Term 101 entry not started (waits on PR #10 merge + art approval).
- [ ] Scroll fix unverified on real iOS Safari.
- [ ] Term 62 SSH missing from `story-copy-manifest.md` (pre-existing).

---
```

See the [example file](examples/checkpoint.md).

## Install

Download a checkout with `curl`, then run its installer:

```sh
curl -fsSL -o worklog.tar.gz https://github.com/cathrynlavery/worklog/archive/refs/heads/main.tar.gz
tar -xzf worklog.tar.gz
cd worklog-main
sh install.sh
```

Or use Git:

```sh
git clone https://github.com/cathrynlavery/worklog.git
cd worklog
sh install.sh
```

The installer creates `~/.local/bin/worklog` and prints the Claude Code hook
block for you to paste. It never edits agent configuration.

It tries `python3`, `python3.14`, `python3.13`, `python3.12`, `python3.11`, and
`python3.10` in that order, selecting the first interpreter that is Python 3.10
or newer. The installer bakes that interpreter's resolved absolute path into
both the launcher (through its install-time interpreter record) and the printed
hook command, so a later `PATH` change cannot silently switch either command to
a different Python.

## How it works

The Claude Code hook supplies the session ID and checkpoint rule at prompt time.
The hook does not write anything. The agent decides whether the turn produced
material, verified work and qualifies for a checkpoint, then calls `worklog
add`.

Every checkpoint names concrete evidence: a test result, commit SHA, URL, or
artifact path. `worklog add` enforces this rule, which keeps the ledger useful
instead of turning it into a transcript dump. For the rare case where verified
work genuinely has nothing citable, `--allow-no-evidence` is the deliberate
exception.

## Commands

| Command | Purpose |
| --- | --- |
| `worklog add` | Record one verified checkpoint. |
| `worklog list` | List recent checkpoints. Bare `worklog` does the same. |
| `worklog report` | Build a Markdown report for a time window. |
| `worklog import` | Import an existing accomplishment ledger. |
| `worklog doctor` | Check Python, storage, permissions, and adapters. |
| `worklog where` | Print the resolved ledger root. |
| `worklog install-report` | Install a nightly report schedule. |
| `worklog uninstall-report` | Remove the nightly report schedule. |

Run `worklog COMMAND --help` for each command's options.

## Adapters

- [Claude Code](adapters/claude-code.md)
- [Codex](adapters/codex.md)
- [Any other agent](adapters/generic.md)

## Data and privacy

By default, data lives in `~/.local/share/worklog`. Set `WORKLOG_DIR` to choose
another location or `XDG_DATA_HOME` to change the XDG data root. `worklog where`
prints the active path.

The ledger records project names, branch names, and absolute working-directory
paths. Keep it out of a public repository. Worklog creates ledger directories
with mode `0700` and files with mode `0600`. The redactor is defence in depth,
not a guarantee; review what an agent is about to record and never give it
secrets, credentials, PHI, or raw transcripts.

## Known limitations

- An installed schedule points `PYTHONPATH` at this checkout. Moving or deleting
  the directory breaks it; run `worklog install-report` again after moving it.
- `--status` is inferred as `partial` whenever `--remaining` is passed. This is
  deliberate. On the author's own ledger, 863 of 876 entries read `partial`.
- SSH federation across machines is not in this version.

## Requirements and tests

Worklog requires Python 3.10 or newer and has no third-party dependencies. The
installer can find a supported version under any of the interpreter names
listed in the [Install](#install) section; `python3` itself does not need to
refer to the supported version.

```sh
python3 -m unittest discover -s tests
```
