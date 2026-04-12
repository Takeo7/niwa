---
name: niwa
description: Personal AI task manager and project orchestrator. Manages tasks, projects, memory, and autonomous execution.
---

# Niwa — Your Personal Task & Project Manager

You have access to Niwa, a personal AI-powered task and project management system. Use Niwa tools to help the user organize their work, remember things, and track progress.

## Available Tools

### Task Management
- **niwa__task_list** — List tasks. Accepts filters: status, project_id, include_done.
- **niwa__task_get** — Get full details of a specific task by ID.
- **niwa__task_create** — Create a new task. Required: title. Optional: description, status (default: "pendiente"), priority ("alta"/"media"/"baja"), project_id, due_at, area, source (set to "openclaw").
- **niwa__task_update** — Update a task's fields (title, description, priority, due_at, etc.)
- **niwa__task_update_status** — Change a task's status. Valid statuses: inbox, pendiente, en_progreso, bloqueada, waiting_input, revision, hecha, archivada.

### Projects
- **niwa__project_list** — List all projects with task counts.
- **niwa__project_get** — Get project details by slug.
- **niwa__project_context** — Get rich context about a project: description, recent tasks, file structure. Use this before working on a project.

### Memory
- **niwa__memory_store** — Store a persistent memory. Params: content (text), category (optional).
- **niwa__memory_search** — Search memories by query text.
- **niwa__memory_list** — List all stored memories.

### Execution Support
- **niwa__task_log** — Append a log entry to a task (for progress tracking).
- **niwa__task_request_input** — Request input from the user for a task that's blocked.

## Task Lifecycle

Tasks flow through these states:
1. **inbox** — Captured but not triaged
2. **pendiente** — Ready to be worked on
3. **en_progreso** — Currently being worked on
4. **bloqueada** — Blocked by something
5. **waiting_input** — Waiting for user input
6. **revision** — Done, awaiting review
7. **hecha** — Completed
8. **archivada** — Archived

## Best Practices

- When the user asks to "remember" something, use `niwa__memory_store`.
- When the user asks about their tasks/projects, use `niwa__task_list` or `niwa__project_list` first.
- When creating tasks from user requests, always set `source: "openclaw"` so Niwa knows the task came from you.
- Use `niwa__project_context` before doing any work related to a specific project.
- Keep task descriptions clear and actionable.
- Use priorities: "alta" for urgent, "media" for normal, "baja" for low.
- Log progress with `niwa__task_log` when working on multi-step tasks.

## Language

The user's Niwa instance uses Spanish for status names and UI. Use Spanish for task statuses (pendiente, en_progreso, hecha, etc.) but communicate with the user in whatever language they use.
