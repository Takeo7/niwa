# Niwa v0.2 — State Machines

Reference document for the canonical state machines in v0.2.
Implementation lives in PR-02; this document defines the contracts.

---

## 1. `tasks.status`

The task status tracks the **human-visible lifecycle** of a task.

### States

| State | Meaning |
|-------|---------|
| `inbox` | Captured but not yet triaged. No execution. |
| `pendiente` | Ready for execution. The router evaluates and creates a `routing_decision`. |
| `en_progreso` | A `backend_run` is actively executing. |
| `waiting_input` | The task (or its active run) needs human input before it can continue. **Canonical state for "needs your answer".** |
| `revision` | Human review of completed deliverables. Not used for mid-execution input requests. |
| `bloqueada` | Blocked by an external dependency or unresolved issue. |
| `hecha` | Completed successfully. |
| `archivada` | Archived — no longer active, retained for history. |

### Transitions

```
inbox ──────────> pendiente

pendiente ──────> en_progreso
pendiente ──────> bloqueada
pendiente ──────> archivada

en_progreso ───> waiting_input
en_progreso ───> revision
en_progreso ───> bloqueada
en_progreso ───> hecha
en_progreso ───> archivada

waiting_input ─> pendiente
waiting_input ─> archivada

revision ──────> pendiente
revision ──────> hecha
revision ──────> archivada

bloqueada ─────> pendiente
bloqueada ─────> archivada
```

### Rules

- A `routing_decision` is created when a task transitions to `pendiente`.
- A `backend_run` is created when a worker claims and starts execution (task moves to `en_progreso`).
- `waiting_input` is set by `task_request_input` (MCP tool) or by a `backend_run` entering `waiting_input` status. **Never use `revision` for this.**
- `revision` is for final human review of deliverables only.
- `_pipeline_status()` must count `waiting_input` as a pending-intervention state (active workload).

### Illegal transitions (examples)

- `inbox` -> `en_progreso` (must go through `pendiente` first)
- `hecha` -> `en_progreso` (completed tasks don't re-enter execution)
- `archivada` -> any (archived is terminal; create a new task if needed)
- `waiting_input` -> `en_progreso` (must go back to `pendiente` for re-routing)

---

## 2. `backend_runs.status`

The run status tracks the lifecycle of a **single execution attempt** by a backend.

### States

| State | Meaning |
|-------|---------|
| `queued` | Run created, waiting for a worker to pick it up. |
| `starting` | Worker claimed the run, initializing the backend. |
| `running` | Backend is actively executing. Heartbeat expected. |
| `waiting_approval` | Execution paused — needs human approval to continue (e.g., dangerous operation, high cost). |
| `waiting_input` | Execution paused — needs human input to continue. |
| `succeeded` | Execution completed successfully. |
| `failed` | Execution failed (error, crash, bad exit code). |
| `cancelled` | Execution cancelled by human or system. |
| `timed_out` | Execution exceeded its time budget. |
| `rejected` | Approval was denied — run will not continue. |

### Transitions

```
queued ──────────> starting

starting ────────> running

running ─────────> waiting_approval
running ─────────> waiting_input
running ─────────> succeeded
running ─────────> failed
running ─────────> cancelled
running ─────────> timed_out

waiting_approval > running       (approved)
waiting_approval > rejected      (denied)

waiting_input ──> queued         (input provided, re-queue)
waiting_input ──> cancelled
```

### Rules

- Each run belongs to exactly one `routing_decision` and one `backend_profile`.
- A run records `previous_run_id` and `relation_type` when it is a fallback, resume, or retry of a prior run.
- `heartbeat_at` is updated periodically while status is `running`. A missing heartbeat beyond the configured threshold triggers timeout detection.
- Terminal states: `succeeded`, `failed`, `cancelled`, `timed_out`, `rejected`. Once a run reaches a terminal state, it does not transition again.
- On failure, the system may create a **new** run with `relation_type='fallback'` or `'retry'`, linked via `previous_run_id`. The failed run's record is never overwritten.

### Relation types

| Type | When | What happens |
|------|------|-------------|
| `fallback` | Current backend fails and fallback chain exists | New run created with different `backend_profile_id` |
| `resume` | Human provides input or unblocks a paused run | New run created with same backend, carrying prior context via `session_handle` |
| `retry` | Transient failure (timeout, rate limit) | New run created with same backend, fresh attempt |

---

## 3. Interaction between task status and run status

| Run event | Task status effect |
|-----------|--------------------|
| Run created (`queued`) | Task stays `pendiente` or moves to `en_progreso` when `starting` |
| Run reaches `running` | Task is `en_progreso` |
| Run reaches `waiting_approval` | Task stays `en_progreso` (approval is run-level, not task-level) |
| Run reaches `waiting_input` | Task moves to `waiting_input` |
| Run reaches `succeeded` | Task moves to `revision` (if review required) or `hecha` |
| Run reaches `failed` | If fallback exists: new run created, task stays `en_progreso`. If no fallback: task moves to `bloqueada` |
| Run reaches `cancelled` | Task moves to `bloqueada` or `archivada` depending on context |
| Run reaches `timed_out` | Same as `failed` — fallback or `bloqueada` |
| Run reaches `rejected` | Task moves to `bloqueada` |

---

## 4. Approval lifecycle

Approvals are created by the backend adapter or router when a dangerous or expensive operation is detected.

```
pending ───> approved ───> (run resumes)
pending ───> denied ─────> (run moves to rejected)
pending ───> expired ────> (run moves to cancelled or timed_out)
```

Approval fields: `approval_type`, `reason`, `risk_level`, `status`, `requested_at`, `resolved_at`, `resolved_by`, `resolution_note`.

Approval is mandatory for:
- Filesystem writes outside the project workspace
- File deletion
- Shell commands outside a configured whitelist
- Network access when the capability profile disallows it
- `quota_risk >= medium`
- `estimated_resource_cost > threshold`
