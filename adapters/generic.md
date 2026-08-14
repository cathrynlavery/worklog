# Generic agent adapter

Use one stable session ID for the life of a conversation. After a turn produces
material, verified work, run:

```sh
worklog add --agent '<agent>' --session-id '<session-id>' \
  --title '<short summary>' \
  --done '<verified outcome>' \
  --evidence '<test, commit, URL, or artifact>' \
  --remaining '<real follow-up, if any>'
```

Evidence is required by the integration contract. Call `worklog add` only after
the work is verified, and never for conversational or no-op turns, secrets,
credentials, PHI, raw transcripts, or unverified claims. Omit `--remaining`
when nothing remains. Repeat `--done`, `--evidence`, or `--remaining` for
multiple items.
