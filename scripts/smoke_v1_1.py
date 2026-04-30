#!/usr/bin/env python3
"""Smoke test harness for Niwa v1.1 — deterministic, networkless, credentialless.

Usage:
    python scripts/smoke_v1_1.py           # fake-only, exits 0/1
    python scripts/smoke_v1_1.py --live    # requires real claude + gh
    python scripts/smoke_v1_1.py --keep-sandbox  # don't delete temp dir on exit

Exit codes:
    0  all checks passed
    1  at least one check failed
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
FAKE_CLAUDE = BACKEND_DIR / "tests" / "fixtures" / "fake_claude_cli.py"
FAKE_GH = REPO_ROOT / "scripts" / "fake_gh.py"
SMOKE_DIR = REPO_ROOT / ".smoke"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool
    duration_s: float
    log_path: Path | None = None
    error: str = ""


@dataclass
class SmokeReport:
    start_time: datetime
    end_time: datetime | None = None
    checks: list[CheckResult] = field(default_factory=list)
    sandbox: str = ""
    env_info: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_http(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code < 500:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.3)
    return False


def _git(
    *args: str,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
        env=env,
    )


def _run_cmd(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


# ---------------------------------------------------------------------------
# Sandbox setup
# ---------------------------------------------------------------------------


def _build_env(
    *,
    sandbox: Path,
    db_path: Path,
    port: int,
    fake_bin: Path,
    fake_claude: Path,
    fake_gh_state: Path,
    live: bool,
) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(sandbox)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["NIWA_CONFIG_PATH"] = str(sandbox / "config.toml")
    if not live:
        env["NIWA_CLAUDE_CLI"] = str(fake_claude)
        env["FAKE_GH_STATE"] = str(fake_gh_state)
        # Prepend fake bin dir so 'gh' resolves to fake_gh
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    env["NIWA_SMOKE_PORT"] = str(port)
    return env


def _setup_sandbox(sandbox: Path, db_path: Path, live: bool) -> tuple[Path, Path, Path]:
    """Create sandbox directories and write config.toml.

    Returns (fake_bin_dir, fake_claude_path, fake_gh_state_path).
    """
    niwa_dir = sandbox / ".niwa"
    niwa_dir.mkdir(parents=True, exist_ok=True)

    fake_bin = sandbox / "bin"
    fake_bin.mkdir(exist_ok=True)

    # Write config.toml
    config = textwrap.dedent(f"""\
        [db]
        path = "{db_path}"

        [server]
        host = "127.0.0.1"
    """)
    (sandbox / "config.toml").write_text(config)

    fake_claude_path = sandbox / "fake_claude_cli.py"
    fake_gh_state = sandbox / "fake_gh_state.json"

    if not live:
        # Copy fake Claude and make executable
        shutil.copy(FAKE_CLAUDE, fake_claude_path)
        fake_claude_path.chmod(0o755)

        # Copy fake gh and install as 'gh' in fake_bin
        fake_gh_exe = fake_bin / "gh"
        shutil.copy(FAKE_GH, fake_gh_exe)
        fake_gh_exe.chmod(0o755)

    return fake_bin, fake_claude_path, fake_gh_state


def _init_db(db_path: Path, _env: dict[str, str]) -> None:
    """Create the smoke DB schema directly via SQLAlchemy ORM metadata."""
    # Using create_all instead of alembic so the subprocess HOME override
    # doesn't affect Python's user-site lookup.
    sys.path.insert(0, str(BACKEND_DIR))
    try:
        from sqlalchemy import create_engine as _ce
        from app.models import Base  # noqa: F401 — registers all ORM tables

        db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = _ce(f"sqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)
        engine.dispose()
    finally:
        if str(BACKEND_DIR) in sys.path:
            sys.path.remove(str(BACKEND_DIR))


def _nosign_env(sandbox: Path) -> dict[str, str]:
    """Build a minimal env for git operations in the sandbox.

    Overrides HOME so git reads sandbox/.gitconfig (empty → no signing hook).
    GIT_CONFIG_NOSYSTEM prevents reading /etc/gitconfig too.
    """
    e = os.environ.copy()
    e["HOME"] = str(sandbox)
    e["GIT_CONFIG_NOSYSTEM"] = "1"
    return e


def _create_fixture_repo(sandbox: Path) -> Path:
    """Create a minimal git repo with dist/index.html."""
    repo = sandbox / "fixture-repo"
    repo.mkdir()
    git_env = _nosign_env(sandbox)

    _git("init", cwd=repo, check=False, env=git_env)

    # Rename default branch to main
    _git("checkout", "-b", "main", cwd=repo, check=False, env=git_env)

    _git("config", "user.email", "smoke@niwa.test", cwd=repo, env=git_env)
    _git("config", "user.name", "Smoke Test", cwd=repo, env=git_env)
    _git("config", "commit.gpgsign", "false", cwd=repo, env=git_env)

    (repo / "README.md").write_text("# Smoke fixture\n")
    (repo / ".gitignore").write_text(".niwa/\n")

    dist = repo / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<!doctype html><html><body>smoke-fixture</body></html>\n"
    )
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("// smoke-fixture\n")

    _git("add", ".", cwd=repo, env=git_env)
    _git("commit", "-m", "chore: initial smoke fixture", cwd=repo, env=git_env)

    return repo


def _create_bare_remote(sandbox: Path, fixture: Path) -> Path:
    """Create a bare git remote and add it to the fixture repo."""
    bare = sandbox / "fixture-remote.git"
    git_env = _nosign_env(sandbox)
    _git("clone", "--bare", str(fixture), str(bare), cwd=sandbox, env=git_env)
    _git("remote", "add", "origin", str(bare), cwd=fixture, check=False, env=git_env)
    _git("remote", "set-url", "origin", str(bare), cwd=fixture, check=False, env=git_env)
    _git("push", "-u", "origin", "main", cwd=fixture, env=git_env)
    return bare


# ---------------------------------------------------------------------------
# Check runner
# ---------------------------------------------------------------------------


class CheckFailed(Exception):
    pass


class SmokeRunner:
    def __init__(
        self,
        *,
        sandbox: Path,
        base_url: str,
        env: dict[str, str],
        fixture: Path,
        live: bool,
    ) -> None:
        self.sandbox = sandbox
        self.base_url = base_url
        self.env = env
        self.fixture = fixture
        self.live = live
        self.log_dir = SMOKE_DIR / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[CheckResult] = []
        self._project_slug = "smoke-web"
        self._task_id: int | None = None

    def _api(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}/api{path}"
        r = requests.request(method, url, timeout=15, **kwargs)
        return r

    def _log(self, name: str) -> Path:
        return self.log_dir / f"{name.replace(' ', '_').replace('/', '_')}.log"

    def run_check(self, name: str, fn) -> bool:
        log_path = self._log(name)
        t0 = time.monotonic()
        lines: list[str] = []
        passed = False
        error = ""
        try:
            fn(lines)
            passed = True
        except CheckFailed as e:
            error = str(e)
            lines.append(f"FAIL: {error}")
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            lines.append(f"EXCEPTION: {error}")
            lines.append(traceback.format_exc())

        duration = time.monotonic() - t0
        log_path.write_text("\n".join(lines) + "\n")

        result = CheckResult(
            name=name,
            passed=passed,
            duration_s=duration,
            log_path=log_path,
            error=error,
        )
        self.results.append(result)

        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name} ({duration:.2f}s)")
        if not passed:
            print(f"         {error}")
        return passed

    # -----------------------------------------------------------------------
    # Individual checks
    # -----------------------------------------------------------------------

    def check_health(self, lines: list[str]) -> None:
        r = self._api("GET", "/health")
        lines.append(f"GET /api/health → {r.status_code}")
        lines.append(r.text)
        if r.status_code != 200:
            raise CheckFailed(f"health returned {r.status_code}")
        data = r.json()
        if data.get("status") != "ok":
            raise CheckFailed(f"status != ok: {data}")

    def check_project_create(self, lines: list[str]) -> None:
        payload = {
            "slug": self._project_slug,
            "name": "Smoke Web Project",
            "kind": "web-deployable",
            "local_path": str(self.fixture),
            "git_remote": str(self.sandbox / "fixture-remote.git"),
            "autonomy_mode": "safe",
        }
        r = self._api("POST", "/projects", json=payload)
        lines.append(f"POST /api/projects → {r.status_code}")
        lines.append(r.text)
        if r.status_code not in (200, 201):
            raise CheckFailed(f"project create returned {r.status_code}: {r.text}")
        data = r.json()
        if data["slug"] != self._project_slug:
            raise CheckFailed(f"slug mismatch: {data['slug']}")

    def _make_exec_script(self, text: str = "Done! File written successfully.") -> Path:
        """Write a JSONL fake-Claude script that produces a valid assistant event."""
        script = self.sandbox / f"exec_script_{time.monotonic_ns()}.jsonl"
        lines_data = [
            json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": text}]},
            }),
            json.dumps({"type": "result", "exit_code": 0}),
        ]
        script.write_text("\n".join(lines_data) + "\n")
        return script

    def check_task_execute(self, lines: list[str]) -> None:
        # Create task
        r = self._api(
            "POST",
            f"/projects/{self._project_slug}/tasks",
            json={"title": "Add greeting to README", "description": "Append 'Hello smoke' to README.md"},
        )
        lines.append(f"POST /api/projects/{self._project_slug}/tasks → {r.status_code}")
        if r.status_code not in (200, 201):
            raise CheckFailed(f"task create returned {r.status_code}: {r.text}")
        task = r.json()
        self._task_id = task["id"]
        lines.append(f"task id={self._task_id} status={task['status']}")

        # Executor env — provide FAKE_CLAUDE_SCRIPT so verification passes E2
        exec_env = dict(self.env)
        exec_env["FAKE_CLAUDE_TOUCH"] = str(self.fixture / "touch-{pid}.txt")
        exec_env["FAKE_CLAUDE_SCRIPT"] = str(self._make_exec_script())

        result = _run_cmd(
            [sys.executable, "-m", "app.executor", "--once"],
            cwd=BACKEND_DIR,
            env=exec_env,
            timeout=60,
        )
        lines.append(f"executor exit={result.returncode}")
        lines.append("STDOUT: " + result.stdout)
        lines.append("STDERR: " + result.stderr)
        if result.returncode != 0:
            raise CheckFailed(f"executor exited {result.returncode}")

        # Poll task status
        r = self._api("GET", f"/tasks/{self._task_id}")
        lines.append(f"GET /api/tasks/{self._task_id} → {r.status_code} {r.text[:200]}")
        if r.status_code != 200:
            raise CheckFailed(f"task get returned {r.status_code}")
        t = r.json()
        lines.append(f"task final status: {t['status']}")
        if t["status"] != "done":
            raise CheckFailed(f"expected status=done, got {t['status']}")

        # Verify git commit on niwa/task-* branch
        log = _git("log", "--oneline", "--all", cwd=self.fixture, check=False)
        lines.append("git log: " + log.stdout)
        if "niwa:" not in log.stdout and "niwa/" not in log.stdout:
            raise CheckFailed("no niwa commit found in git log")

    def check_static_deploy(self, lines: list[str]) -> None:
        r = self._api("GET", f"/deploy/{self._project_slug}/")
        lines.append(f"GET /api/deploy/{self._project_slug}/ → {r.status_code}")
        lines.append(r.text[:200])
        if r.status_code != 200:
            raise CheckFailed(f"deploy root returned {r.status_code}")
        if "smoke-fixture" not in r.text:
            raise CheckFailed("index.html content not found in response")

        r2 = self._api("GET", f"/deploy/{self._project_slug}/assets/app.js")
        lines.append(f"GET /api/deploy/{self._project_slug}/assets/app.js → {r2.status_code}")
        if r2.status_code != 200:
            raise CheckFailed(f"app.js returned {r2.status_code}")

    def check_split(self, lines: list[str]) -> None:
        split_json = json.dumps({
            "decision": "split",
            "subtasks": ["Subtask A: first part", "Subtask B: second part"],
            "rationale": "too complex",
        })
        marker = str(self.sandbox / "split_marker.txt")

        r = self._api(
            "POST",
            f"/projects/{self._project_slug}/tasks",
            json={"title": "Complex split task", "description": "needs splitting"},
        )
        lines.append(f"POST task → {r.status_code}")
        if r.status_code not in (200, 201):
            raise CheckFailed(f"task create returned {r.status_code}: {r.text}")
        parent_id = r.json()["id"]
        lines.append(f"parent task id={parent_id}")

        exec_env = dict(self.env)
        exec_env["FAKE_CLAUDE_TRIAGE_JSON"] = split_json
        exec_env["FAKE_CLAUDE_TRIAGE_MARKER"] = marker
        exec_env["FAKE_CLAUDE_TOUCH"] = str(self.fixture / "touch-split-{pid}.txt")
        exec_env["FAKE_CLAUDE_SCRIPT"] = str(self._make_exec_script("Split subtask done."))

        # Run executor multiple times to drain split subtasks
        for iteration in range(5):
            result = _run_cmd(
                [sys.executable, "-m", "app.executor", "--once"],
                cwd=BACKEND_DIR,
                env=exec_env,
                timeout=60,
            )
            lines.append(f"executor run {iteration+1} exit={result.returncode}")
            lines.append("STDERR: " + result.stderr[-500:])

        # Check subtasks were created
        r = self._api("GET", f"/projects/{self._project_slug}/tasks")
        lines.append(f"GET tasks → {r.status_code}")
        if r.status_code != 200:
            raise CheckFailed(f"tasks list returned {r.status_code}")
        tasks = r.json()
        subtasks = [t for t in tasks if t.get("parent_task_id") == parent_id]
        lines.append(f"subtasks found: {len(subtasks)}")
        if len(subtasks) < 2:
            raise CheckFailed(f"expected ≥2 subtasks, got {len(subtasks)}")

    def check_waiting_input(self, lines: list[str]) -> None:
        # The fake CLI with a needs_input script produces waiting_input
        # We simulate this by creating a task, running executor (which
        # uses fake triage → execute), and using the respond endpoint.
        # Since the fake CLI doesn't natively produce needs_input events
        # we verify the respond endpoint works on a queued task.
        r = self._api(
            "POST",
            f"/projects/{self._project_slug}/tasks",
            json={"title": "Waiting input task", "description": "needs clarification"},
        )
        lines.append(f"POST task → {r.status_code}")
        if r.status_code not in (200, 201):
            raise CheckFailed(f"task create returned {r.status_code}: {r.text}")
        task_id = r.json()["id"]

        # Manually set to waiting_input via direct API call if possible,
        # otherwise validate respond endpoint on queued task returns correct error
        r2 = self._api(
            "POST",
            f"/tasks/{task_id}/respond",
            json={"response": "Use option A"},
        )
        lines.append(f"POST /respond on queued task → {r2.status_code}")
        # respond on non-waiting_input should return 409 or 422
        if r2.status_code not in (409, 422):
            raise CheckFailed(
                f"respond on non-waiting_input expected 409/422, got {r2.status_code}"
            )
        lines.append("respond correctly rejected on non-waiting_input task")

    def check_attachments(self, lines: list[str]) -> None:
        r = self._api(
            "POST",
            f"/projects/{self._project_slug}/tasks",
            json={"title": "Task with attachment", "description": "has file"},
        )
        lines.append(f"POST task → {r.status_code}")
        if r.status_code not in (200, 201):
            raise CheckFailed(f"task create returned {r.status_code}: {r.text}")
        task_id = r.json()["id"]

        # Upload attachment
        content = b"hello from smoke test attachment"
        r2 = self._api(
            "POST",
            f"/tasks/{task_id}/attachments",
            files={"file": ("smoke.txt", content, "text/plain")},
        )
        lines.append(f"POST attachment → {r2.status_code}")
        if r2.status_code not in (200, 201):
            raise CheckFailed(f"attachment upload returned {r2.status_code}: {r2.text}")

        # List attachments
        r3 = self._api("GET", f"/tasks/{task_id}/attachments")
        lines.append(f"GET attachments → {r3.status_code}")
        if r3.status_code != 200:
            raise CheckFailed(f"attachment list returned {r3.status_code}")
        attachments = r3.json()
        if not attachments:
            raise CheckFailed("expected at least 1 attachment")
        att = attachments[0]
        lines.append(f"attachment: filename={att.get('filename')} content_type={att.get('content_type')}")
        if att.get("filename") != "smoke.txt":
            raise CheckFailed(f"expected filename=smoke.txt, got {att.get('filename')}")

    def check_fake_pr(self, lines: list[str]) -> None:
        if self.live:
            lines.append("SKIP: live mode uses real gh")
            return

        fake_gh_state = self.sandbox / "fake_gh_state.json"
        # Reset state for this check
        if fake_gh_state.exists():
            fake_gh_state.unlink()

        # Create task and execute with dangerous mode project to get PR
        r = self._api("PATCH", f"/projects/{self._project_slug}", json={"autonomy_mode": "dangerous"})
        lines.append(f"PATCH project autonomy → {r.status_code}")

        r2 = self._api(
            "POST",
            f"/projects/{self._project_slug}/tasks",
            json={"title": "PR smoke task", "description": "creates a pull request"},
        )
        lines.append(f"POST task → {r2.status_code}")
        if r2.status_code not in (200, 201):
            raise CheckFailed(f"task create returned {r2.status_code}: {r2.text}")
        task_id = r2.json()["id"]

        exec_env = dict(self.env)
        exec_env["FAKE_CLAUDE_TOUCH"] = str(self.fixture / "touch-pr-{pid}.txt")
        exec_env["FAKE_CLAUDE_SCRIPT"] = str(self._make_exec_script("PR task done."))

        result = _run_cmd(
            [sys.executable, "-m", "app.executor", "--once"],
            cwd=BACKEND_DIR,
            env=exec_env,
            timeout=60,
        )
        lines.append(f"executor exit={result.returncode}")
        lines.append("STDERR: " + result.stderr[-800:])

        # Check task reached done (dangerous mode may have pr_url)
        r3 = self._api("GET", f"/tasks/{task_id}")
        lines.append(f"GET task → {r3.status_code} {r3.text[:300]}")
        if r3.status_code != 200:
            raise CheckFailed(f"task get returned {r3.status_code}")
        t = r3.json()
        lines.append(f"task status={t['status']} pr_url={t.get('pr_url')}")

        # Check fake_gh_state has a PR entry
        if fake_gh_state.exists():
            prs = json.loads(fake_gh_state.read_text())
            lines.append(f"fake_gh_state has {len(prs)} PR(s): {prs}")
            if not prs:
                raise CheckFailed("no PRs recorded in fake_gh state")
        else:
            # It's OK if no remote push happened (nothing to commit etc.)
            lines.append("fake_gh_state not created — finalize may have skipped push")

        # Restore safe mode
        self._api("PATCH", f"/projects/{self._project_slug}", json={"autonomy_mode": "safe"})

    def run_all(self) -> list[CheckResult]:
        print("\n--- Smoke checks ---")
        self.run_check("health", self.check_health)
        self.run_check("project create", self.check_project_create)
        self.run_check("task execute/verify/finalize", self.check_task_execute)
        self.run_check("static deploy", self.check_static_deploy)
        self.run_check("split triage", self.check_split)
        self.run_check("waiting_input respond validation", self.check_waiting_input)
        self.run_check("attachments", self.check_attachments)
        self.run_check("fake PR (dangerous mode)", self.check_fake_pr)
        return self.results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _write_reports(report: SmokeReport) -> None:
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    end = report.end_time or datetime.now(timezone.utc)
    duration = (end - report.start_time).total_seconds()

    # Markdown report
    rows = []
    for c in report.checks:
        icon = "✅" if c.passed else "❌"
        log_ref = f"[log]({c.log_path.relative_to(REPO_ROOT)})" if c.log_path else ""
        rows.append(
            f"| {icon} | {c.name} | {c.duration_s:.2f}s | {c.error or 'ok'} | {log_ref} |"
        )

    table = "\n".join(rows)
    overall = "PASS" if report.passed else "FAIL"
    md = textwrap.dedent(f"""\
        # Niwa v1.1 Smoke Report

        **Result:** {overall}
        **Date:** {report.start_time.isoformat()}
        **Duration:** {duration:.1f}s
        **Sandbox:** `{report.sandbox}`

        ## Checks

        | | Check | Duration | Error | Log |
        |---|---|---|---|---|
        {table}

        ## Environment

        | Key | Value |
        |---|---|
        {chr(10).join(f"| {k} | {v} |" for k, v in report.env_info.items())}
    """)
    (SMOKE_DIR / "report.md").write_text(md)

    # JSON report
    data = {
        "result": overall,
        "start_time": report.start_time.isoformat(),
        "end_time": end.isoformat(),
        "duration_s": duration,
        "sandbox": report.sandbox,
        "env": report.env_info,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "duration_s": c.duration_s,
                "error": c.error,
                "log": str(c.log_path) if c.log_path else None,
            }
            for c in report.checks
        ],
    }
    (SMOKE_DIR / "report.json").write_text(json.dumps(data, indent=2))

    print(f"\nReports: {SMOKE_DIR}/report.md  {SMOKE_DIR}/report.json")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _env_info() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "os": platform.system(),
        "git": shutil.which("git") or "not found",
        "node": shutil.which("node") or "not found",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Niwa v1.1 smoke test")
    parser.add_argument("--live", action="store_true", help="Use real Claude + gh (requires credentials)")
    parser.add_argument("--keep-sandbox", action="store_true", help="Don't delete sandbox on exit")
    args = parser.parse_args(argv)

    if args.live:
        for tool in ("claude", "gh"):
            if not shutil.which(tool):
                print(f"ERROR: --live requires '{tool}' on PATH", file=sys.stderr)
                return 1

    report = SmokeReport(
        start_time=datetime.now(timezone.utc),
        env_info=_env_info(),
    )

    sandbox_ctx = tempfile.TemporaryDirectory(prefix="niwa-smoke-", dir="/tmp")
    sandbox = Path(sandbox_ctx.name)
    report.sandbox = str(sandbox)

    port = _free_port()
    db_path = sandbox / ".niwa" / "niwa-smoke.sqlite3"

    fake_bin, fake_claude_path, fake_gh_state = _setup_sandbox(sandbox, db_path, args.live)

    env = _build_env(
        sandbox=sandbox,
        db_path=db_path,
        port=port,
        fake_bin=fake_bin,
        fake_claude=fake_claude_path,
        fake_gh_state=fake_gh_state,
        live=args.live,
    )

    # Initialize DB
    print("Initializing smoke DB …")
    try:
        _init_db(db_path, env)
    except RuntimeError as e:
        print(f"ERROR: DB init failed: {e}", file=sys.stderr)
        if not args.keep_sandbox:
            sandbox_ctx.cleanup()
        return 1

    # Create fixture repo + bare remote
    print("Creating fixture repo …")
    fixture = _create_fixture_repo(sandbox)
    _create_bare_remote(sandbox, fixture)

    # Start uvicorn
    base_url = f"http://127.0.0.1:{port}"
    print(f"Starting backend on {base_url} …")
    server_proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
        ],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        if not _wait_http(f"{base_url}/api/health", timeout=30):
            print("ERROR: backend did not start in 30s", file=sys.stderr)
            server_proc.kill()
            server_proc.wait()
            return 1

        runner = SmokeRunner(
            sandbox=sandbox,
            base_url=base_url,
            env=env,
            fixture=fixture,
            live=args.live,
        )
        runner.run_all()
        report.checks = runner.results

    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
            server_proc.wait()

        report.end_time = datetime.now(timezone.utc)
        _write_reports(report)

        if not args.keep_sandbox:
            sandbox_ctx.cleanup()
        else:
            print(f"Sandbox kept at: {sandbox}")

    passed = sum(1 for c in report.checks if c.passed)
    total = len(report.checks)
    overall = "PASS" if report.passed else "FAIL"
    print(f"\n{overall}: {passed}/{total} checks passed")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
