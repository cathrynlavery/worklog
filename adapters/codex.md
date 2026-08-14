# Codex adapter

Add this rule to `AGENTS.md`:

```markdown
After any turn that produces material, verified work, record one concise checkpoint before the final response with `worklog add --agent codex --title '...' --done '...' --evidence '...'` and optional `--remaining '...'`. Do not record conversational or no-op turns, secrets, credentials, PHI, raw transcripts, or unverified claims. `CODEX_THREAD_ID` is picked up automatically, so `--session-id` is optional.
```

`worklog add` enforces evidence: provide a commit SHA, test result, URL, or
artifact path. Use `--allow-no-evidence` only in the rare case where verified
work genuinely has nothing citable.

Verify the adapter with `worklog doctor`.
