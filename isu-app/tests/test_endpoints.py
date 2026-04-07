#!/usr/bin/env python3
"""Unit tests for Desk API endpoints.

Runs HTTP requests against a Desk server. By default targets
http://127.0.0.1:8080. Override with DESK_TEST_URL env var.

Auth is handled by logging in with DESK_USERNAME/DESK_PASSWORD
and extracting the session cookie from the Set-Cookie header.
"""

import json
import os
import re
import subprocess
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request


def _detect_env(var, default, container="isu"):
    """Return env var value, falling back to Docker container env if unset."""
    val = os.environ.get(var)
    if val:
        return val
    try:
        out = subprocess.check_output(
            ["docker", "inspect", container, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        for line in out.splitlines():
            if line.startswith(f"{var}="):
                return line.split("=", 1)[1]
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    return default


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("DESK_TEST_URL", "http://127.0.0.1:8080")
DESK_USER = _detect_env("DESK_USERNAME", "arturo")
DESK_PASS = _detect_env("DESK_PASSWORD", "yume1234")

_session_cookie = None


# ---------------------------------------------------------------------------
# Module setup — login once, extract session cookie manually
# ---------------------------------------------------------------------------
def setUpModule():
    global _session_cookie
    login_data = urllib.parse.urlencode(
        {
            "username": DESK_USER,
            "password": DESK_PASS,
        }
    ).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/login",
        data=login_data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    # Use a raw opener that does NOT follow redirects so we can read Set-Cookie
    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # prevent following redirects

    opener = urllib.request.build_opener(NoRedirectHandler)
    try:
        resp = opener.open(req)
        set_cookie = resp.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        # 302 raises HTTPError when redirect_request returns None
        set_cookie = e.headers.get("Set-Cookie", "")
    # Extract desk_session from Set-Cookie header
    m = re.search(r"desk_session=([^;]+)", set_cookie)
    if m:
        _session_cookie = m.group(1)
    else:
        print("WARNING: Could not extract session cookie.", file=sys.stderr)
        print(f"Set-Cookie: {set_cookie}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def api_request(method, path, data=None):
    """Make an HTTP request, return (status_code, parsed_json_or_text)."""
    url = f"{BASE_URL}{path}"
    payload = None
    headers = {}
    if data is not None:
        payload = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    if _session_cookie:
        headers["Cookie"] = f"desk_session={_session_cookie}"
    req = urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(req)
        body = resp.read().decode()
        try:
            return resp.status, json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return e.code, body


def api_get(path):
    return api_request("GET", path)


def api_post(path, data):
    return api_request("POST", path, data)


def api_patch(path, data):
    return api_request("PATCH", path, data)


def api_delete(path):
    return api_request("DELETE", path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLogin(unittest.TestCase):
    def test_login_with_valid_credentials_redirects(self):
        """POST /login with correct credentials should return 302."""
        login_data = urllib.parse.urlencode({"username": DESK_USER, "password": DESK_PASS}).encode()
        req = urllib.request.Request(
            f"{BASE_URL}/login",
            data=login_data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirectHandler)
        try:
            resp = opener.open(req)
            status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 302)

    def test_login_with_bad_credentials_returns_401(self):
        """POST /login with wrong password should return 401."""
        login_data = urllib.parse.urlencode({"username": DESK_USER, "password": "wrong_password"}).encode()
        req = urllib.request.Request(
            f"{BASE_URL}/login",
            data=login_data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            resp = urllib.request.urlopen(req)
            status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 401)


class TestHealth(unittest.TestCase):
    def test_health_returns_ok(self):
        status, body = api_get("/health")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))


class TestTasks(unittest.TestCase):
    def test_list_tasks(self):
        status, body = api_get("/api/tasks")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)

    def test_create_update_delete_task(self):
        # Create
        status, body = api_post(
            "/api/tasks",
            {
                "title": "Unit test task",
                "description": "Created by test_endpoints.py",
                "area": "personal",
                "priority": "media",
            },
        )
        self.assertIn(status, [200, 201])
        self.assertTrue(body.get("ok"))
        task_id = body["id"]

        # Verify task appears in list
        status, body = api_get("/api/tasks")
        self.assertEqual(status, 200)
        task_ids = [t["id"] for t in body]
        self.assertIn(task_id, task_ids)

        # Update
        status, body = api_patch(
            f"/api/tasks/{task_id}",
            {
                "priority": "alta",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))

        # Delete
        status, body = api_delete(f"/api/tasks/{task_id}")
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))


class TestProjects(unittest.TestCase):
    def test_list_projects(self):
        status, body = api_get("/api/projects")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)

    def test_projects_have_required_fields(self):
        """Each project should have at least an id and name."""
        status, body = api_get("/api/projects")
        self.assertEqual(status, 200)
        if len(body) > 0:
            project = body[0]
            self.assertIn("id", project)
            self.assertIn("name", project)


class TestSettings(unittest.TestCase):
    def test_get_settings(self):
        status, body = api_get("/api/settings")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, dict)

    def test_save_and_read_settings(self):
        status, body = api_post(
            "/api/settings",
            {
                "__test_key": "test_value",
            },
        )
        self.assertEqual(status, 200)

        status, body = api_get("/api/settings")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("__test_key"), "test_value")

        # Cleanup
        api_post("/api/settings", {"__test_key": ""})


class TestDashboard(unittest.TestCase):
    def test_get_dashboard(self):
        status, body = api_get("/api/dashboard")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, dict)

    def test_dashboard_contains_expected_keys(self):
        """Dashboard response should contain task/project summary data."""
        status, body = api_get("/api/dashboard")
        self.assertEqual(status, 200)
        # At minimum, dashboard should return a dict with some data
        self.assertGreater(len(body), 0)


class TestStats(unittest.TestCase):
    def test_get_stats(self):
        status, body = api_get("/api/stats")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, dict)


class TestMetrics(unittest.TestCase):
    def test_get_metrics(self):
        status, body = api_get("/api/metrics")
        self.assertEqual(status, 200)
        self.assertIsInstance(body, dict)


class TestTaskEdgeCases(unittest.TestCase):
    def test_create_task_without_title_still_succeeds(self):
        """POST /api/tasks without title is accepted (server assigns empty title)."""
        status, body = api_post("/api/tasks", {"description": "no title"})
        self.assertIn(status, [200, 201])
        # Cleanup
        if body.get("id"):
            api_delete(f"/api/tasks/{body['id']}")

    def test_get_nonexistent_task(self):
        """GET /api/tasks/<bad_id> should return 404."""
        status, _ = api_get("/api/tasks/nonexistent-id-000")
        self.assertEqual(status, 404)

    def test_patch_nonexistent_task(self):
        """PATCH /api/tasks/<bad_id> should return 404."""
        status, _ = api_patch("/api/tasks/nonexistent-id-000", {"priority": "alta"})
        self.assertEqual(status, 404)


class TestUnauthenticated(unittest.TestCase):
    def test_api_without_auth_returns_401(self):
        """Requests without session cookie should get 401."""
        req = urllib.request.Request(f"{BASE_URL}/api/tasks", method="GET")
        try:
            resp = urllib.request.urlopen(req)
            status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 401)


class TestNotFound(unittest.TestCase):
    def test_unknown_api_route(self):
        status, _ = api_get("/api/nonexistent")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
