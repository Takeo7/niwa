"""Tests for PR-38 — auto-registro de proyecto post-tarea.

Feature 1 (docs/BUGS-FOUND.md:536): when a user creates a task without
an explicit project_id and Claude creates files, those files should
show up under "Proyectos" in the UI. Before PR-38, they didn't — the
executor ran Claude with ``cwd=os.getcwd()`` (wherever systemd started
it, typically ``/``) and never registered anything.

The fix has two layers:

1. **Pre-hook** (``_auto_project_prepare``): for tasks without a
   ``project_id``, the executor creates a fresh directory under
   ``<NIWA_HOME>/data/projects/<slug>-<uuid6>/`` and injects it into
   ``task["project_directory"]`` so the Claude Code adapter sets
   ``cwd`` there. It also tells Claude in the prompt to call
   ``project_create`` (the MCP tool already exists) with those exact
   args.

2. **Post-hook safety net** (``_auto_project_finalize``): after the
   adapter runs, if the directory has files and no ``projects`` row
   points at it, the executor inserts one. Either way (new row or
   existing), ``tasks.project_id`` is associated so the task shows up
   under its project. If Claude wrote nothing, the empty directory is
   cleaned up.

These tests cover:

* ``_sanitize_slug`` rejects path-traversal characters.
* ``_auto_project_prepare`` is a no-op if ``project_id`` is set
  (backwards-compat guarantee — manual projects keep working).
* ``_auto_project_prepare`` creates the dir and mutates the task dict.
* ``_auto_project_finalize`` cleans up empty dirs.
* ``_auto_project_finalize`` inserts a project row when files exist.
* ``_auto_project_finalize`` reuses an existing row keyed by
  ``directory`` (Claude called the MCP tool itself).
* ``_auto_project_finalize`` only overwrites ``tasks.project_id``
  when it's NULL (never steals a task from an explicit project).
* ``ClaudeCodeAdapter._build_prompt`` includes the MCP instructions
  exactly when ``project_directory`` is set AND ``project_id`` is
  NULL.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = REPO_ROOT / "bin"
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def executor(monkeypatch, tmp_path):
    """Import task-executor with a minimal fake NIWA_HOME and a real
    SQLite DB at ``<tmp>/data/niwa.sqlite3`` so finalize can INSERT."""
    (tmp_path / "secrets").mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "data" / "niwa.sqlite3"
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "logs" / "executor.log").touch()
    (tmp_path / "secrets" / "mcp.env").write_text(
        f"NIWA_DB_PATH={db_path}\n",
    )
    monkeypatch.setenv("NIWA_HOME", str(tmp_path))

    # Create minimal schema — only the columns touched by the helpers.
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            slug TEXT UNIQUE,
            name TEXT,
            area TEXT,
            description TEXT,
            active INTEGER,
            created_at TEXT,
            updated_at TEXT,
            directory TEXT,
            url TEXT
        );
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            project_id TEXT,
            updated_at TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_task_executor_auto_project", str(BIN_DIR / "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        pytest.skip(f"task-executor imports failed in this env: {e}")

    return mod


# ─────────────────────── _sanitize_slug ───────────────────────

class TestSanitizeSlug:
    def test_plain_title(self, executor):
        assert executor._sanitize_slug("Build a blog") == "build-a-blog"

    def test_path_traversal_rejected(self, executor):
        # `..`, `/`, `\` must never survive — the slug gets used as a
        # directory name under <NIWA_HOME>/data/projects/.
        s = executor._sanitize_slug("../../etc/passwd")
        assert ".." not in s
        assert "/" not in s
        assert s == "etc-passwd"

    def test_null_bytes_stripped(self, executor):
        s = executor._sanitize_slug("evil\x00name")
        assert "\x00" not in s
        # Only [a-z0-9-] survives, non-alnum runs collapse to one '-'.
        assert s == "evil-name"

    def test_empty_falls_back(self, executor):
        assert executor._sanitize_slug("") == "task"
        assert executor._sanitize_slug("   ") == "task"
        assert executor._sanitize_slug("!!!") == "task"

    def test_length_cap(self, executor):
        s = executor._sanitize_slug("a" * 200)
        assert len(s) <= 40


# ─────────────────────── _auto_project_prepare ───────────────────────

class TestAutoProjectPrepare:
    def test_noop_when_project_id_set(self, executor):
        task = {"id": "t1", "title": "x", "project_id": "proj-123"}
        ctx = executor._auto_project_prepare(task)
        assert ctx is None
        assert "project_directory" not in task, (
            "Must not touch tasks that already have a project — this "
            "is the backwards-compat guarantee that manual projects "
            "keep working unchanged."
        )

    def test_creates_dir_when_project_id_null(self, executor, tmp_path):
        task = {"id": "t2", "title": "Build a blog", "project_id": None}
        ctx = executor._auto_project_prepare(task)
        assert ctx is not None
        assert ctx["slug"].startswith("build-a-blog-")
        assert Path(ctx["directory"]).is_dir()
        # The path is under NIWA_HOME/data/projects/, not some random
        # location.
        expected_root = tmp_path / "data" / "projects"
        assert Path(ctx["directory"]).parent == expected_root
        # task_dict was mutated so the adapter picks it up as cwd.
        assert task["project_directory"] == ctx["directory"]

    def test_unique_slug_per_call(self, executor):
        t1 = {"id": "t1", "title": "Same title", "project_id": None}
        t2 = {"id": "t2", "title": "Same title", "project_id": None}
        c1 = executor._auto_project_prepare(t1)
        c2 = executor._auto_project_prepare(t2)
        assert c1["slug"] != c2["slug"], (
            "Two tasks with identical titles must produce distinct "
            "slugs (the uuid suffix guarantees this) so they don't "
            "collide on the projects.slug UNIQUE constraint."
        )


# ─────────────────────── _auto_project_finalize ───────────────────────

class TestAutoProjectFinalize:
    def _seed_task(self, executor, task_id="t-42", project_id=None):
        with executor._conn() as c:
            c.execute(
                "INSERT INTO tasks (id, title, project_id, updated_at) "
                "VALUES (?,?,?,?)",
                (task_id, "my task", project_id, "2026-04-16T00:00:00"),
            )
            c.commit()

    def test_empty_dir_is_cleaned_up(self, executor, tmp_path):
        pdir = tmp_path / "data" / "projects" / "empty-abc123"
        pdir.mkdir(parents=True)
        self._seed_task(executor)
        ctx = {"slug": "empty-abc123", "directory": str(pdir), "name": "x"}

        executor._auto_project_finalize(ctx, "t-42")

        assert not pdir.exists(), (
            "If Claude wrote no files we don't want empty directories "
            "accumulating under data/projects/."
        )
        with executor._conn() as c:
            row = c.execute(
                "SELECT project_id FROM tasks WHERE id=?", ("t-42",),
            ).fetchone()
            assert row["project_id"] is None, (
                "No files → no project row → task.project_id stays null."
            )

    def test_files_present_inserts_row_and_associates(self, executor, tmp_path):
        pdir = tmp_path / "data" / "projects" / "blog-xyz789"
        pdir.mkdir(parents=True)
        (pdir / "index.html").write_text("<h1>hi</h1>")
        self._seed_task(executor)
        ctx = {"slug": "blog-xyz789", "directory": str(pdir), "name": "My blog"}

        executor._auto_project_finalize(ctx, "t-42")

        with executor._conn() as c:
            proj = c.execute(
                "SELECT id, name, directory, active FROM projects "
                "WHERE directory=?",
                (str(pdir),),
            ).fetchone()
            assert proj is not None
            assert proj["name"] == "My blog"
            assert proj["active"] == 1
            task = c.execute(
                "SELECT project_id FROM tasks WHERE id=?", ("t-42",),
            ).fetchone()
            assert task["project_id"] == proj["id"]

    def test_existing_project_row_is_reused(self, executor, tmp_path):
        """If Claude called ``project_create`` via MCP, the row already
        exists when finalize runs. We must NOT insert a duplicate —
        just associate the task."""
        pdir = tmp_path / "data" / "projects" / "claude-registered"
        pdir.mkdir(parents=True)
        (pdir / "app.py").write_text("print('hi')")
        self._seed_task(executor)

        with executor._conn() as c:
            c.execute(
                "INSERT INTO projects "
                "(id, slug, name, area, description, active, "
                " created_at, updated_at, directory, url) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("proj-preexisting", "claude-slug", "Claude's choice",
                 "proyecto", "", 1, "2026-04-16", "2026-04-16",
                 str(pdir), ""),
            )
            c.commit()

        ctx = {"slug": "claude-registered", "directory": str(pdir),
               "name": "executor fallback"}
        executor._auto_project_finalize(ctx, "t-42")

        with executor._conn() as c:
            rows = c.execute(
                "SELECT id, name FROM projects WHERE directory=?",
                (str(pdir),),
            ).fetchall()
            assert len(rows) == 1, "No duplicate row."
            assert rows[0]["name"] == "Claude's choice", (
                "Claude's chosen name wins — the executor fallback "
                "only names the project when Claude didn't."
            )
            task = c.execute(
                "SELECT project_id FROM tasks WHERE id=?", ("t-42",),
            ).fetchone()
            assert task["project_id"] == "proj-preexisting"

    def test_never_steals_task_already_on_another_project(self, executor, tmp_path):
        """Defensive: if somehow the task ended up with a project_id
        before finalize runs (e.g. Claude called task_update), do not
        re-assign."""
        pdir = tmp_path / "data" / "projects" / "late-bound"
        pdir.mkdir(parents=True)
        (pdir / "file.txt").write_text("x")
        self._seed_task(executor, project_id="proj-manual-choice")

        ctx = {"slug": "late-bound", "directory": str(pdir), "name": "x"}
        executor._auto_project_finalize(ctx, "t-42")

        with executor._conn() as c:
            task = c.execute(
                "SELECT project_id FROM tasks WHERE id=?", ("t-42",),
            ).fetchone()
            assert task["project_id"] == "proj-manual-choice", (
                "UPDATE must be conditional on project_id IS NULL; "
                "otherwise we'd overwrite user choices."
            )

    def test_finalize_runs_even_when_body_raises(self, executor, tmp_path, monkeypatch):
        """Regression guard for the try/finally in _execute_task_v02:
        if the body raises (routing crash, adapter explosion, …), the
        auto-project cleanup still runs so we don't leak empty dirs."""
        self._seed_task(executor)
        task_row = {"id": "t-42", "title": "boom", "project_id": None}

        def _body(*args, **kwargs):
            raise RuntimeError("body exploded")

        # Point the wrapper at a body that always raises; the
        # auto-project hook must still run its cleanup in ``finally``.
        monkeypatch.setattr(
            executor, "_execute_task_v02_body", _body, raising=True,
        )
        # Stub out the v0.2 imports inside the wrapper so ``try``
        # gets past them and reaches _body.
        monkeypatch.setitem(
            sys.modules, "routing_service",
            type(sys)("_stub_routing"),
        )
        monkeypatch.setitem(
            sys.modules, "runs_service",
            type(sys)("_stub_runs"),
        )
        stub_reg = type(sys)("_stub_backend_registry")
        stub_reg.get_execution_registry = lambda *a, **k: None
        monkeypatch.setitem(sys.modules, "backend_registry", stub_reg)

        with pytest.raises(RuntimeError, match="body exploded"):
            executor._execute_task_v02(task_row)

        # The prepare step ran (task_dict was mutated into a real
        # directory); finalize in finally must have cleaned it up.
        root = tmp_path / "data" / "projects"
        leftover = [p for p in root.iterdir() if p.is_dir()] if root.exists() else []
        assert leftover == [], (
            "auto-project finalize must run inside 'finally' so a "
            "raised exception in the body doesn't leak empty dirs "
            "under data/projects/."
        )

    def test_hidden_files_only_treated_as_empty(self, executor, tmp_path):
        """Claude sometimes leaves .git/ or similar scaffolding — by
        itself, that shouldn't count as 'created a project'."""
        pdir = tmp_path / "data" / "projects" / "only-dotfiles"
        pdir.mkdir(parents=True)
        (pdir / ".DS_Store").write_text("junk")
        self._seed_task(executor)
        ctx = {"slug": "only-dotfiles", "directory": str(pdir), "name": "x"}

        executor._auto_project_finalize(ctx, "t-42")

        assert not pdir.exists()
        with executor._conn() as c:
            task = c.execute(
                "SELECT project_id FROM tasks WHERE id=?", ("t-42",),
            ).fetchone()
            assert task["project_id"] is None


# ─────────────────────── adapter._build_prompt ───────────────────────

class TestAdapterPromptInjection:
    """PR-45: auto-project rules live in the APPENDED SYSTEM PROMPT
    (via ``--append-system-prompt``), not in the user message. The
    user prompt stays minimal — just the task goal. These tests
    assert rules appear ONLY in the system prompt and that the user
    prompt is clean, so future refactors that drift the rules back
    into the user message get caught."""

    def _load_adapter(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter
        return ClaudeCodeAdapter

    def test_user_prompt_has_no_rules(self):
        """The user prompt built by ``_build_prompt`` must NOT
        contain the auto-project rules — those go to the system
        prompt in PR-45. Regression against reintroducing them in
        the user message."""
        adapter = self._load_adapter()
        task = {
            "title": "Build my blog",
            "description": "please",
            "project_id": None,
            "project_directory": "/opt/niwa/data/projects/my-blog-abc123",
        }
        user_prompt = adapter._build_prompt(task)
        assert "WORKING DIRECTORY" not in user_prompt, (
            "PR-45 moved the rules to --append-system-prompt. The "
            "user prompt must NOT echo them — doing so defeats the "
            "point (rules-in-user-message was exactly what failed "
            "in PR-38..PR-44)."
        )
        assert "project_create" not in user_prompt
        assert "## Task" in user_prompt or user_prompt.startswith("#") or \
               "Build my blog" in user_prompt, (
            "The user prompt must still deliver the task goal "
            "(title/description/notes). It's minimal, not empty."
        )

    def test_system_prompt_none_when_project_id_set(self):
        adapter = self._load_adapter()
        task = {
            "title": "Existing project task",
            "description": "work on the thing",
            "project_id": "proj-abc",
            "project_directory": "/opt/niwa/data/projects/foo",
        }
        sys_prompt = adapter._build_system_prompt(task)
        assert sys_prompt is None, (
            "Tasks already attached to a project must not get the "
            "auto-project rules — the operator chose the project "
            "explicitly."
        )

    def test_system_prompt_none_when_directory_missing(self):
        adapter = self._load_adapter()
        task = {
            "title": "Orphan task",
            "description": "but executor didn't pre-create a dir",
            "project_id": None,
        }
        sys_prompt = adapter._build_system_prompt(task)
        assert sys_prompt is None

    def test_system_prompt_built_when_auto_project(self):
        adapter = self._load_adapter()
        task = {
            "title": "Build my blog",
            "description": "please",
            "project_id": None,
            "project_directory": "/opt/niwa/data/projects/my-blog-abc123",
        }
        sp = adapter._build_system_prompt(task)
        assert sp is not None
        assert "project_create" in sp
        assert "/opt/niwa/data/projects/my-blog-abc123" in sp
        assert "area" in sp and "proyecto" in sp
        assert "Build my blog" in sp

    # Rule content tests moved from _build_prompt → _build_system_prompt
    # after PR-45. The constraints are the same; only their carrier
    # changed (user msg → system prompt).

    def test_system_prompt_mentions_tmp_as_common_mistake(self):
        adapter = self._load_adapter()
        task = {
            "title": "x", "project_id": None,
            "project_directory": "/root/.niwa/data/projects/p-abc",
        }
        sp = adapter._build_system_prompt(task)
        assert "/tmp/" in sp

    def test_system_prompt_has_no_contradictory_blacklist(self):
        """PR-42 blacklist of /root/, /home/, /var/, /opt/ collided
        with project_directory in sudo installs. PR-43 removed it;
        PR-45 keeps it removed now that rules live in the system
        prompt."""
        adapter = self._load_adapter()
        task = {
            "title": "x", "project_id": None,
            "project_directory": "/root/.niwa/data/projects/p-abc",
        }
        sp = adapter._build_system_prompt(task)
        assert "`/root/...`" not in sp
        assert "`/home/...`" not in sp
        assert "`/var/...`" not in sp
        assert "`/opt/...`" not in sp

    def test_system_prompt_states_positive_start_rule(self):
        adapter = self._load_adapter()
        pdir = "/root/.niwa/data/projects/blog-abc"
        task = {"title": "x", "project_id": None, "project_directory": pdir}
        sp = adapter._build_system_prompt(task)
        assert "start with" in sp.lower()
        assert sp.count(pdir) >= 2

    def test_system_prompt_includes_concrete_tool_call_example(self):
        adapter = self._load_adapter()
        task = {
            "title": "Build a blog",
            "project_id": None,
            "project_directory": "/opt/niwa/data/projects/blog-xyz",
        }
        sp = adapter._build_system_prompt(task)
        assert "```json" in sp
        assert '"name"' in sp
        assert '"area"' in sp
        assert '"directory"' in sp
        assert '"description"' in sp

    def test_system_prompt_tells_claude_relative_paths_work(self):
        adapter = self._load_adapter()
        task = {
            "title": "x", "project_id": None,
            "project_directory": "/opt/niwa/data/projects/p-abc",
        }
        sp = adapter._build_system_prompt(task)
        assert "relative" in sp.lower()

    def test_build_command_passes_append_system_prompt_flag(self):
        """PR-45 — Bug 34 parte 4: when ``append_system_prompt`` is
        provided, ``_build_command`` must add the CLI flag. Without
        this the system prompt is silently dropped and we're back to
        the PR-44 behaviour (rules in user message → ignored)."""
        adapter = self._load_adapter()
        cmd = adapter._build_command(
            model="claude-sonnet-4-6",
            append_system_prompt="some rules go here",
        )
        assert "--append-system-prompt" in cmd, (
            "PR-45: the rules live in the system prompt. If this "
            "flag isn't in the CLI command, they never reach Claude "
            "as a system prompt — which was the whole point of PR-45."
        )
        idx = cmd.index("--append-system-prompt")
        assert cmd[idx + 1] == "some rules go here", (
            "The argument right after the flag must be the rules "
            "text literally — no quoting, Popen handles it."
        )

    def test_build_command_omits_flag_when_rules_none(self):
        """No project_directory → ``_build_system_prompt`` returns
        None → ``_build_command`` called without the flag. This is
        the path chat-style tasks and tasks with explicit
        project_id follow; they should not carry a dangling flag."""
        adapter = self._load_adapter()
        cmd = adapter._build_command(
            model="claude-sonnet-4-6",
            append_system_prompt=None,
        )
        assert "--append-system-prompt" not in cmd

    def test_system_prompt_preserves_conversational_escape_hatch(self):
        adapter = self._load_adapter()
        task = {
            "title": "resume lo del informe anual",
            "project_id": None,
            "project_directory": "/opt/niwa/data/projects/informe-xyz",
        }
        sp = adapter._build_system_prompt(task)
        assert "conversational" in sp.lower() or "skip" in sp.lower()
