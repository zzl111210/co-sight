# NetHeal-Agent repository instructions

This file applies to the whole repository. The current competition work lives on `dev`; do not modify or push `main` unless the repository owner explicitly asks.

## Read first

Before changing NetHeal, read [`docs/netheal/CODEX_HANDOFF.md`](docs/netheal/CODEX_HANDOFF.md). It contains the architecture, file map, API contracts, lifecycle, test baseline, extension recipes, known limitations, and recommended next steps.

## Project boundary

- NetHeal is a 5G private-network operations scenario built on top of Co-Sight.
- Reuse the existing Co-Sight Planner, concurrent DAG scheduler, Actor, tool registration, and generic workbench.
- Keep NetHeal-specific code under `app/netheal/`, its API under `cosight_server/deep_research/routers/netheal.py`, and its cockpit under `cosight_server/web/netheal.*`.
- Do not turn synthetic benchmark numbers into claims about a real operator network.
- Configuration commands must remain simulation-only and `dry_run=true` until a separately reviewed real-network adapter and authorization mechanism exist.

## Safety and collaboration

- Never commit `.env`, API keys, local databases, logs, or `work_space/**` outputs.
- The local model configuration belongs in the ignored `.env`; only templates or variable names may be documented.
- Preserve unrelated teammate changes and inspect `git status` before editing.
- Do not force-push shared branches. Fetch first and use normal fast-forward collaboration.
- `scripts/*` is ignored by the inherited `.gitignore`; the tracked NetHeal acceptance script was intentionally force-added. Check ignore rules before adding another script.

## Required verification

Run these from the repository root after relevant changes:

```powershell
node --check cosight_server\web\js\netheal.js
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
powershell -ExecutionPolicy Bypass -File .\scripts\run_netheal_acceptance.ps1
git diff --check
```

Expected baseline at this handoff: 12 automated tests pass and NetHeal acceptance reports 5/5 cases passed.

## Common entry points

- Start server: `.\.venv\Scripts\python.exe cosight_server\deep_research\main.py`
- NetHeal cockpit: `http://127.0.0.1:7788/cosight/netheal.html`
- Generic Co-Sight workbench: `http://127.0.0.1:7788/cosight/`
- API prefix: `/api/netheal/v1`
- Scenario catalog: `app/netheal/data/scenarios.json`
- Domain lifecycle/RBAC: `app/netheal/domain.py`
- Orchestration service: `app/netheal/service.py`
- Tool implementation: `app/netheal/network_toolkit.py`
- Root-cause ranking: `app/netheal/diagnosis_engine.py`
- Frontend behavior: `cosight_server/web/js/netheal.js`
- Frontend layout: `cosight_server/web/styles/netheal.css`

