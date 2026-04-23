# Niwa

Personal autonomous code agent — turn natural language tasks into
git commits, PRs and deploys via the Claude Code CLI.

**Status:** v1 MVP. Single-user, single-machine.

See `docs/SPEC.md` for the full spec.

## Install

Requires Python 3.11+, Node 22+, git, `claude` CLI authenticated.

```
git clone https://github.com/takeo7/niwa.git
cd niwa
./bootstrap.sh
niwa-executor start
make dev
```

UI on http://127.0.0.1:5173.

## Architecture

See `docs/HANDBOOK.md`.
