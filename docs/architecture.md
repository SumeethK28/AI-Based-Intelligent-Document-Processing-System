# Application architecture

React is the application's frontend framework. The TypeScript interface in
`frontend/` uses Vite, Tailwind and Radix components. FastAPI serves its production
build and exposes authenticated endpoints over the shared Python services.

## Start the application

Use Python 3.14.6 and uv from the project root:

```powershell
uv sync --frozen --python 3.14.6
npm --prefix frontend ci
npm --prefix frontend run build
uv run --frozen --python 3.14.6 python -m idp.web.api
```

Open `http://127.0.0.1:8000`. The FastAPI adapter serves the built frontend from
`frontend/dist/`. Build that directory before starting the application. For a new
installation only, create the first administrator privately using:

```powershell
uv run --frozen --python 3.14.6 python scripts/manage_security.py bootstrap
```

No default user or password is created. Set `IDP_DATABASE_PATH` to an isolated
database for acceptance; the default remains `data/idp.db`. The worker, account
bootstrap and existing CLI commands are preserved. Never use the original database
for synthetic acceptance tests.

## Interface and processing

`frontend/` contains React, TypeScript, Vite, Tailwind and Radix components. Overview,
Documents, My Work, Insights and Administration remain permission-aware destinations.
`src/idp/web/api.py` is the same-origin, loopback HTTP adapter over shared services.

One upload form accepts one or many PDF/PNG/JPEG files: preview and bounds checks,
explicit AI/source-retention consent, durable submission, processing and saved job
progress. Limits remain 50 files / 100 MB per upload, with 20 MB per file. Pillow
is an explicit dependency for safe image-header validation and research tools.
The legacy single-document API and CLI remain supported.

The processing path remains ingestion/OCR → classification → extraction → validation
→ anomaly detection → cross-document verification → business policy → routing,
followed by persisted departmental/human review and scoped analytics/export.
Post-job deterministic reconciliation handles invoices uploaded before their POs.
No automatic retraining or external ERP/CRM integration is claimed.

The adapter uses HttpOnly/SameSite cookies, same-origin mutation checks, session-scoped
repositories and existing permission boundaries. Downloads remain expiring, one-use,
session-bound and hash-verified. User-supplied actor identities, internal capabilities
and database paths are never accepted. The adapter binds only to loopback and disables
access logs to protect download grants. Public network deployment requires a separate
security review; the cookie configuration is intended for the local prototype.

Shared agents, OCR, extraction, review, policy, storage, authentication, migrations,
retention and worker implementations are retained. No database or research archive
is deleted or reset. This guide provides the supported application startup commands.

## Verification and research tools

```powershell
uv run --frozen --python 3.14.6 python scripts/run_tests.py
uv run --frozen --python 3.14.6 python -m unittest discover -s tests -p 'test_*.py' -v
npm --prefix frontend run build
```

Persisted batch retry and review-history assertions exercise shared services directly. HTTP
regressions cover login/logout, role scopes, read-only auditors, safe review decisions,
document-specific notes, no browser bootstrap, read-only page data without model
initialization, job recovery and protected exports. Existing policy HTTP lifecycle
coverage verifies draft, preview and activation behavior. Automated model responses are
simulated; the existing real RapidOCR PDF integration test remains.

The five operational scripts stay in `scripts/`; component tests stay under
`tests/components/`, HTTP/pipeline integrations under `tests/`, and the 15 offline
research tools under `research/tools/`. Private `data/`, `results/` and
`research_sources/` remain ignored. Prior evaluations and the existing research
release tag retain their original evidence and measurements.
