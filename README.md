# Worklog

**Agent transcripts tell you everything they did. Worklog tells you what shipped.**

[![CI](https://github.com/cathrynlavery/worklog/actions/workflows/ci.yml/badge.svg)](https://github.com/cathrynlavery/worklog/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-141414)](https://www.python.org/)
[![MIT license](https://img.shields.io/badge/license-MIT-f06a3c)](LICENSE)

![A daily Worklog digest showing agent checkpoints, projects, and remaining work](docs/screenshots/digest.png)

Worklog is a private, evidence-required journal for Claude Code, Codex, and any other agent that can run a shell command. It records verified outcomes in plain Markdown, then turns them into daily and weekly reports you can actually scan.

No cloud account. No telemetry. No database. No transcript dump.

---

## Why I built it

I spent years making a paper journal that asked one useful question: **what did you actually get done today?**

Coding agents created the same problem at a different scale. They can work across repositories, terminals, and hours of context, but the record they leave behind is usually a chat transcript. That is useful for reconstruction and terrible for answering:

- What shipped?
- What evidence proves it?
- What is still open?
- Which agent worked on which project?

Worklog makes the checkpoint—not the conversation—the unit of progress.

> **A material task is not complete until the agent can name the outcome and the evidence.**

---

## What you get

| | |
|---|---|
| **Evidence-required checkpoints** | Every record needs a test, commit, URL, run ID, or artifact path. |
| **One readable ledger per session** | Human-readable Markdown grouped by agent and stable session ID. |
| **Daily + weekly HTML digests** | Self-contained, responsive, script-free summaries with project timelines and open work. |
| **Automatic nightly generation** | Native LaunchAgent support on macOS and cron support on Linux. |
| **Private local storage** | Directories use `0700`; checkpoint, report, digest, and log files use `0600`. |

Worklog supports Claude Code and Codex directly. The generic adapter works with Hermes, OpenClaw, Pi, shell agents, scheduled agents, and anything else that can invoke a command.

---

## Install

Worklog requires Python 3.10+ and has no third-party runtime dependencies.

### Clone + installer

```sh
git clone https://github.com/cathrynlavery/worklog.git
cd worklog
sh install.sh
```

The installer creates `~/.local/bin/worklog`, chooses a compatible Python interpreter, and prints the Claude Code hook block. It never edits agent configuration.

### pipx

After the `v0.1.0` release is available:

```sh
pipx install "git+https://github.com/cathrynlavery/worklog.git@v0.1.0"
```

Then verify the installation:

```sh
worklog --version
worklog doctor
```

---

## Connect an agent

### Claude Code

Merge this into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "worklog hook"
          }
        ]
      }
    ]
  }
}
```

Add this rule to `CLAUDE.md`:

```markdown
After any turn that materially changes state or completes verified work, record
one concise checkpoint with worklog before the final response. Never log
conversational/no-op turns, secrets, credentials, PHI, raw transcripts, or
unverified claims.
```

### Codex

Add this rule to `AGENTS.md`:

```markdown
After any turn that materially changes state or completes verified work, run:
worklog add --agent codex --title "..." --done "..." --evidence "..."
Add --remaining "..." only when real follow-up remains. Never log secrets,
credentials, PHI, raw transcripts, conversational/no-op turns, or unverified
claims. CODEX_THREAD_ID supplies the stable session ID automatically.
```

### Any other agent

Give the agent one stable session ID for the life of a conversation or scheduled run:

```sh
worklog add \
  --agent "my-agent" \
  --session-id "stable-conversation-id" \
  --title "Shipped the new checkout retry path" \
  --done "Made reservation writes idempotent under concurrent retries" \
  --evidence "184 tests passed; commit 8c4a7f2" \
  --remaining "Watch production retry volume after Monday's deploy"
```

Detailed adapter notes:

- [Claude Code](adapters/claude-code.md)
- [Codex](adapters/codex.md)
- [Generic agents](adapters/generic.md)

Run `worklog doctor` after connecting an agent. It checks the interpreter, ledger, permissions, contents, Claude hook, Codex rule, redactor, and Git integration without printing credential files.

---

## The checkpoint

The storage format is intentionally boring. Open it in any editor, search it with `rg`, sync it with your existing tools, or keep reading it after Worklog disappears.

<details>
<summary>See a complete checkpoint</summary>

```markdown
# Session accomplishment ledger

- **Session ID:** `stable-conversation-id`
- **Agent:** `codex`
- **Created:** 2026-08-16T17:42:00Z

## 2026-08-16T17:42:00Z — Closed the inventory reservation race

- **Status:** partial
- **Project:** `checkout-api`
- **Working directory:** `/Users/example/Developer/checkout-api`
- **Branch:** `fix/idempotent-reservations`
- **Commit:** `8c4a7f2`
- **Working tree:** clean
- **Machine:** `studio.local`

### Accomplished

- [x] Made reservation writes idempotent under concurrent retries.

### Evidence

- 184 tests passed; commit `8c4a7f2`.

### Remaining

- [ ] Watch production retry volume after Monday's deploy.

---
```

</details>

An entry is `partial` whenever it has a real remaining item. Omit `--remaining` and it is `completed`. Worklog refuses evidence-free checkpoints unless the caller deliberately supplies `--allow-no-evidence`.

---

## Daily and weekly HTML digests

Generate a daily digest:

```sh
worklog digest --period daily --write
```

Generate the current calendar week (Monday through Sunday):

```sh
worklog digest --period weekly --write
```

Generate both in one pass:

```sh
worklog digest --period all --write
```

Files land in:

```text
~/.local/share/worklog/reports/digests/daily-2026-08-16.html
~/.local/share/worklog/reports/digests/weekly-2026-W33.html
```

Use `--date YYYY-MM-DD` to regenerate a historical day or its containing calendar week. Without `--write`, a single daily or weekly digest is printed to stdout.

The HTML is responsive, printable, self-contained, and script-free. Checkpoint text is escaped before rendering. Expand **Outcome & evidence** inside the digest when you need the receipt; scan the project timeline when you only need the headline.

Install nightly digest generation:

```sh
worklog install-digests --at 21:05
```

That one job refreshes both the daily and current weekly digest. Remove it with:

```sh
worklog uninstall-digests
```

[Inspect the sanitized example HTML](docs/digest-preview.html), or download it and open it in any browser.

---

## Markdown reports

For email, terminal, or plain-text workflows:

```sh
worklog report --since today
worklog report --since week --write
worklog install-report --at 21:00
```

Markdown reports group checkpoints by project and roll every remaining item into one **Still open** list.

---

## Commands

| Command | Purpose |
|---|---|
| `worklog add` | Record one verified checkpoint. |
| `worklog list` | List recent checkpoints. Bare `worklog` does the same. |
| `worklog digest` | Build a daily or weekly self-contained HTML digest. |
| `worklog report` | Build a Markdown report for a time window. |
| `worklog doctor` | Check installation, storage, permissions, and adapters. |
| `worklog import` | Import or merge an existing ledger. |
| `worklog where` | Print the resolved ledger root. |
| `worklog hook` | Run the Claude Code prompt hook. |
| `worklog install-digests` | Schedule daily + weekly HTML digest generation. |
| `worklog uninstall-digests` | Remove the HTML digest schedule. |
| `worklog install-report` | Schedule the Markdown report. |
| `worklog uninstall-report` | Remove the Markdown report schedule. |

Run `worklog COMMAND --help` for command-specific options.

### Filter the ledger

```sh
worklog list --today
worklog list --since 7d --agent codex
worklog list --project checkout-api --json
```

### Finish a ledger cutover safely

```sh
worklog import /path/to/legacy-ledger --dry-run --on-conflict merge
worklog import /path/to/legacy-ledger --on-conflict merge
worklog import /path/to/legacy-ledger --dry-run --on-conflict merge
```

The final dry run should report zero imported files and checkpoints. Merge mode preserves existing checkpoints, appends missing ones, and stops when matching timestamps/titles contain different content.

---

## Data and privacy

By default, Worklog stores data under `~/.local/share/worklog`. Set `WORKLOG_DIR` to choose another location or `XDG_DATA_HOME` to change the XDG data root. `worklog where` prints the active path.

The ledger may contain project names, branch names, absolute working-directory paths, outcomes, evidence, and remaining work. Keep it out of a public repository.

- Ledger directories are created with mode `0700`.
- Checkpoint, report, digest, and scheduler-log files use mode `0600`.
- The built-in redactor is defense in depth, not a guarantee.
- Never record secrets, credentials, PHI, raw transcripts, customer data, or unnecessary personal information.
- HTML digests are as private as the ledger they summarize.

Worklog has no telemetry and makes no network requests. See [SECURITY.md](SECURITY.md) for vulnerability reporting and the full trust boundary.

---

## What Worklog does not do

- It does not record or summarize full transcripts.
- It does not decide whether an agent's evidence is true; your tests and review still matter.
- It does not provide cloud sync or a hosted dashboard.
- It does not federate ledgers over SSH in this release.
- It does not automatically edit Claude, Codex, or other agent configuration.

Those boundaries are deliberate. The first release is a small local tool with a format you own.

---

## Development

```sh
python3 -m compileall worklog
python3 -m unittest discover -s tests
python3 -m pip install .
worklog --version
```

CI runs on macOS and Linux across Python 3.10–3.14. Runtime dependencies: zero.

See [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md), and the [MIT license](LICENSE).

---

Built by [Cathryn Lavery](https://github.com/cathrynlavery).
