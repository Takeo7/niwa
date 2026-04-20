"""Tests for FIX-20260420 PR-B — image + container verification in
``bin/update_engine.py``.

See ``docs/plans/FIX-20260420-update-engine-reliability.md`` (Bug 38:
updater printed ``✓ app:image`` and ``✓ app:restarted`` without
checking that the container actually picked up the newly-built image,
so a silent "build succeeded, container kept old image" failure made
it all the way through the update without a warning).

Pins:
 - ``capture_state`` reads container image id / image ref / started-at
   from a single ``docker inspect`` call and tolerates missing data
   (fresh installs).
 - ``_build_and_verify_image`` returns the NEW image id only when the
   build produced one different from what the container was on;
   returns None (with a warning on failure, informational record on
   cache hit) otherwise.
 - ``_recreate_and_verify_container`` uses ``--force-recreate`` (plain
   ``up -d`` does NOT recreate on image-only changes), then polls
   ``docker inspect`` until the container is Running AND on the
   expected image id. Timeout records a precise warning
   (``expected X, got Y``), returns False.
 - ``_rebuild_app`` integration: cache-hit build → no recreate; new
   image + recreate OK → success; new image + recreate timeout →
   warning + ``needs_restart=True`` (rollback lives in PR-D).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT_DIR, "bin")
if BIN_DIR not in sys.path:
    sys.path.insert(0, BIN_DIR)

import update_engine  # noqa: E402


class FakeRunner:
    """Match subprocess.run by command prefix, log every call."""

    def __init__(self) -> None:
        self.responses: list[tuple[list[str], SimpleNamespace]] = []
        self.calls: list[list[str]] = []

    def on(self, cmd_prefix, *, returncode=0, stdout="", stderr=""):
        self.responses.append((cmd_prefix, SimpleNamespace(
            returncode=returncode, stdout=stdout, stderr=stderr,
        )))

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        for prefix, resp in self.responses:
            if args[:len(prefix)] == prefix:
                return resp
        # Default: succeed silently with empty stdout. Tests that care
        # about inspect output must pin their own response.
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _make_ctx(tmp_path: Path, runner: FakeRunner) -> update_engine._Ctx:
    install_dir = tmp_path / ".niwa"
    install_dir.mkdir(parents=True)
    (install_dir / "docker-compose.yml").write_text("version: '3'\n")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    ctx = update_engine._Ctx(
        install_dir=install_dir,
        repo_dir=repo_dir,
        printer=lambda *_a, **_k: None,
        runner=runner,
        timestamp="20260420-000000",
        backup_fn=lambda c: None,
        health_check_fn=lambda c: True,
    )
    ctx.manifest = {
        "errors": [],
        "warnings": [],
        "components_updated": [],
        "needs_restart": False,
    }
    return ctx


def _stub_capture_state(runner: FakeRunner, image_id: str, image_ref: str,
                        started_at: str = "2026-04-20T00:00:00Z") -> None:
    """Stub the capture_state inspect call."""
    runner.on(
        ["docker", "inspect", "--format",
         "{{.Image}}|{{.Config.Image}}|{{.State.StartedAt}}"],
        returncode=0, stdout=f"{image_id}|{image_ref}|{started_at}\n",
    )


def _stub_image_id_lookup(runner: FakeRunner, image_ref: str,
                          new_image_id: str) -> None:
    """Stub the post-build ``docker inspect --format '{{.Id}}' <ref>``
    lookup used by ``_build_and_verify_image``."""
    runner.on(
        ["docker", "inspect", "--format", "{{.Id}}", image_ref],
        returncode=0, stdout=f"{new_image_id}\n",
    )


def _stub_container_inspect(runner: FakeRunner, running: bool,
                            image_id: str) -> None:
    """Stub the recreate-verification ``docker inspect`` poll."""
    runner.on(
        ["docker", "inspect", "--format",
         "{{.State.Running}}|{{.Image}}", "niwa-app"],
        returncode=0,
        stdout=f"{str(running).lower()}|{image_id}\n",
    )


# ── capture_state ────────────────────────────────────────────────────


def test_capture_state_reads_all_three_fields(tmp_path):
    r = FakeRunner()
    r.on(["git", "rev-parse", "HEAD"], returncode=0,
         stdout="abc123def456\n")
    _stub_capture_state(r, "sha256:aaa", "niwa-app:0.1.0",
                        "2026-04-19T10:00:00Z")
    ctx = _make_ctx(tmp_path, r)
    state = update_engine.capture_state(ctx)
    assert state["commit_sha"] == "abc123def456"
    assert state["container_image_id"] == "sha256:aaa"
    assert state["container_image_ref"] == "niwa-app:0.1.0"
    assert state["container_started_at"] == "2026-04-19T10:00:00Z"


def test_capture_state_no_container_returns_nones(tmp_path):
    r = FakeRunner()
    r.on(["git", "rev-parse", "HEAD"], returncode=0, stdout="abc\n")
    # docker inspect fails — no container yet (fresh install).
    r.on(["docker", "inspect"], returncode=1, stderr="No such object\n")
    ctx = _make_ctx(tmp_path, r)
    state = update_engine.capture_state(ctx)
    assert state["commit_sha"] == "abc"
    assert state["container_image_id"] is None
    assert state["container_image_ref"] is None
    assert state["container_started_at"] is None


def test_capture_state_malformed_inspect_returns_nones(tmp_path):
    # docker inspect succeeds but output doesn't have the 3 pipes —
    # treat as missing rather than crashing.
    r = FakeRunner()
    r.on(["git", "rev-parse", "HEAD"], returncode=0, stdout="abc\n")
    r.on(["docker", "inspect", "--format"], returncode=0,
         stdout="garbage_no_pipes\n")
    ctx = _make_ctx(tmp_path, r)
    state = update_engine.capture_state(ctx)
    assert state["container_image_id"] is None


# ── _build_and_verify_image ──────────────────────────────────────────


def test_build_and_verify_image_cache_hit_returns_none(tmp_path):
    # Build succeeds, new image id equals the running container's id
    # → cache hit, nothing to recreate.
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_image_id_lookup(r, "niwa-app:0.1.0", "sha256:same")
    ctx = _make_ctx(tmp_path, r)
    pre_state = {"container_image_id": "sha256:same",
                 "container_image_ref": "niwa-app:0.1.0"}
    result = update_engine._build_and_verify_image(ctx, pre_state)
    assert result is None
    assert any("unchanged" in c for c in ctx.manifest["components_updated"])


def test_build_and_verify_image_new_id_returns_it(tmp_path):
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_image_id_lookup(r, "niwa-app:0.1.0", "sha256:new")
    ctx = _make_ctx(tmp_path, r)
    pre_state = {"container_image_id": "sha256:old",
                 "container_image_ref": "niwa-app:0.1.0"}
    result = update_engine._build_and_verify_image(ctx, pre_state)
    assert result == "sha256:new"
    assert any("rebuilt" in c for c in ctx.manifest["components_updated"])


def test_build_and_verify_image_build_failure_is_warning(tmp_path):
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], returncode=2, stderr="build error\n")
    ctx = _make_ctx(tmp_path, r)
    pre_state = {"container_image_id": "sha256:old",
                 "container_image_ref": "niwa-app:0.1.0"}
    result = update_engine._build_and_verify_image(ctx, pre_state)
    assert result is None
    assert any("build" in w.lower() for w in ctx.manifest["warnings"])


def test_build_and_verify_image_inspect_failure_is_warning(tmp_path):
    # Build succeeds but the image we just built disappeared (docker
    # inspect returns non-zero) — report it explicitly, not a silent pass.
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    r.on(["docker", "inspect", "--format", "{{.Id}}"],
         returncode=1, stderr="No such image\n")
    ctx = _make_ctx(tmp_path, r)
    pre_state = {"container_image_id": "sha256:old",
                 "container_image_ref": "niwa-app:0.1.0"}
    result = update_engine._build_and_verify_image(ctx, pre_state)
    assert result is None
    assert any("inspect" in w.lower() for w in ctx.manifest["warnings"])


def test_build_and_verify_image_env_forces_no_cache(tmp_path, monkeypatch):
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_image_id_lookup(r, "niwa-app:0.1.0", "sha256:new")
    ctx = _make_ctx(tmp_path, r)
    pre_state = {"container_image_id": "sha256:old",
                 "container_image_ref": "niwa-app:0.1.0"}
    monkeypatch.setenv("NIWA_UPDATE_REBUILD", "1")
    update_engine._build_and_verify_image(ctx, pre_state)
    build_calls = [c for c in r.calls if c[:5] ==
                   ["docker", "compose", "-f", str(ctx.install_dir / "docker-compose.yml"), "build"]]
    assert build_calls, "build should have been invoked"
    assert "--no-cache" in build_calls[0]


def test_build_and_verify_image_default_no_no_cache(tmp_path):
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_image_id_lookup(r, "niwa-app:0.1.0", "sha256:new")
    ctx = _make_ctx(tmp_path, r)
    pre_state = {"container_image_id": "sha256:old",
                 "container_image_ref": "niwa-app:0.1.0"}
    update_engine._build_and_verify_image(ctx, pre_state)
    build_calls = [c for c in r.calls if "build" in c]
    assert build_calls
    assert not any("--no-cache" in c for c in build_calls)


def test_build_and_verify_image_fallback_ref_from_config(tmp_path):
    # Fresh install: no running container, no pre_state image_ref —
    # the fallback must match what the compose template actually
    # tags (``niwa-app:<VERSION>``), NOT the bare ``niwa-app`` which
    # resolves to ``:latest`` and doesn't exist.
    import json as _json
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_image_id_lookup(r, "niwa-app:9.9.9", "sha256:new")
    ctx = _make_ctx(tmp_path, r)
    (ctx.install_dir / ".install-config.json").write_text(_json.dumps({
        "app_container_name": "niwa-app",
        "app_image_ref": "niwa-app:9.9.9",
    }))
    pre_state = {"container_image_id": None, "container_image_ref": None}
    result = update_engine._build_and_verify_image(ctx, pre_state)
    assert result == "sha256:new"
    # Bare ``niwa-app`` must NOT have been inspected.
    assert not any(c == ["docker", "inspect", "--format", "{{.Id}}", "niwa-app"]
                   for c in r.calls)


def test_build_and_verify_image_hardcoded_fallback_without_config(tmp_path):
    # Legacy install (pre-PR-B installer) — no ``.install-config.json``
    # keys. Defaults to ``niwa-app:0.1.0`` which is what setup.py was
    # tagging at the time of the PR-A ship.
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_image_id_lookup(r, "niwa-app:0.1.0", "sha256:new")
    ctx = _make_ctx(tmp_path, r)
    pre_state = {"container_image_id": None, "container_image_ref": None}
    result = update_engine._build_and_verify_image(ctx, pre_state)
    assert result == "sha256:new"


# ── _recreate_and_verify_container ───────────────────────────────────


def test_recreate_and_verify_success(tmp_path):
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_container_inspect(r, running=True, image_id="sha256:new")
    ctx = _make_ctx(tmp_path, r)
    ok = update_engine._recreate_and_verify_container(
        ctx, "sha256:new", poll_interval=0, timeout_seconds=5)
    assert ok is True
    # --force-recreate must be in the up command — this is the whole
    # point of the fix.
    up_calls = [c for c in r.calls
                if "up" in c and "-d" in c]
    assert up_calls
    assert "--force-recreate" in up_calls[0]


def test_recreate_and_verify_timeout_reports_expected_vs_got(tmp_path):
    # Container stays on the OLD image → the regression from
    # 2026-04-19. Message must be unambiguous.
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_container_inspect(r, running=True, image_id="sha256:old")
    ctx = _make_ctx(tmp_path, r)
    ok = update_engine._recreate_and_verify_container(
        ctx, "sha256:newxxxxxxxxxxxxxxx", poll_interval=0,
        timeout_seconds=0.1)
    assert ok is False
    joined = " | ".join(ctx.manifest["warnings"])
    assert "stale image" in joined
    assert "expected" in joined and "got" in joined


def test_recreate_and_verify_up_failure_no_polling(tmp_path):
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], returncode=1,
         stderr="compose error\n")
    ctx = _make_ctx(tmp_path, r)
    ok = update_engine._recreate_and_verify_container(
        ctx, "sha256:new", poll_interval=0, timeout_seconds=5)
    assert ok is False
    # No inspect polling should have happened after up failed.
    inspect_calls = [c for c in r.calls if c[:2] == ["docker", "inspect"]]
    assert not inspect_calls


def test_recreate_and_verify_container_not_running(tmp_path):
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    # Container is on the expected image but not Running (exited,
    # crashloop, etc.). Failure must be reported as "not running",
    # NOT "stale image" — IDs match, the problem is elsewhere.
    _stub_container_inspect(r, running=False, image_id="sha256:new")
    ctx = _make_ctx(tmp_path, r)
    ok = update_engine._recreate_and_verify_container(
        ctx, "sha256:new", poll_interval=0, timeout_seconds=0.1)
    assert ok is False
    joined = " | ".join(ctx.manifest["warnings"])
    assert "not running" in joined
    assert "stale image" not in joined


def test_recreate_and_verify_uses_container_name_from_config(tmp_path):
    # The inspect polling must target the container name recorded in
    # ``.install-config.json`` (not a hardcoded ``niwa-app``).
    import json as _json
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    r.on(["docker", "inspect", "--format",
          "{{.State.Running}}|{{.Image}}", "other-app"],
         returncode=0, stdout="true|sha256:new\n")
    ctx = _make_ctx(tmp_path, r)
    (ctx.install_dir / ".install-config.json").write_text(_json.dumps({
        "app_container_name": "other-app",
        "app_image_ref": "other-app:1.2.3",
    }))
    ok = update_engine._recreate_and_verify_container(
        ctx, "sha256:new", poll_interval=0, timeout_seconds=5)
    assert ok is True
    # Inspect was called against "other-app", not "niwa-app".
    inspect_calls = [c for c in r.calls
                     if c[:3] == ["docker", "inspect", "--format"]
                     and c[-1] == "other-app"]
    assert inspect_calls


# ── _rebuild_app integration ─────────────────────────────────────────


def test_rebuild_app_cache_hit_skips_recreate(tmp_path):
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_image_id_lookup(r, "niwa-app:0.1.0", "sha256:same")
    ctx = _make_ctx(tmp_path, r)
    ctx.manifest["pre_state"] = {
        "container_image_id": "sha256:same",
        "container_image_ref": "niwa-app:0.1.0",
    }
    update_engine._rebuild_app(ctx)
    # No --force-recreate issued on cache hit.
    assert not any("--force-recreate" in c for c in r.calls)
    assert ctx.manifest["needs_restart"] is False


def test_rebuild_app_new_image_successful_recreate(tmp_path):
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_image_id_lookup(r, "niwa-app:0.1.0", "sha256:new")
    _stub_container_inspect(r, running=True, image_id="sha256:new")
    ctx = _make_ctx(tmp_path, r)
    ctx.manifest["pre_state"] = {
        "container_image_id": "sha256:old",
        "container_image_ref": "niwa-app:0.1.0",
    }
    update_engine._rebuild_app(ctx)
    assert any("--force-recreate" in c for c in r.calls)
    assert ctx.manifest["needs_restart"] is False
    # No warnings — clean happy path.
    assert ctx.manifest["warnings"] == []


def test_rebuild_app_new_image_recreate_fails_sets_needs_restart(
    tmp_path, monkeypatch,
):
    # The gold-standard regression scenario: build produces a new id
    # but the container keeps running the old image. PR-B captures
    # this as a warning + ``needs_restart=True`` (PR-D converts to
    # rollback). Advance the fake clock so we burn through the 30s
    # default timeout in a single polling iteration.
    clock = [0.0]

    def _fast_mono():
        clock[0] += 20.0
        return clock[0]

    monkeypatch.setattr(update_engine.time, "monotonic", _fast_mono)
    monkeypatch.setattr(update_engine.time, "sleep", lambda _s: None)
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    _stub_image_id_lookup(r, "niwa-app:0.1.0", "sha256:new")
    _stub_container_inspect(r, running=True, image_id="sha256:old")
    ctx = _make_ctx(tmp_path, r)
    ctx.manifest["pre_state"] = {
        "container_image_id": "sha256:old",
        "container_image_ref": "niwa-app:0.1.0",
    }
    update_engine._rebuild_app(ctx)
    assert ctx.manifest["needs_restart"] is True
    joined = " | ".join(ctx.manifest["warnings"])
    assert "stale image" in joined


def test_rebuild_app_missing_compose_file_is_warning(tmp_path):
    r = FakeRunner()
    ctx = _make_ctx(tmp_path, r)
    (ctx.install_dir / "docker-compose.yml").unlink()
    update_engine._rebuild_app(ctx)
    assert any("docker-compose.yml" in w for w in ctx.manifest["warnings"])
    # No docker invocations when compose file is missing.
    assert not any(c[:1] == ["docker"] for c in r.calls)
