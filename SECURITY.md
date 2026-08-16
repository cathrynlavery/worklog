# Security policy

## Reporting a vulnerability

Please use [GitHub private vulnerability reporting](https://github.com/cathrynlavery/worklog/security/advisories/new). Do not open a public issue for a vulnerability that could expose ledger contents, local paths, credentials, or agent configuration.

Include the affected command, operating system, Python version, and the smallest safe reproduction you can provide. Never attach a real ledger, credential file, raw transcript, PHI, or secret.

## Supported versions

Until Worklog reaches 1.0, security fixes are applied to the latest release only.

## Data model

Worklog is local-first and has no network client or telemetry. Ledger directories are created with mode `0700`; checkpoint and report files use mode `0600`. The built-in redactor is defense in depth, not a data-loss-prevention system. Agents should never record secrets, credentials, PHI, raw transcripts, or unnecessary personal data.

HTML digests are self-contained and escape checkpoint content before rendering. Their small inline project selector loads no external code, assets, or data and makes no network requests. Digests still contain whatever non-secret work details were recorded in the source ledger, so treat them with the same care as the ledger itself.
