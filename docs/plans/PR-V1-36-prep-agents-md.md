# PR-V1-36-prep: AGENTS.md for external task implementers

## Why

We are switching the implementer role of the maintenance flow from
Claude Code (which loaded `CLAUDE.md` automatically) to an external
agent (Codex Desktop with GPT-5.5). The new implementer needs the
same project rules but in a self-contained file it loads at start.

## What

- New file: `AGENTS.md` at repo root.
- Self-contained translation of `CLAUDE.md` rules adapted for an
  external implementer.
- Cross-references `CLAUDE.md` as source of truth (yields on
  contradiction).
- Documents the split flow: orchestrator (Claude Code) vs
  implementer (external agent), and the human bridge.
- Disambiguates "codex" terminology (internal `codex-reviewer`
  Claude agent vs external Codex Desktop OpenAI product).

## Cap

S+ (~170 LOC, mostly markdown). Calibrated band from
`FOUND-20260426-loc-cap-pattern.md` and
`FOUND-20260426-brief-loc-estimation.md` retro inputs:
S = 100-130, S+ = 130-200.

## Out of scope

- HANDBOOK section on the split flow. Defer to a follow-up so this
  PR stays focused; the AGENTS.md itself documents the flow well
  enough for the implementer.
- Renaming the `codex-reviewer` internal agent. Defer; AGENTS.md
  notes the ambiguity explicitly so the external implementer is
  not confused.

## Tests

No code changes. Test baseline (196 passed, 1 skipped backend; 18
passed frontend) must remain unchanged. The orchestrator verifies
via GitHub MCP that no `.py` / `.ts` / `.tsx` files are touched.

## Codex review

Not required — markdown-only PR, no critical area touched.
