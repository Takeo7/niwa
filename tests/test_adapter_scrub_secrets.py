"""Tests for ``backend_adapters.base.scrub_secrets`` (PR-50).

The executor injects a GitHub PAT into the subprocess env. If the
subprocess ever echoes it (git error with credentials embedded in a
URL, ``curl -v`` log, etc.) the adapter used to persist the raw text
to ``backend_run_events.message``, leaking it to the UI and DB dumps.

``scrub_secrets`` is applied to ``stderr`` before persistence as a
belt-and-braces guard.

Run: pytest tests/test_adapter_scrub_secrets.py -v
"""
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def test_redacts_classic_pat():
    from backend_adapters.base import scrub_secrets
    token = "ghp_" + "A" * 36
    msg = f"fatal: could not read Password for 'https://x-access-token@github.com': {token}"
    out = scrub_secrets(msg)
    assert token not in out
    assert "<redacted>" in out


def test_redacts_fine_grained_pat():
    from backend_adapters.base import scrub_secrets
    token = "github_pat_" + "B" * 22 + "_" + "C" * 59
    out = scrub_secrets(f"ERROR url https://{token}@github.com/foo/bar.git")
    assert token not in out
    assert "<redacted>" in out


def test_redacts_oauth_grant_prefixes():
    from backend_adapters.base import scrub_secrets
    for prefix in ("gho_", "ghu_", "ghs_", "ghr_"):
        token = prefix + "D" * 36
        out = scrub_secrets(f"token={token} stuff")
        assert token not in out
        assert "<redacted>" in out


def test_empty_and_none_tolerated():
    from backend_adapters.base import scrub_secrets
    assert scrub_secrets("") == ""
    assert scrub_secrets(None) is None  # type: ignore[arg-type]


def test_non_secret_text_unchanged():
    from backend_adapters.base import scrub_secrets
    text = "fatal: remote: Repository not found. (HTTP 404)"
    assert scrub_secrets(text) == text


def test_redacts_multiple_occurrences():
    from backend_adapters.base import scrub_secrets
    t1 = "ghp_" + "1" * 36
    t2 = "ghp_" + "2" * 36
    msg = f"retrying clone with {t1} then fallback {t2}"
    out = scrub_secrets(msg)
    assert t1 not in out and t2 not in out
    assert out.count("<redacted>") == 2
