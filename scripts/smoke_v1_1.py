#!/usr/bin/env python3
"""Niwa v1.1 deterministic smoke suite.

The suite exercises the backend and executor against an isolated SQLite DB,
temporary ``NIWA_HOME``, fake Claude CLI, and fake GitHub CLI. It intentionally
uses no external network, credentials, or real GitHub/Claude services.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SMOKE_DIR = ROOT / ".smoke"
LOG_DIR = SMOKE_DIR / "logs"
FAKE_CLAUDE = BACKEND / "tests" / "fixtures" / "fake_claude_cli.py"
FAKE_GH = ROOT / "scripts" / "fake_gh_cli.py"


@dataclass
class Check:
    name: str
    passed: bool
    duration_s: float
    error: str
    log: str


class Smoke:
    def __init__(self) -> None:
        self.start = datetime.now(timezone.utc)
        self.sandbox = Path(tempfile.mkdtemp(prefix="niwa-smoke-"))
        self.niwa_home = self.sandbox / "niwa-home"
        self.db_path = self.sandbox / "niwa.sqlite3"
        self.config_path = self.sandbox / "config.toml"
        self.fake_bin = self.sandbox / "bin"
        self.fake_gh_state = self.sandbox / "fake-gh-state.json"
        self.repo = self.sandbox / "fixture-repo"
        self.remote = self.sandbox / "fixture-remote.git"
        self.client: Any = None
        self.checks: list[Check] = []
        self.env = os.environ.copy()

    def setup(self) -> None:
        if SMOKE_DIR.exists():
            shutil.rmtree(SMOKE_DIR)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.niwa_home.mkdir(parents=True, exist_ok=True)
        self.fake_bin.mkdir(parents=True, exist_ok=True)
        os.chmod(FAKE_CLAUDE, os.stat(FAKE_CLAUDE).st_mode | 0o111)
        os.chmod(FAKE_GH, os.stat(FAKE_GH).st_mode | 0o111)
        gh_link = self.fake_bin / "gh"
        try:
            gh_link.symlink_to(FAKE_GH)
        except FileExistsError:
            pass
        self.config_path.write_text(
            "\n".join(
                [
                    "[db]",
                    f'path = "{self.db_path}"',
                    "",
                    "[claude]",
                    f'cli = "{FAKE_CLAUDE}"',
                    "timeout = 20",
                    "",
                    "[executor]",
                    "poll_interval_seconds = 1",
                    "max_concurrent_runs = 1",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.env.update(
            {
                "NIWA_HOME": str(self.niwa_home),
                "NIWA_CONFIG_PATH": str(self.config_path),
                "NIWA_CONFIG": str(self.config_path),
                "NIWA_CLAUDE_CLI": str(FAKE_CLAUDE),
                "NIWA_CLAUDE_TIMEOUT": "20",
                "FAKE_GH_STATE": str(self.fake_gh_state),
                "PATH": f"{self.fake_bin}{os.pathsep}{self.env.get('PATH', '')}",
                "PYTHONPATH": f"{BACKEND}{os.pathsep}{self.env.get('PYTHONPATH', '')}",
            }
        )
        os.environ.update(self.env)
        sys.path.insert(0, str(BACKEND))

        from app.db import Base, engine  # noqa: PLC0415
        import app.models  # noqa: F401, PLC0415
        from app.main import app  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        Base.metadata.create_all(engine)
        self.client = TestClient(app)
        self._create_fixture_repo()

    def _run_git(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
            env=self.env,
        )

    def _create_fixture_repo(self) -> None:
        subprocess.run(
            ["git", "init", "--bare", str(self.remote)],
            check=True,
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.repo.mkdir()
        self._run_git(["init", "-b", "main"], self.repo)
        self._run_git(["config", "user.email", "niwa@localhost"], self.repo)
        self._run_git(["config", "user.name", "Niwa Smoke"], self.repo)
        self._run_git(["config", "commit.gpgsign", "false"], self.repo)
        (self.repo / "README.md").write_text("seed\n", encoding="utf-8")
        dist = self.repo / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text(
            "<!doctype html><html><body>smoke-fixture</body></html>\n",
            encoding="utf-8",
        )
        (dist / "assets" / "app.js").write_text(
            "window.__NIWA_SMOKE__ = true;\n",
            encoding="utf-8",
        )
        self._run_git(["add", "."], self.repo)
        self._run_git(["commit", "-m", "chore: initial smoke fixture"], self.repo)
        self._run_git(["remote", "add", "origin", str(self.remote)], self.repo)
        self._run_git(["push", "-u", "origin", "main"], self.repo)

    def run_check(self, name: str, fn: Callable[[Path], None]) -> None:
        log_path = LOG_DIR / (self._slug(name) + ".log")
        started = time.monotonic()
        try:
            fn(log_path)
            passed = True
            error = ""
        except Exception as exc:  # noqa: BLE001
            passed = False
            error = str(exc)[:500]
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write("\nTRACEBACK\n")
                fh.write(traceback.format_exc())
        duration = time.monotonic() - started
        self.checks.append(
            Check(
                name=name,
                passed=passed,
                duration_s=duration,
                error=error,
                log=str(log_path.relative_to(ROOT)),
            )
        )

    def _slug(self, text: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")

    def _write(self, log: Path, text: str) -> None:
        with log.open("a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n")

    def _jsonl(self, name: str, events: list[dict[str, Any]]) -> Path:
        path = self.sandbox / f"{name}.jsonl"
        path.write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        return path

    def _set_done_script(self, *, touch: str = "smoke-artifact-{pid}.txt") -> None:
        script = self._jsonl(
            "done",
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "Done."}],
                    },
                },
                {"type": "result", "exit_code": 0},
            ],
        )
        self.env["FAKE_CLAUDE_SCRIPT"] = str(script)
        self.env["FAKE_CLAUDE_EXIT"] = "0"
        self.env["FAKE_CLAUDE_TOUCH"] = touch
        self.env.pop("FAKE_CLAUDE_TRIAGE_JSON", None)
        self.env.pop("FAKE_CLAUDE_TRIAGE_MARKER", None)
        os.environ.update(self.env)

    def _set_question_script(self) -> None:
        script = self._jsonl(
            "question",
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "AskUserQuestion",
                                "input": {
                                    "questions": [
                                        {
                                            "question": "Which greeting should Niwa use?",
                                            "options": [
                                                {
                                                    "label": "Hello",
                                                    "description": "Use a friendly greeting.",
                                                }
                                            ],
                                        }
                                    ]
                                },
                            }
                        ],
                    },
                },
                {"type": "result", "exit_code": 0},
            ],
        )
        self.env["FAKE_CLAUDE_SCRIPT"] = str(script)
        self.env["FAKE_CLAUDE_EXIT"] = "0"
        self.env.pop("FAKE_CLAUDE_TOUCH", None)
        self.env["FAKE_CLAUDE_SESSION_ID"] = "smoke-session"
        os.environ.update(self.env)

    def _executor_once(self, log: Path) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [sys.executable, "-m", "app.executor", "--once"],
            cwd=str(BACKEND),
            capture_output=True,
            text=True,
            env=self.env,
            timeout=60,
        )
        self._write(
            log,
            "executor exit={}\nSTDOUT:\n{}\nSTDERR:\n{}".format(
                proc.returncode, proc.stdout, proc.stderr[-4000:]
            ),
        )
        if proc.returncode != 0:
            raise AssertionError(f"executor failed with exit {proc.returncode}")
        return proc

    def _request(self, method: str, path: str, log: Path, **kwargs: Any):
        response = getattr(self.client, method.lower())(path, **kwargs)
        body = response.text[:1000]
        self._write(log, f"{method.upper()} {path} -> {response.status_code}\n{body}")
        return response

    def check_health(self, log: Path) -> None:
        resp = self._request("get", "/api/health", log)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def check_project_create(self, log: Path) -> None:
        payload = {
            "slug": "smoke-web",
            "name": "Smoke Web Project",
            "kind": "web-deployable",
            "git_remote": str(self.remote),
            "local_path": str(self.repo),
            "deploy_type": "static",
            "dist_dir": "dist",
        }
        resp = self._request("post", "/api/projects", log, json=payload)
        assert resp.status_code == 201
        body = resp.json()
        assert body["slug"] == "smoke-web"
        assert body["local_path"] == str(self.repo)

    def check_task_execute(self, log: Path) -> None:
        self._set_done_script()
        resp = self._request(
            "post",
            "/api/projects/smoke-web/tasks",
            log,
            json={"title": "Add greeting to README", "description": "Smoke run"},
        )
        assert resp.status_code == 201
        task_id = resp.json()["id"]
        self._executor_once(log)
        resp = self._request("get", f"/api/tasks/{task_id}", log)
        assert resp.status_code == 200
        task = resp.json()
        assert task["status"] == "done"
        assert task["branch_name"]
        assert task["pr_url"]
        log_out = subprocess.run(
            ["git", "log", "--oneline", "-2"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            env=self.env,
            check=True,
        ).stdout
        self._write(log, "git log:\n" + log_out)

    def check_static_deploy(self, log: Path) -> None:
        resp = self._request("post", "/api/projects/smoke-web/deployments", log)
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "healthy"
        resp = self._request("get", "/api/deploy/smoke-web/", log)
        assert resp.status_code == 200
        assert "smoke-fixture" in resp.text
        resp = self._request("get", "/api/deploy/smoke-web/assets/app.js", log)
        assert resp.status_code == 200
        assert "__NIWA_SMOKE__" in resp.text

    def check_split_triage(self, log: Path) -> None:
        self._set_done_script(touch="split-artifact-{pid}.txt")
        marker = self.sandbox / "triage-marker"
        self.env["FAKE_CLAUDE_TRIAGE_MARKER"] = str(marker)
        self.env["FAKE_CLAUDE_TRIAGE_JSON"] = json.dumps(
            {
                "decision": "split",
                "subtasks": ["Subtask A: first part", "Subtask B: second part"],
                "rationale": "smoke split",
            }
        )
        os.environ.update(self.env)
        resp = self._request(
            "post",
            "/api/projects/smoke-web/tasks",
            log,
            json={"title": "Split this work", "description": "split please"},
        )
        assert resp.status_code == 201
        parent_id = resp.json()["id"]
        self._executor_once(log)
        resp = self._request("get", "/api/projects/smoke-web/tasks", log)
        assert resp.status_code == 200
        tasks = resp.json()
        children = [t for t in tasks if t["parent_task_id"] == parent_id]
        assert len(children) == 2
        assert all(t["status"] == "done" for t in children)
        parent = next(t for t in tasks if t["id"] == parent_id)
        assert parent["status"] == "done"

    def check_waiting_input_resume(self, log: Path) -> None:
        self._set_question_script()
        resp = self._request(
            "post",
            "/api/projects/smoke-web/tasks",
            log,
            json={"title": "Waiting input task", "description": "needs clarification"},
        )
        assert resp.status_code == 201
        task_id = resp.json()["id"]
        self._executor_once(log)
        resp = self._request("get", f"/api/tasks/{task_id}", log)
        assert resp.status_code == 200
        assert resp.json()["status"] == "waiting_input"
        assert resp.json()["pending_question"]
        resp = self._request(
            "post",
            f"/api/tasks/{task_id}/respond",
            log,
            json={"response": "Use Hello smoke."},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        self.env.pop("FAKE_CLAUDE_SESSION_ID", None)
        self._set_done_script(touch="resume-artifact-{pid}.txt")
        self._executor_once(log)
        resp = self._request("get", f"/api/tasks/{task_id}", log)
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    def check_attachments(self, log: Path) -> None:
        resp = self._request(
            "post",
            "/api/projects/smoke-web/tasks",
            log,
            json={"title": "Task with attachment", "description": "has file"},
        )
        assert resp.status_code == 201
        task_id = resp.json()["id"]
        files = {"file": ("smoke.txt", b"attached smoke context\n", "text/plain")}
        resp = self._request(
            "post",
            f"/api/tasks/{task_id}/attachments",
            log,
            files=files,
        )
        assert resp.status_code == 201
        resp = self._request("get", f"/api/tasks/{task_id}/attachments", log)
        assert resp.status_code == 200
        attachment_id = resp.json()[0]["id"]
        assert resp.json()[0]["filename"] == "smoke.txt"
        # Attachments intentionally live inside the project tree. Clean up this
        # API-only check so later executor checks still start from a clean repo.
        resp = self._request(
            "delete",
            f"/api/tasks/{task_id}/attachments/{attachment_id}",
            log,
        )
        assert resp.status_code == 204
        resp = self._request("delete", f"/api/tasks/{task_id}", log)
        assert resp.status_code == 204

    def check_fake_pr_dangerous_mode(self, log: Path) -> None:
        self._set_done_script(touch="dangerous-artifact-{pid}.txt")
        resp = self._request(
            "patch",
            "/api/projects/smoke-web",
            log,
            json={"autonomy_mode": "dangerous"},
        )
        assert resp.status_code == 200
        resp = self._request(
            "post",
            "/api/projects/smoke-web/tasks",
            log,
            json={"title": "PR smoke task", "description": "creates a pull request"},
        )
        assert resp.status_code == 201
        task_id = resp.json()["id"]
        self._executor_once(log)
        resp = self._request("get", f"/api/tasks/{task_id}", log)
        assert resp.status_code == 200
        task = resp.json()
        assert task["status"] == "done"
        assert task["pr_url"]
        state = json.loads(self.fake_gh_state.read_text(encoding="utf-8"))
        self._write(log, json.dumps(state, indent=2))
        assert any(pr.get("merged") for pr in state.get("prs", []))

    def report(self) -> int:
        end = datetime.now(timezone.utc)
        passed = all(c.passed for c in self.checks)
        duration = (end - self.start).total_seconds()
        payload = {
            "result": "PASS" if passed else "FAIL",
            "start_time": self.start.isoformat(),
            "end_time": end.isoformat(),
            "duration_s": duration,
            "sandbox": str(self.sandbox),
            "env": {
                "python": platform.python_version(),
                "os": platform.system(),
                "git": shutil.which("git"),
                "node": shutil.which("node"),
            },
            "checks": [c.__dict__ for c in self.checks],
        }
        SMOKE_DIR.mkdir(parents=True, exist_ok=True)
        (SMOKE_DIR / "report.json").write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        rows = []
        for c in self.checks:
            status = "PASS" if c.passed else "FAIL"
            err = c.error.replace("|", "\\|") if c.error else "ok"
            rows.append(
                f"| {status} | {c.name} | {c.duration_s:.2f}s | {err} | `{c.log}` |"
            )
        md = "\n".join(
            [
                "# Niwa v1.1 Smoke Report",
                "",
                f"**Result:** {'PASS' if passed else 'FAIL'}",
                f"**Date:** {self.start.isoformat()}",
                f"**Duration:** {duration:.1f}s",
                f"**Sandbox:** `{self.sandbox}`",
                "",
                "## Checks",
                "",
                "| Status | Check | Duration | Error | Log |",
                "|---|---|---:|---|---|",
                *rows,
                "",
                "## Environment",
                "",
                "| Key | Value |",
                "|---|---|",
                *[f"| {k} | {v} |" for k, v in payload["env"].items()],
                "",
            ]
        )
        (SMOKE_DIR / "report.md").write_text(md, encoding="utf-8")
        sys.stdout.write(md)
        return 0 if passed else 1


def main() -> int:
    smoke = Smoke()
    smoke.setup()
    checks: list[tuple[str, Callable[[Path], None]]] = [
        ("health", smoke.check_health),
        ("project create", smoke.check_project_create),
        ("task execute/verify/finalize", smoke.check_task_execute),
        ("static deploy", smoke.check_static_deploy),
        ("split triage", smoke.check_split_triage),
        ("waiting_input/resume", smoke.check_waiting_input_resume),
        ("attachments", smoke.check_attachments),
        ("fake PR dangerous mode", smoke.check_fake_pr_dangerous_mode),
    ]
    for name, fn in checks:
        smoke.run_check(name, fn)
    return smoke.report()


if __name__ == "__main__":
    raise SystemExit(main())
