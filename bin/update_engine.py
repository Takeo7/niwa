#!/usr/bin/env python3
"""Niwa update engine — shared by ``setup.py update`` (PR-58b1).

The engine is host-side only. The UI does NOT call it (see PR-58a
decision: the web process inside the container can't rebuild the
image or restart systemd). The UI posts to ``/api/system/update``
which returns an action intent pointing the operator here.

Contract:

    manifest = perform_update(
        install_dir=Path("/root/.niwa"),
        repo_dir=Path("/root/niwa"),
        printer=print,          # swap in tests for capture
        runner=subprocess.run,  # swap in tests for a fake
        timestamp=None,         # ``time.strftime`` is used by default
        backup_fn=None,         # defaults to ``_default_backup``
    )

``manifest`` is a plain dict with a stable shape:

    {
        "success": bool,
        "branch": str,
        "before_commit": str | None,
        "after_commit": str | None,
        "backup_path": str | None,
        "components_updated": list[str],
        "needs_restart": bool,
        "errors": list[str],
        "warnings": list[str],
        "duration_seconds": float,
    }

Steps:

    1. Guard repo_dirty — abort if the working tree has uncommitted
       changes.
    2. Detect current branch (no hardcoded ``main``).
    3. Backup the SQLite DB — atomic. A failing update never reaches
       the git pull without a working restore point (PR-58b1 red de
       seguridad).
    4. Git pull origin <branch>.
    5. Copy executor + MCP servers.
    6. Rebuild frontend (optional).
    7. Rebuild + restart app container.
    8. Restart executor systemd unit.

Everything after step 3 tolerates individual failures; each is
recorded in ``errors`` and execution continues when that's safe.
Fatal failures (dirty, detached, pull fail) short-circuit WITHOUT
running git pull — so the caller's ``restore`` never has to undo
partial damage.

Health-check + auto-revert land in PR-58b2 (separate PR so the base
engine ships first with real backup coverage).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


_UpdateRunner = Callable[..., subprocess.CompletedProcess]
_UpdatePrinter = Callable[[str], None]


@dataclass
class _Ctx:
    install_dir: Path
    repo_dir: Path
    printer: _UpdatePrinter
    runner: _UpdateRunner
    timestamp: str
    backup_fn: Callable[["_Ctx"], Optional[str]]
    health_check_fn: Callable[["_Ctx"], bool]
    manifest: dict = field(default_factory=dict)


def _run(ctx: _Ctx, *args: str, timeout: int = 60, cwd: Optional[Path] = None):
    """Thin wrapper that uses the injected runner so tests can
    substitute subprocess without patching the world."""
    return ctx.runner(
        list(args),
        cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=timeout,
    )


def _git(ctx: _Ctx, *args: str, timeout: int = 30) -> Optional[str]:
    try:
        r = _run(ctx, "git", *args, cwd=ctx.repo_dir, timeout=timeout)
        if r.returncode != 0:
            return None
        return (r.stdout or "").strip()
    except Exception:
        return None


def _record_error(ctx: _Ctx, msg: str) -> None:
    ctx.manifest.setdefault("errors", []).append(msg)
    ctx.printer(f"  ❌ {msg}")


def _record_warning(ctx: _Ctx, msg: str) -> None:
    ctx.manifest.setdefault("warnings", []).append(msg)
    ctx.printer(f"  ⚠️  {msg}")


def _record_component(ctx: _Ctx, name: str) -> None:
    ctx.manifest.setdefault("components_updated", []).append(name)
    ctx.printer(f"  ✓ {name}")


def _default_backup(ctx: _Ctx) -> Optional[str]:
    """Create a SQLite backup using the online backup API.

    Target: ``<install_dir>/data/backups/niwa-<timestamp>.sqlite3``.
    Returns the absolute path as a string, or ``None`` if the DB
    file doesn't exist yet (fresh install never ran migrations).

    Rotation: after a successful backup, prune files older than 14
    days. Keeps 2 weeks of pre-update snapshots without letting the
    directory grow forever (review PR-58b1 menor).
    """
    env_db = os.environ.get("NIWA_DB_PATH", "")
    db_path = Path(env_db) if env_db else (ctx.install_dir / "data" / "niwa.sqlite3")
    if not db_path.exists():
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst = backup_dir / f"niwa-{ctx.timestamp}.sqlite3"
    src_conn = sqlite3.connect(str(db_path))
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    # Rotation: drop backups older than 14 days. We keep the just-
    # created one no matter what (cutoff check uses mtime).
    try:
        import time as _t
        cutoff = _t.time() - 14 * 86400
        for old in backup_dir.glob("niwa-*.sqlite3"):
            if old == dst:
                continue
            if old.stat().st_mtime < cutoff:
                old.unlink()
    except Exception:
        # Never let rotation failures kill the update — we already
        # have the backup we care about.
        pass
    return str(dst)


def _assert_repo_clean(ctx: _Ctx) -> bool:
    """Return True if we should continue; populate manifest errors
    and return False otherwise."""
    porcelain = _git(ctx, "status", "--porcelain")
    if porcelain is None:
        _record_error(ctx, "No se pudo leer el estado del repo (git status falló).")
        return False
    if porcelain:
        _record_error(
            ctx,
            "El repositorio tiene cambios locales sin commitear. "
            "Aborto para no mezclar ramas o perder trabajo. "
            "Usa `git stash`, `git checkout .` o `git reset --hard` y "
            "vuelve a ejecutar `niwa update`.",
        )
        return False
    return True


def _detect_branch(ctx: _Ctx) -> Optional[str]:
    b = _git(ctx, "rev-parse", "--abbrev-ref", "HEAD")
    if not b or b == "HEAD":
        _record_error(
            ctx,
            "No se pudo determinar la rama actual (detached HEAD). "
            "Haz checkout de una rama antes de actualizar.",
        )
        return None
    return b


def _perform_backup(ctx: _Ctx) -> bool:
    try:
        path = ctx.backup_fn(ctx)
        ctx.manifest["backup_path"] = path
        if path:
            _record_component(ctx, f"backup: {path}")
        else:
            _record_warning(ctx, "No había base de datos que respaldar (install fresco).")
        return True
    except Exception as exc:
        _record_error(ctx, f"Backup falló: {exc}. Aborto — no se aplica update sin red.")
        return False


def _git_pull(ctx: _Ctx, branch: str) -> bool:
    ctx.printer(f"  → git pull origin {branch}")
    try:
        r = _run(
            ctx, "git", "pull", "origin", branch,
            cwd=ctx.repo_dir, timeout=120,
        )
    except Exception as exc:
        _record_error(ctx, f"git pull falló: {exc}")
        return False
    if r.returncode != 0:
        _record_error(ctx, f"git pull {branch} falló: {(r.stderr or '')[:300]}")
        return False
    ctx.printer(f"  ✓ {(r.stdout or '').strip()[:200]}")
    return True


def _copy_executor(ctx: _Ctx) -> None:
    src = ctx.repo_dir / "bin" / "task-executor.py"
    dst = ctx.install_dir / "bin" / "task-executor.py"
    if src.exists() and dst.exists():
        try:
            shutil.copy2(str(src), str(dst))
            _record_component(ctx, "executor")
        except Exception as exc:
            _record_warning(ctx, f"No se pudo copiar executor: {exc}")
    else:
        _record_warning(ctx, f"Executor no copiado (src={src.exists()}, dst={dst.exists()})")


def _copy_mcp_servers(ctx: _Ctx) -> None:
    for server_name in ("tasks-mcp", "notes-mcp", "platform-mcp"):
        src = ctx.repo_dir / "servers" / server_name / "server.py"
        dst = ctx.install_dir / "servers" / server_name / "server.py"
        if src.exists() and dst.parent.exists():
            try:
                shutil.copy2(str(src), str(dst))
                _record_component(ctx, f"mcp:{server_name}")
            except Exception as exc:
                _record_warning(ctx, f"No se pudo copiar {server_name}: {exc}")


def _rebuild_app(ctx: _Ctx) -> None:
    compose_file = ctx.install_dir / "docker-compose.yml"
    if not compose_file.exists():
        _record_warning(ctx, f"docker-compose.yml no encontrado en {ctx.install_dir}")
        return
    try:
        r = _run(
            ctx, "docker", "compose", "-f", str(compose_file),
            "build", "--no-cache", "app", timeout=600,
        )
    except Exception as exc:
        _record_warning(ctx, f"docker build falló: {exc}")
        return
    if r.returncode != 0:
        _record_warning(
            ctx, f"docker build app devolvió {r.returncode}: {(r.stderr or '')[:300]}",
        )
        return
    _record_component(ctx, "app:image")
    try:
        _run(
            ctx, "docker", "compose", "-f", str(compose_file),
            "up", "-d", "--no-deps", "app", timeout=120,
        )
        _record_component(ctx, "app:restarted")
    except Exception as exc:
        _record_warning(ctx, f"docker compose up falló: {exc}")


def _restart_executor(ctx: _Ctx) -> None:
    # PR-A3: Niwa is single-instance; the unit is always ``niwa-executor.service``.
    service_name = "niwa-executor.service"
    try:
        r = _run(ctx, "systemctl", "restart", service_name, timeout=30)
    except Exception as exc:
        _record_warning(ctx, f"systemctl restart {service_name} falló: {exc}")
        ctx.manifest["needs_restart"] = True
        return
    if r.returncode != 0:
        _record_warning(
            ctx,
            f"systemctl restart {service_name} devolvió {r.returncode}. "
            f"Reinicia manualmente: sudo systemctl restart {service_name}",
        )
        ctx.manifest["needs_restart"] = True
        return
    _record_component(ctx, f"executor:{service_name}")


def _read_app_port(ctx: _Ctx) -> Optional[int]:
    """Read the app port from mcp.env (canonical source since the
    installer writes it there). Falls back to 8080."""
    mcp_env = ctx.install_dir / "secrets" / "mcp.env"
    if mcp_env.exists():
        try:
            for line in mcp_env.read_text().splitlines():
                if line.startswith("NIWA_APP_PORT="):
                    return int(line.split("=", 1)[1].strip().strip('"').strip("'"))
        except Exception:
            pass
    return 8080


def _read_schema_version(ctx: _Ctx) -> Optional[int]:
    """Read ``MAX(version)`` from the schema_version table. Returns
    ``None`` if the DB doesn't exist or the table hasn't been
    created yet — both are benign on fresh installs."""
    env_db = os.environ.get("NIWA_DB_PATH", "")
    db_path = Path(env_db) if env_db else (ctx.install_dir / "data" / "niwa.sqlite3")
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return row[0] if row and row[0] is not None else None
        finally:
            conn.close()
    except Exception:
        return None


def _app_container_is_up(ctx: _Ctx) -> bool:
    """Return True if ``docker compose ps`` reports the app container
    as running. False on any failure/unreachable docker — the caller
    interprets False as "not confidently up" and can combine with
    HTTP /health to decide."""
    compose_file = ctx.install_dir / "docker-compose.yml"
    if not compose_file.exists():
        return True  # nothing to check — assume OK (bare metal dev)
    try:
        r = _run(
            ctx, "docker", "compose", "-f", str(compose_file),
            "ps", "--format", "json", "app", timeout=15,
        )
        if r.returncode != 0:
            return False
        # ``docker compose ps --format json`` prints one JSON object
        # per line. We want "State": "running" (or "Up") for the
        # ``app`` service.
        for raw in (r.stdout or "").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            state = (
                entry.get("State")
                or entry.get("state")
                or entry.get("Status")
                or ""
            ).lower()
            if "running" in state or state == "up":
                return True
        return False
    except Exception:
        return False


def _default_health_check(ctx: _Ctx) -> bool:
    """Post-update smoke: wait for /health, verify schema_version
    advanced (only if it was set before), and confirm the app
    container is actually Up.

    Returns False at the first step that fails so auto-revert kicks
    in. The three signals together catch more failure modes than
    any one of them alone:

      * /health alone: passes even if migrations failed silently
        or the container is in a degraded auto-restart loop.
      * schema_version alone: no signal if the DB wasn't migrated.
      * docker ps alone: passes even if the app is crashlooping
        inside the container.

    ``before_schema_version`` in the manifest is captured by
    ``perform_update`` before git pull. The comparison rule (per
    review): if before was int, after must be int AND >= before.
    If before was None, we do NOT convert that into a revert — a
    fresh install's first update wouldn't have a baseline.
    """
    port = _read_app_port(ctx)
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + 60
    attempt = 0
    http_ok = False
    while time.monotonic() < deadline:
        attempt += 1
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    http_ok = True
                    break
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            pass
        time.sleep(min(attempt, 5))
    if not http_ok:
        ctx.printer(f"  ❌ health-check: /health no respondió tras {attempt} intentos")
        return False
    ctx.printer(f"  ✓ /health OK tras {attempt} intentos")

    # Schema version check — only if we had a baseline.
    before = ctx.manifest.get("before_schema_version")
    after = _read_schema_version(ctx)
    if before is not None:
        if after is None:
            ctx.printer(
                "  ❌ schema_version: antes era "
                f"{before}, después es None — migración falló o DB inaccesible"
            )
            return False
        if after < before:
            ctx.printer(
                f"  ❌ schema_version retrocedió: {before} → {after}"
            )
            return False
        ctx.printer(f"  ✓ schema_version: {before} → {after}")
    else:
        # Sin baseline — registrar lo que vemos pero no bloquear.
        ctx.printer(f"  ✓ schema_version post-update: {after} (sin baseline)")

    # Docker container check.
    if not _app_container_is_up(ctx):
        ctx.printer("  ❌ docker compose ps: container app no está 'running'")
        return False
    ctx.printer("  ✓ docker compose ps: app Up")
    return True


def _get_db_path(ctx: _Ctx) -> Path:
    env_db = os.environ.get("NIWA_DB_PATH", "")
    if env_db:
        return Path(env_db)
    return ctx.install_dir / "data" / "niwa.sqlite3"


def _restore_db(ctx: _Ctx, backup_path: str) -> bool:
    """Copy backup → db_path atomically. Used by auto-revert.

    WAL safety (review P1): SQLite keeps ``-wal`` and ``-shm``
    sidecar files next to the main DB when in WAL journal mode. If
    we only overwrite the main file, the pre-existing sidecars get
    replayed on the next open and corrupt the restored state. Delete
    them before copying so the restored DB starts from a known clean
    point. The next `init_db` recreates them.
    """
    try:
        src = Path(backup_path)
        if not src.exists():
            return False
        dst = _get_db_path(ctx)
        # Best-effort: take the app down first so we don't race
        # writers. Failure to stop doesn't block the restore.
        compose_file = ctx.install_dir / "docker-compose.yml"
        if compose_file.exists():
            try:
                _run(ctx, "docker", "compose", "-f", str(compose_file),
                     "stop", "app", timeout=60)
            except Exception:
                pass
        # Scrub WAL sidecars so they can't re-fold stale writes onto
        # the restored main file.
        for sidecar in (dst.with_suffix(dst.suffix + "-wal"),
                        dst.with_suffix(dst.suffix + "-shm")):
            try:
                if sidecar.exists():
                    sidecar.unlink()
            except Exception:
                pass
        shutil.copy2(str(src), str(dst))
        return True
    except Exception as exc:
        _record_error(ctx, f"Restore de DB desde backup falló: {exc}")
        return False


def _auto_revert(ctx: _Ctx) -> bool:
    """Roll back code + DB to the state captured BEFORE the pull.

    Triggered when the post-update health-check fails. Best-effort:
    each step that fails is recorded as a warning so the operator
    can see exactly what degraded. Returns True if the rollback
    sequence completed end-to-end (code reset + DB restored +
    health-check green again), False otherwise.
    """
    ctx.printer("  ↩️  Auto-revert iniciado (health-check post-update falló)")
    before = ctx.manifest.get("before_commit")
    backup_path = ctx.manifest.get("backup_path")

    if not before:
        _record_warning(ctx, "auto-revert: no hay before_commit; solo revert de DB posible")
    else:
        try:
            r = _run(ctx, "git", "reset", "--hard", before,
                     cwd=ctx.repo_dir, timeout=60)
            if r.returncode != 0:
                _record_warning(
                    ctx,
                    f"auto-revert: git reset --hard {before[:12]} devolvió "
                    f"{r.returncode}: {(r.stderr or '')[:200]}",
                )
            else:
                ctx.printer(f"  ✓ código revertido a {before[:12]}")
                # Re-copy the pre-update executor + MCP servers.
                _copy_executor(ctx)
                _copy_mcp_servers(ctx)
        except Exception as exc:
            _record_warning(ctx, f"auto-revert: git reset falló: {exc}")

    if backup_path:
        if _restore_db(ctx, backup_path):
            ctx.printer(f"  ✓ DB restaurada desde {backup_path}")
        else:
            _record_warning(ctx, "auto-revert: restore de DB no completó")
    else:
        # Review P1: sin backup, la DB puede haberse migrado al
        # schema N+1 mientras el código vuelve a N. Estado
        # inconsistente — error, no warning. needs_restart forza al
        # operador a tomar acción manual.
        _record_error(
            ctx,
            "auto-revert: no hay backup_path. La DB podría tener "
            "schema N+1 mientras el código se restaura a N. Estado "
            "inconsistente — revisa manualmente la DB antes de "
            "reiniciar el app.",
        )
        ctx.manifest["needs_restart"] = True

    # Re-rebuild + restart so the container picks up the reverted code.
    _rebuild_app(ctx)
    _restart_executor(ctx)
    # Try health-check again after revert.
    ok = ctx.health_check_fn(ctx)
    if ok:
        ctx.manifest["reverted"] = True
        ctx.printer("  ✅ auto-revert completado: instalación restaurada al estado previo")
    else:
        ctx.manifest["reverted"] = False
        _record_error(
            ctx,
            "auto-revert no pudo dejar la instalación sana. Intervención manual requerida. "
            f"Backup disponible en: {backup_path or '(ninguno)'}",
        )
    return ok


def _write_update_log(ctx: _Ctx) -> None:
    """Persist the manifest in ``<install_dir>/data/update-log.json``
    so ``/api/version`` can surface last-update context. Keeps the
    last 20 entries.
    """
    try:
        log_path = ctx.install_dir / "data" / "update-log.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        if log_path.exists():
            try:
                entries = json.loads(log_path.read_text()) or []
                if not isinstance(entries, list):
                    entries = []
            except json.JSONDecodeError:
                entries = []
        # Append a compact entry (full manifest) at the end.
        compact = {
            "timestamp": ctx.timestamp,
            "success": ctx.manifest.get("success"),
            "reverted": ctx.manifest.get("reverted"),
            "branch": ctx.manifest.get("branch"),
            "before_commit": ctx.manifest.get("before_commit"),
            "after_commit": ctx.manifest.get("after_commit"),
            "backup_path": ctx.manifest.get("backup_path"),
            "errors": ctx.manifest.get("errors") or [],
            "warnings": ctx.manifest.get("warnings") or [],
            "duration_seconds": ctx.manifest.get("duration_seconds"),
        }
        entries.append(compact)
        # Retain the last 20 entries.
        if len(entries) > 20:
            entries = entries[-20:]
        log_path.write_text(json.dumps(entries, indent=2))
    except Exception:
        # Logging is best-effort; the update itself shouldn't fail
        # because we couldn't persist its manifest.
        pass


def _find_manifest_entry_for_backup(
    install_dir: Path, backup_path: str,
) -> Optional[dict]:
    """Locate the update-log entry that produced this backup — that's
    the source of truth for which commit to roll the code back to.
    Returns ``None`` if the log or entry can't be found (fresh
    install, log rotated away, backup from another machine, etc.).
    """
    log_path = install_dir / "data" / "update-log.json"
    if not log_path.exists():
        return None
    try:
        entries = json.loads(log_path.read_text())
    except Exception:
        return None
    if not isinstance(entries, list):
        return None
    # Search newest first — the most recent matching entry is the
    # canonical one.
    for entry in reversed(entries):
        if isinstance(entry, dict) and entry.get("backup_path") == backup_path:
            return entry
    return None


def perform_restore(
    install_dir: Path,
    repo_dir: Path,
    backup_path: str,
    *,
    printer: _UpdatePrinter = print,
    runner: _UpdateRunner = subprocess.run,
    db_only: bool = False,
    health_check_fn: Optional[Callable[["_Ctx"], bool]] = None,
) -> dict:
    """Restore from a backup. DB is always restored. Code is rolled
    back to the commit recorded in the update-log for this backup
    (unless ``db_only=True`` or the manifest entry is missing).

    Manifest shape:

        {
            "success": bool,
            "backup_path": str,
            "db_restored": bool,
            "code_restored": bool,
            "target_commit": str | None,   # what we rolled code to
            "manifest_entry_found": bool,  # was there a log entry?
            "health_check_ok": bool | None,
            "errors": [...],
            "warnings": [...],
        }

    Failure modes:

      * backup_path doesn't exist → success=False, immediate abort.
      * code rollback fails → warning, DB still restored, success=False
        with guidance.
      * DB copy fails → success=False (the worst case).
      * health-check fails post-restore → warning but still count as
        "restored" (the operator sees the run result + the engine log).
    """
    ts = time.strftime("%Y%m%d-%H%M%S")
    ctx = _Ctx(
        install_dir=install_dir,
        repo_dir=repo_dir,
        printer=printer,
        runner=runner,
        timestamp=ts,
        backup_fn=lambda c: None,  # not used
        health_check_fn=health_check_fn or _default_health_check,
    )
    ctx.manifest = {
        "success": False,
        "backup_path": backup_path,
        "db_restored": False,
        "code_restored": False,
        "target_commit": None,
        "manifest_entry_found": False,
        "health_check_ok": None,
        "errors": [],
        "warnings": [],
    }

    printer(f"↩️  Restore desde {backup_path}")

    if not Path(backup_path).exists():
        _record_error(ctx, f"Backup no encontrado: {backup_path}")
        return ctx.manifest

    # Locate the manifest entry so we know which commit this backup
    # belongs to. Missing entry is ok in ``--db-only`` mode; otherwise
    # we warn and skip the code rollback (never guess — could mix
    # branches silently).
    entry = _find_manifest_entry_for_backup(install_dir, backup_path)
    ctx.manifest["manifest_entry_found"] = entry is not None

    target_commit = None
    if entry and entry.get("before_commit"):
        target_commit = entry["before_commit"]
        ctx.manifest["target_commit"] = target_commit

    if not db_only and target_commit:
        ctx.printer(f"  → git checkout {target_commit[:12]}")
        try:
            r = _run(
                ctx, "git", "checkout", target_commit,
                cwd=ctx.repo_dir, timeout=60,
            )
            if r.returncode != 0:
                _record_warning(
                    ctx,
                    f"git checkout {target_commit[:12]} devolvió "
                    f"{r.returncode}: {(r.stderr or '')[:200]}. "
                    f"La DB se restaurará igualmente — arregla el "
                    f"repo manualmente.",
                )
            else:
                ctx.manifest["code_restored"] = True
                _record_component(ctx, f"code:{target_commit[:12]}")
                _copy_executor(ctx)
                _copy_mcp_servers(ctx)
        except Exception as exc:
            _record_warning(ctx, f"git checkout falló: {exc}")
    elif not db_only and not target_commit:
        _record_warning(
            ctx,
            "No encuentro la entry del update-log que generó este "
            "backup — no puedo saber a qué commit revertir. Restaurando "
            "solo DB. Revisa manualmente que el código concuerde con el "
            "schema restaurado.",
        )

    if _restore_db(ctx, backup_path):
        ctx.manifest["db_restored"] = True
        _record_component(ctx, f"db:{Path(backup_path).name}")
    else:
        _record_error(ctx, "Restore de DB no completó.")
        return ctx.manifest

    # Bring the app back up after the stop in _restore_db.
    _rebuild_app(ctx)
    health_ok = ctx.health_check_fn(ctx)
    ctx.manifest["health_check_ok"] = health_ok
    if not health_ok:
        _record_warning(
            ctx,
            "Restore completado pero el health-check post-restore no "
            "respondió. Revisa logs del app.",
        )

    ctx.manifest["success"] = ctx.manifest["db_restored"]
    if ctx.manifest["success"]:
        printer("✅ Restore completado.")
    return ctx.manifest


def perform_update(
    install_dir: Path,
    repo_dir: Path,
    *,
    printer: _UpdatePrinter = print,
    runner: _UpdateRunner = subprocess.run,
    timestamp: Optional[str] = None,
    backup_fn: Optional[Callable[["_Ctx"], Optional[str]]] = None,
    health_check_fn: Optional[Callable[["_Ctx"], bool]] = None,
) -> dict:
    """Run a full Niwa update and return a structured manifest.

    Fatal short-circuits (dirty repo, detached HEAD, backup fail,
    pull fail) produce ``success=False`` WITHOUT touching the
    runtime. Partial failures (build/restart) produce
    ``success=True`` but populate ``warnings``; ``errors`` only
    holds fatal conditions.
    """
    ts = timestamp or time.strftime("%Y%m%d-%H%M%S")
    t0 = time.monotonic()
    ctx = _Ctx(
        install_dir=install_dir,
        repo_dir=repo_dir,
        printer=printer,
        runner=runner,
        timestamp=ts,
        backup_fn=backup_fn or _default_backup,
        health_check_fn=health_check_fn or _default_health_check,
    )
    ctx.manifest.update({
        "success": False,
        "branch": None,
        "before_commit": None,
        "after_commit": None,
        "before_schema_version": None,
        "backup_path": None,
        "components_updated": [],
        "needs_restart": False,
        "errors": [],
        "warnings": [],
        "duration_seconds": 0.0,
        "reverted": None,
        "health_check_ok": None,
    })

    printer("🔄 Actualizando Niwa...")

    if not _assert_repo_clean(ctx):
        ctx.manifest["duration_seconds"] = round(time.monotonic() - t0, 2)
        _write_update_log(ctx)
        return ctx.manifest

    branch = _detect_branch(ctx)
    if not branch:
        ctx.manifest["duration_seconds"] = round(time.monotonic() - t0, 2)
        _write_update_log(ctx)
        return ctx.manifest
    ctx.manifest["branch"] = branch

    ctx.manifest["before_commit"] = _git(ctx, "rev-parse", "HEAD")
    # PR final 2: baseline for the post-update schema_version check
    # in the default health-check. Read BEFORE backup so a bad
    # backup that corrupts the DB still leaves us with a valid
    # comparison target.
    ctx.manifest["before_schema_version"] = _read_schema_version(ctx)

    if not _perform_backup(ctx):
        ctx.manifest["duration_seconds"] = round(time.monotonic() - t0, 2)
        _write_update_log(ctx)
        return ctx.manifest

    if not _git_pull(ctx, branch):
        ctx.manifest["duration_seconds"] = round(time.monotonic() - t0, 2)
        _write_update_log(ctx)
        return ctx.manifest

    ctx.manifest["after_commit"] = _git(ctx, "rev-parse", "HEAD")

    _copy_executor(ctx)
    _copy_mcp_servers(ctx)
    _rebuild_app(ctx)
    _restart_executor(ctx)

    # PR-58b2: post-update health-check + auto-revert on failure.
    health_ok = ctx.health_check_fn(ctx)
    ctx.manifest["health_check_ok"] = health_ok
    if not health_ok:
        _record_warning(
            ctx,
            "El app no responde a /health tras el update — disparando auto-revert.",
        )
        reverted = _auto_revert(ctx)
        ctx.manifest["success"] = False
        if not reverted:
            _record_error(
                ctx,
                "Estado inconsistente: el update falló Y el auto-revert no recuperó. "
                "Revisa los logs y usa `niwa restore --from=<backup>` (PR-59).",
            )
    else:
        ctx.manifest["success"] = True
        ctx.manifest["reverted"] = False

    ctx.manifest["duration_seconds"] = round(time.monotonic() - t0, 2)
    _write_update_log(ctx)
    if ctx.manifest["success"]:
        printer("✅ Update completado.")
    elif ctx.manifest.get("reverted"):
        printer("↩️  Update revertido; instalación restaurada al estado previo.")
    else:
        printer("❌ Update falló y auto-revert incompleto — intervención manual requerida.")
    return ctx.manifest
