# claude_stream_bug35.jsonl — stream-json fixture for Bug 35

**Source:** manually fabricated based on direct observation of
`claude -p --output-format stream-json --verbose` output, matching the
shape captured during the 2026-04-19 fresh-install reproduction of the
"crea un proyecto con un botón que se mueve y cambia estilos" task.

**What the fixture reproduces:**

- One `system` init event with `permissionMode=bypassPermissions`.
- Five `assistant` events whose `message.content[]` arrays each carry
  either a `text` block or a nested `tool_use` block — the real Claude
  CLI never emits top-level `{"type":"tool_use"}` messages; it wraps
  them inside `assistant.message.content[]`.
- Three `Write` tool_use calls (`index.html`, `style.css`, `app.js`),
  each followed by a `user` message carrying the `tool_result`.
- A final `result` event with `stop_reason="end_turn"`, `is_error=false`,
  empty `permission_denials` and successful `usage`.

**Why it exists:**

The pre-FIX `ClaudeCodeAdapter._classify_event` only counted top-level
`type=="tool_use"` messages. With the real nested shape, `tool_use_count`
came out as 0 and Bug 32's "executive + 0 tools + end_turn"
heuristic flagged the run as `clarification_required` even though Claude
had written three files on disk — the exact false positive the
FIX-20260420 brief is chartered to eliminate.

Tests that consume this fixture MUST assert:

1. Parser counts `tool_use_count == 3` after reading the stream.
2. With a non-empty filesystem diff over the project directory, the
   decision table returns `outcome == "success"`.
3. With an empty filesystem diff, the decision table returns
   `outcome == "needs_clarification"` (the old "just talked" bucket).

Do not edit the fixture without updating the checksums in any test that
asserts against specific byte ranges (no current tests rely on exact
bytes — assertions are over parsed events).
