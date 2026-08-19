# Claude Code adapter

Merge this block into `~/.claude/settings.json` after installing Worklog:

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
After any turn that produces material, verified work, follow the worklog hook's
instruction and record one checkpoint before the final response. Do not record
conversational or no-op turns, secrets, credentials, PHI, raw transcripts, or
unverified claims.
```

`worklog add` enforces evidence: provide a commit SHA, test result, URL, or
artifact path. Use `--allow-no-evidence` only in the rare case where verified
work genuinely has nothing citable.

Check the integration without disclosing the settings file:

```sh
worklog doctor
```

The hook only supplies context. It does not write to the ledger or capture the
prompt. Claude records a checkpoint later, after material work has been
verified.

## What the hook costs

The hook fires on every prompt, so the instruction it injects is paid for on
every turn. Sending the whole rule each time would spend roughly 150 tokens per
prompt on text Claude already has.

Instead, the hook tracks each session and sends the full rule once:

| Turn | What Claude receives |
|---|---|
| First turn of a session | The full rule, about 590 characters. |
| Later turns | A short reminder naming the command and the session ID, about 230 characters. |
| After a compaction | The full rule again. |
| Every 25 turns | The full rule again, as a backstop. |

That is a ~60% reduction on repeat turns. This is a context-window saving, not a
billing one: repeated context sits inside the cached prefix already, but it
still occupies the window and still competes for attention.

Bookkeeping lives in `~/.local/state/worklog/hook-sessions` (directory mode
`0700`, files mode `0600`), keyed by session ID so parallel terminals never
share state. Override the location with `WORKLOG_STATE_DIR` or `XDG_STATE_HOME`.

Nothing here is load-bearing. If the state directory is missing, unwritable, or
corrupt, the hook sends the full rule, which is the behaviour it had before this
existed. Deleting the directory is safe and costs one verbose prompt per active
session. `worklog doctor` reports the current savings under `hook context`.
