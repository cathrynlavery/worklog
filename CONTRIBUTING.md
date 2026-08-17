# Contributing

Worklog should remain small, local-first, and understandable in one sitting.

## Development setup

Worklog requires Python 3.10 or newer. Apple's default `python3` is often still 3.9, so check `python3 --version` before running tests.

```sh
git clone https://github.com/cathrynlavery/worklog.git
cd worklog
python3 --version
python3 -m unittest discover -s tests
```

The runtime intentionally has no third-party dependencies. Development tools are optional.

## Before opening a pull request

```sh
python3 -m compileall worklog
python3 -m unittest discover -s tests
python3 -m pip install .
worklog --version
```

Please include tests for behavioral changes. Keep file writes atomic and private, preserve macOS and Linux support, and do not add telemetry or a network dependency.

## Privacy

Fixtures and screenshots must be synthetic. Never commit a real ledger, home-directory path, credential, raw transcript, PHI, customer record, or internal repository URL.

## Design principles

- Record verified outcomes, not activity theater.
- Require concrete evidence.
- Keep the ledger human-readable without Worklog.
- Fail clearly without corrupting existing records.
- Prefer the standard library and boring storage formats.
