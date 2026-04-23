# Niwa

Personal autonomous code agent — turn natural language tasks into
git commits, PRs and deploys via the Claude Code CLI.

**Status:** v1 MVP. Single-user, single-machine.

See `docs/SPEC.md` for the full spec.

## Install

Tested on macOS and Linux. Requires:

- Python 3.11+ — `brew install python@3.11` (macOS) or
  `sudo apt install python3.11 python3.11-venv` (Ubuntu).
- Node.js 22+ — `brew install node@22` (macOS) or
  https://nodejs.org (Linux).
- git.
- Claude Code CLI authenticated:
  `npm install -g @anthropic-ai/claude-code && claude`
  then `/login` inside the TUI.
- GitHub CLI (optional, needed to auto-open PRs):
  `brew install gh && gh auth login`.

Then:

```
git clone https://github.com/Takeo7/niwa.git
cd niwa
./bootstrap.sh
source ~/.niwa/venv/bin/activate
niwa-executor start
make dev
```

Backend on :8000, frontend on :5173. Open
http://127.0.0.1:5173 once both are up.

> **Note on dev mode:** `make dev` runs backend + frontend in
> the foreground of the terminal where you invoked it. Closing
> that terminal stops them. For persistent dev use tmux, nohup
> or `caffeinate -s`. A `make dev-daemon` target is planned for
> v1.1.

> **Single instance:** the bootstrap installs into `~/.niwa/`
> and registers a single launchd/systemd service. Running
> Niwa from multiple clones simultaneously is not supported —
> the second clone overwrites the service file of the first.

## First project

Niwa works on existing git repos. Point it at one.

1. Pick a repo you want to experiment with. It **must** be a
   git repo with a clean working tree (no uncommitted changes).
   Niwa creates per-task branches via `git checkout -b
   niwa/task-<id>-<slug>` from the default branch (`main` /
   `master`); it never touches your default directly.

2. Open http://127.0.0.1:5173 and click "New project". Fill:
   - **slug** — short identifier, lowercase, e.g. `playground`.
   - **name** — human-readable label.
   - **kind** — `library`, `web-deployable`, or `script`.
     `library` runs the project's tests on completion;
     `web-deployable` additionally exposes it at
     `/api/deploy/<slug>/`; `script` skips the test step.
   - **local_path** — absolute path to the repo on your disk,
     e.g. `/Users/you/repos/myproject`.
   - **git_remote** — optional. If set and `gh` is installed,
     Niwa opens a PR automatically when each task finishes.
   - **autonomy_mode** — `safe` (default, Niwa opens PR, you
     merge) or `dangerous` (Niwa auto-merges after verify).

3. Click into the project and hit "New task". Describe the work
   in natural language. Task flows through: triage → execute →
   verify → finalize (commit + push + PR).

4. Watch the run stream in the task detail. A task that ends
   with Claude asking you something parks in `waiting_input`
   — respond in the UI and the executor resumes the session.

## Known limitations (v1.0)

- DB lives in `~/.niwa/data/niwa-v1.sqlite3` and is shared
  across all clones on the same user account. For isolated
  testing use a separate user.
- `bootstrap.sh` on macOS with brew requires `python3.11`
  available; the script picks it automatically.
- `niwa-executor stop` stops the launchd/systemd service but
  does not kill `make dev` — use Ctrl-C in the terminal where
  you launched it.

See v1.1 roadmap in `docs/plans/FOUND-20260422-onboarding.md`.

## Architecture

See `docs/HANDBOOK.md`.
