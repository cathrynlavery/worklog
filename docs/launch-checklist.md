# Public launch checklist

The code can be prepared locally, but these repository settings require an explicit GitHub action by the owner.

- [ ] Merge or push the launch commit to `main`.
- [ ] Wait for every current-head CI job to pass.
- [ ] Confirm the full-history secret scan still reports zero findings.
- [ ] Change repository visibility from private to public.
- [ ] Upload `docs/social-preview.png` under **Settings → General → Social preview**.
- [ ] Add topics: `ai-agents`, `coding-agents`, `claude-code`, `codex`, `developer-tools`, `productivity`, `worklog`.
- [ ] Disable the empty wiki.
- [ ] Protect `main`: require a pull request, require the CI check, dismiss stale approvals, and block force pushes/deletion.
- [ ] Create the `v0.1.0` release from the verified launch commit using the `CHANGELOG.md` notes.
- [ ] Verify the anonymous repository, raw README, release archive, and install instructions before posting publicly.
