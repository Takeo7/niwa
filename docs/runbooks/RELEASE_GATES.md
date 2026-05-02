# Release Gates

Use these gates before tagging a Niwa release candidate.

## Deterministic Gate

Run:

```bash
make release-gate
```

The gate creates a temporary `HOME`, runs `./bootstrap.sh` with
`NIWA_BOOTSTRAP_SKIP_LINGER=1`, then verifies:

- `make test`
- `make smoke`
- `niwa-executor doctor --strict`
- `niwa-executor backup`
- `niwa-executor restore --yes`

It does not require real Claude, GitHub auth, DNS, Caddy, or external network
services beyond normal package installation.

`bootstrap.sh` must leave `~/.niwa` with `0700` permissions. The strict doctor
step fails the release gate if the temporary `NIWA_HOME` is missing, has loose
permissions, or reports another operational warning.

## Live Tool Check

`make smoke-live` is intentionally a live tools check, not an end-to-end live
task smoke. It never runs in deterministic CI gates.

Run:

```bash
make smoke-live
NIWA_SMOKE_LIVE=1 make smoke-live
```

Without `NIWA_SMOKE_LIVE=1`, the target exits successfully with a skip message.
With opt-in enabled, it checks for a real `claude` CLI and authenticated `gh`
session, then exits non-zero if either is missing. It does not create a task,
open a PR, deploy online, reload Caddy, or prove DNS/TLS.

To summarize recorded deterministic smoke evidence without running gates:

```bash
python3 scripts/acceptance_summary.py
```

The summary is informational. It does not replace the literal gate output that
must be attached to release PRs or release notes.

## CI

`.github/workflows/release-gate.yml` exposes a manual `workflow_dispatch` job
for the full release gate. Keep regular PR CI deterministic and use this gate
when preparing release candidates.
