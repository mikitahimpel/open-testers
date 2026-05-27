# open-testers

open-testers is an OSS, AI-driven QA testing agent — inspired by TesterArmy.
You write tests in plain English as a list of typed steps in YAML; a pluggable
LLM decides each browser action, Playwright drives Chromium, and every run
captures a video, per-step screenshots, and a JSON trace.

## Status

MVP — not production-ready. The agent core, executor, LLM providers,
credential store, and memory store all work end-to-end, but a lot of the
TesterArmy surface area is intentionally out of scope for now.

Not built yet:

- No web dashboard
- No HTTP API
- No GitHub PR bot
- No Vercel / Coolify integrations
- No mobile testing or iOS simulator support (the `platform: mobile` field is
  accepted by the schema but only `web` actually runs)
- No Agent Mail / temporary inbox provisioning
- No captcha solving
- No parallel run orchestration

## Install

```bash
git clone <repo>
cd open-testers
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium
```

Python 3.11 or newer is required (see `pyproject.toml`). The `playwright install
chromium` step downloads the browser binary that the executor drives.

## Quickstart (no API key)

The repo ships with `examples/example.yaml` — a three-step smoke test against
`news.ycombinator.com`. Run it with the stub provider:

```bash
open-testers run examples/example.yaml --dry-run
```

`--dry-run` forces the deterministic stub LLM, which returns canned actions
without contacting any external service. The point is to validate the full
pipeline — Playwright launches Chromium, each step records a screenshot, the
video file is produced, and a `trace.json` is written — before you wire up a
real provider.

Artifacts land in `runs/<run-id>/`:

```
runs/<run-id>/
  screenshots/
    step-00.png
    step-01.png
    step-02.png
  video.webm
  trace.json
```

## Environment variables

| Var | Purpose | Default |
|---|---|---|
| `OPEN_TESTERS_LLM` | Provider: `claude` / `openai` / `ollama` / `stub` | `stub` |
| `ANTHROPIC_API_KEY` | Required when `OPEN_TESTERS_LLM=claude` | — |
| `OPENAI_API_KEY` | Required when `OPEN_TESTERS_LLM=openai` | — |
| `OPEN_TESTERS_OLLAMA_HOST` | Ollama HTTP host | `http://localhost:11434` |
| `OPEN_TESTERS_OLLAMA_MODEL` | Ollama model | `llava` |
| `OPEN_TESTERS_PASSPHRASE` | Pre-fills the cred-store passphrase | (prompt) |

The encrypted credential store lives at `~/.open-testers/credentials.json`
(AES-GCM with a PBKDF2-derived key). The memory store lives at
`./open-testers.memory.json` in the project root by default.

## YAML test schema

A test file has a title, an optional `projectUrl` that's opened before step 0,
and a list of typed steps. The 5 step shapes are defined in
`open_testers/schema.py`.

```yaml
title: My test
description: Optional free text
platform: web              # web | mobile (only web works today)
projectUrl: https://...    # optional; navigated to before step 0
steps:
  - type: act
    title: Open the homepage

  - type: assert
    title: The page shows the navbar

  - type: login
    title: Sign in
    credentialId: <uuid-from-cred-list>   # optional
    temporaryEmail: false                 # optional, default false

  - type: files
    title: Upload the avatar
    fileIds: [<uuid>]

  - type: screenshot
    title: Snapshot the dashboard
```

### Step types

- **`act`** — Free-form action. The LLM picks browser actions
  (click / fill / press / navigate / scroll / wait) until the goal in `title`
  is met.
- **`assert`** — Verification. The LLM uses `assert_visible` / `assert_text`
  actions to check the claim in `title`.
- **`login`** — Sign-in flow. Carries an optional `credentialId` (UUID from
  `open-testers cred list`) and an optional `temporaryEmail` flag. In the MVP
  the executor's `use_credential` action is a no-op; the field exists so the
  schema and LLM context stay forward-compatible.
- **`files`** — File upload. Carries a list of `fileIds`. In the MVP the
  executor's `upload_file` action is a no-op.
- **`screenshot`** — Capture the current page. The per-step pre-screenshot is
  always taken; this step type makes that the explicit objective.

## Command reference

All commands come from the `open-testers` console script wired up in
`pyproject.toml`. Run any command with `--help` to see the live flag set.

### `open-testers run`

```bash
open-testers run TEST.yaml \
  [--llm claude|openai|ollama|stub] \
  [--dry-run] \
  [--headed | --headless] \
  [--output DIR] \
  [--max-actions N] \
  [--viewport WxH] \
  [--memory-file PATH] \
  [--no-memory]
```

- `--llm` overrides `OPEN_TESTERS_LLM`. Default: `stub`.
- `--dry-run` short-circuits to the stub provider regardless of env / `--llm`.
- `--headed` launches Chromium with a visible window; default is headless.
- `--output` is the artifact root (default `runs/`); each run gets a
  `runs/<run-id>/` subdirectory.
- `--max-actions` caps the inner `decide → execute` loop per step
  (default 25).
- `--viewport` is `WIDTHxHEIGHT`, default `1280x720`.
- `--memory-file` points at the project memory JSON (default
  `open-testers.memory.json` in cwd). `--no-memory` skips loading it.

Example:

```bash
OPEN_TESTERS_LLM=claude \
ANTHROPIC_API_KEY=sk-ant-... \
open-testers run examples/example.yaml --headed --output ./runs
```

Exit code is `0` on pass, `1` on fail, `2` on configuration / load errors.

### `open-testers cred`

Encrypted credential store at `~/.open-testers/credentials.json`. Every
operation prompts for the store passphrase unless `OPEN_TESTERS_PASSPHRASE`
is set in the environment.

```bash
open-testers cred add LABEL KIND --secret KEY=VALUE [--secret KEY=VALUE ...]
open-testers cred list
open-testers cred rm CRED_ID
```

`KIND` is one of:

- `username_password`
- `google_oauth`
- `github_oauth`
- `http_basic`
- `custom`

Examples:

```bash
open-testers cred add "ACME staging" username_password \
  --secret username=alice \
  --secret password=hunter2

open-testers cred list
# 9c5b...  ACME staging  username_password

open-testers cred rm 9c5b...
```

`cred add` prints the new credential's UUID on success — paste that into the
`credentialId` field of a `login` step.

### `open-testers memory`

Project-scoped store of hints the agent sees on every run. Sorted by
importance (`high` > `medium` > `low`) and capped at 100 entries.

```bash
open-testers memory add CATEGORY TITLE CONTENT [--importance high|medium|low] \
  [--memory-file PATH]
open-testers memory list [--memory-file PATH]
open-testers memory rm MEMORY_ID [--memory-file PATH]
```

`CATEGORY` is one of:

- `site_structure` — facts about the app under test (selectors, routes, etc.)
- `test_insights` — known flake patterns, timing quirks, gotchas
- `user_preferences` — operator-level preferences

Example:

```bash
open-testers memory add site_structure "Login route" \
  "The login form is at /auth/sign-in and uses #email and #password." \
  --importance high
```

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│  open-testers run examples/example.yaml --llm claude       │
└──────────────────────────────┬─────────────────────────────┘
                               │
               ┌───────────────┼───────────────┐
               │               │               │
         ┌─────▼──────┐  ┌─────▼─────┐  ┌──────▼─────┐
         │  schema    │  │  memory   │  │ credentials│
         │ (Pydantic) │  │  (JSON)   │  │ (AES-GCM)  │
         └─────┬──────┘  └─────┬─────┘  └──────┬─────┘
               └────────┬──────┴───────────────┘
                        │
               ┌────────▼─────────┐
               │   Runner (async) │
               │  ┌────────────┐  │   for each step:
               │  │ Playwright │  │     loop:
               │  │  Chromium  │  │       screenshot
               │  └─────┬──────┘  │       LLMProvider.decide()
               │        │         │       execute action
               │        ▼         │       until done/fail
               │  ┌────────────┐  │
               │  │LLMProvider │  │
               │  │ (pluggable)│  │
               │  └────────────┘  │
               └────────┬─────────┘
                        │
               ┌────────▼────────┐
               │  runs/<id>/     │
               │   screenshots/  │
               │   video.webm    │
               │   trace.json    │
               └─────────────────┘
```

The flow: `schema.load()` parses the YAML into a `TestDefinition`; the
`MemoryStore` reads `open-testers.memory.json` and renders the top entries as
LLM context; the `CredentialStore` exposes credential *labels* (never the
secrets) so the LLM can ask for `use_credential` by label. The `Runner` opens
a Playwright context with video recording, then for each step builds a
`StepContext` (current screenshot, page URL, DOM summary, memories, available
credential labels) and loops:

1. Capture screenshot + DOM summary.
2. Call `LLMProvider.decide(ctx)` for one `AgentAction`.
3. Execute the action (`click`, `fill`, `navigate`, `assert_visible`, …) and
   refresh the context.
4. Repeat until the LLM emits `done` (pass / fail) or `fail`, or
   `--max-actions` is hit.

When the run finishes, the runner closes the context (flushing the video),
renames the WebM to `video.webm`, and writes `trace.json` containing the full
`RunResult` (status, per-step actions with reasoning, durations, paths).

### LLM provider contract

Any provider is one class with one async method, defined in
`open_testers/llm/base.py`:

```python
class LLMProvider(ABC):
    async def decide(self, ctx: StepContext) -> AgentAction: ...
```

`StepContext` carries the screenshot (base64 PNG), the page URL/title, a short
DOM summary of visible interactive elements, the project memories, and the
labels of available credentials. `AgentAction.kind` is one of `click`, `fill`,
`press`, `navigate`, `wait`, `scroll`, `assert_visible`, `assert_text`,
`use_credential`, `upload_file`, `done`, `fail`. To add a provider, drop a
module under `open_testers/llm/` and wire it into the factory in
`open_testers/llm/__init__.py`.

## Comparison to TesterArmy

What we kept:

- The 5 typed step shapes (`act`, `assert`, `login`, `files`, `screenshot`).
- Memory categories (`site_structure`, `test_insights`, `user_preferences`)
  with `high` / `medium` / `low` importance.
- Credential kinds (`username_password`, `google_oauth`, `github_oauth`,
  `http_basic`, `custom`) stored encrypted at rest.
- The "prep-test" idea: per-run context assembled from memory + credential
  labels before the LLM sees the first screenshot.
- Per-run artifacts: video, screenshots, JSON trace.

What we omitted (for now):

- The web dashboard and HTTP API
- The GitHub PR bot and Vercel / Coolify deploy hooks
- Mobile / iOS simulator support
- Agent Mail (temporary inbox provisioning)
- Captcha solving
- Parallel run orchestration and queueing

open-testers is the agent core extracted and made self-contained. If you want
a dashboard or a PR bot, the surface to build on is `Runner.run()` and the
`trace.json` it emits — both are stable enough to script against.

## License

MIT — see LICENSE.
