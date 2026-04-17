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
    def _load_adapter(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter
        return ClaudeCodeAdapter

    def test_no_injection_when_project_id_set(self):
        adapter = self._load_adapter()
        task = {
            "title": "Existing project task",
            "description": "work on the thing",
            "project_id": "proj-abc",
            "project_directory": "/opt/niwa/data/projects/foo",
        }
        prompt = adapter._build_prompt(task)
        assert "project_create" not in prompt, (
            "Tasks already attached to a project must not be nagged "
            "to create a new one — the operator chose the project "
            "explicitly."
        )

    def test_no_injection_when_directory_missing(self):
        adapter = self._load_adapter()
        task = {
            "title": "Orphan task",
            "description": "but executor didn't pre-create a dir",
            "project_id": None,
        }
        prompt = adapter._build_prompt(task)
        assert "project_create" not in prompt, (
            "Without a pre-created directory there's nothing to tell "
            "Claude to write into — skip the instruction."
        )

    def test_injection_when_auto_project(self):
        adapter = self._load_adapter()
        task = {
            "title": "Build my blog",
            "description": "please",
            "project_id": None,
            "project_directory": "/opt/niwa/data/projects/my-blog-abc123",
        }
        prompt = adapter._build_prompt(task)
        assert "project_create" in prompt
        assert "/opt/niwa/data/projects/my-blog-abc123" in prompt
        assert "area" in prompt and "proyecto" in prompt, (
            "The prompt must include the exact args (name, area, "
            "directory) so Claude doesn't have to invent them."
        )
        # The task title should appear as the name suggestion so
        # Claude can pick something sensible even on the first try.
        assert "Build my blog" in prompt

    # PR-42 / PR-43 — Bug 34: the PR-38 prompt was too soft; the
    # PR-42 blacklist of fixed paths (/tmp/, /home/, /root/…) bit
    # back in prod because project_directory in a sudo install sits
    # under /root/.niwa/ — blacklist and main rule contradicted each
    # other and Claude evaded both by going to /tmp/. PR-43 states
    # the rule positively ("paths must start with pdir") and keeps
    # /tmp/ only as a common-mistake example.

    def test_prompt_mentions_tmp_as_common_mistake(self):
        """The /tmp/ mention stays as an example of what Claude
        defaults to — removing it would lose the specific warning
        that catches the most common failure mode."""
        adapter = self._load_adapter()
        task = {
            "title": "x", "project_id": None,
            "project_directory": "/root/.niwa/data/projects/p-abc",
        }
        prompt = adapter._build_prompt(task)
        assert "/tmp/" in prompt, (
            "Keep /tmp/ as the named common mistake Claude falls "
            "into — without that specificity the warning is vague."
        )
        assert "STRICT" in prompt, (
            "The instruction must read as imperative, not "
            "conditional — Claude treated the PR-38 wording as a "
            "suggestion."
        )

    def test_prompt_has_no_contradictory_blacklist(self):
        """The PR-42 blacklist of /root/, /home/, /var/, /opt/
        contradicted the main rule whenever ``project_directory``
        started with one of those prefixes. In a sudo install
        ``project_directory`` sits under ``/root/.niwa/``, so the
        blacklist said "never write to /root/" while the main rule
        said "MUST write under /root/.niwa/<slug>/". Claude resolved
        the ambiguity by going to /tmp/. PR-43 drops those fixed
        blacklists entirely."""
        adapter = self._load_adapter()
        task = {
            "title": "x", "project_id": None,
            "project_directory": "/root/.niwa/data/projects/p-abc",
        }
        prompt = adapter._build_prompt(task)
        # /root/ MUST NOT appear as a standalone blacklist entry
        # that would contradict the main rule.
        assert "`/root/...`" not in prompt, (
            "PR-43 removed the fixed /root/ blacklist — it "
            "contradicted project_directory in sudo installs. "
            "Use a positive rule instead: 'must start with <pdir>'."
        )
        # Same for the other fixed prefixes that could overlap with
        # a legitimate project_directory.
        assert "`/home/...`" not in prompt
        assert "`/var/...`" not in prompt
        assert "`/opt/...`" not in prompt

    def test_prompt_states_positive_start_rule(self):
        """The replacement for the blacklist: a positive rule that
        says exactly which prefix all paths must start with. This
        works regardless of where ``_auto_projects_root`` lives
        (/root/.niwa/, /opt/niwa/, /home/niwa/…)."""
        adapter = self._load_adapter()
        pdir = "/root/.niwa/data/projects/blog-abc"
        task = {
            "title": "x", "project_id": None,
            "project_directory": pdir,
        }
        prompt = adapter._build_prompt(task)
        # The pdir appears both as the target and framed as "must
        # start with". Any rewrite that drops the "must start with"
        # framing reintroduces the ambiguity.
        assert "start with" in prompt.lower(), (
            "State the rule positively: 'every path MUST start "
            "with <pdir>' — that's unambiguous even when pdir "
            "shares a prefix with a previously-blacklisted path."
        )
        # And the pdir itself must appear in the rule body (not
        # just in the task description).
        assert prompt.count(pdir) >= 2, (
            "pdir should appear at least twice: as the target dir "
            "and as the prefix in the 'must start with' rule. "
            "Once isn't enough to anchor the rule."
        )

    def test_prompt_includes_concrete_tool_call_example(self):
        """A literal JSON example of the `project_create` arguments
        eliminates ambiguity about what Claude should pass. Without
        an example, Claude sometimes guesses the schema."""
        adapter = self._load_adapter()
        task = {
            "title": "Build a blog",
            "project_id": None,
            "project_directory": "/opt/niwa/data/projects/blog-xyz",
        }
        prompt = adapter._build_prompt(task)
        # Look for a fenced json block that contains all four args.
        assert "```json" in prompt
        # The fenced block should include the four keys.
        assert '"name"' in prompt
        assert '"area"' in prompt
        assert '"directory"' in prompt
        assert '"description"' in prompt

    def test_prompt_tells_claude_relative_paths_work(self):
        """The PR-42 prompt tells Claude `cwd` is already the project
        dir, so relative paths "just work". Without this hint Claude
        defaults to absolute paths and misses the project dir."""
        adapter = self._load_adapter()
        task = {
            "title": "x", "project_id": None,
            "project_directory": "/opt/niwa/data/projects/p-abc",
        }
        prompt = adapter._build_prompt(task)
        assert "relative" in prompt.lower(), (
            "Tell Claude that relative paths resolve to the project "
            "dir. Absolute paths were the Bug 34 footgun."
        )

    def test_prompt_preserves_conversational_escape_hatch(self):
        """A task that is purely conversational ('resume this',
        'explain how X works') should be allowed to skip
        project_create without tripping the rule. The prompt must
        keep that escape hatch — otherwise the adapter becomes too
        rigid for non-artifact tasks."""
        adapter = self._load_adapter()
        task = {
            "title": "resume lo del informe anual",
            "project_id": None,
            "project_directory": "/opt/niwa/data/projects/informe-xyz",
        }
        prompt = adapter._build_prompt(task)
        assert "conversational" in prompt.lower() or \
               "skip" in prompt.lower(), (
            "The prompt must let conversational tasks off the hook — "
            "forcing project_create on a 'summarise X' would be "
            "noisy and create empty project rows."
        )
