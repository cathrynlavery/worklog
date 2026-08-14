# Claude Code adapter

Replace `/absolute/path/to/worklog` with this checkout's absolute path, then
merge this block into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "PYTHONPATH='/absolute/path/to/worklog' python3 -m worklog.hook"
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
