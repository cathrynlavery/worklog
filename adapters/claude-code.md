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
