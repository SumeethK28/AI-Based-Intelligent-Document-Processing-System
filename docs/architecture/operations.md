# Installation, onboarding and storage

## Start a selected installation

From the project root, use Python 3.14.6 and uv:

```powershell
uv sync --frozen --python 3.14.6
npm --prefix frontend ci
npm --prefix frontend run build
uv run --frozen --python 3.14.6 python -m idp.web.api
```

FastAPI serves `frontend/dist/` at `http://127.0.0.1:8000`. Optional configuration:
`IDP_WEB_PORT`, `IDP_DATABASE_PATH`; code fallback database is `data/idp.db`.
Use the same selected path for web, security CLI and worker. Do not print API keys.
Set `IDP_DATABASE_PATH` explicitly for an isolated acceptance database. The completed
clean-install cutover selects `data/operational/organization.db` through the local
private configuration. Historical databases remain intact; no demonstration accounts
or processing records were carried into the selected installation.
Further production configuration changes require explicit approval.

An absent database creates schema and protected baseline business policy, with zero
users, sessions, documents, jobs and review records. Restart is idempotent; it imports
no demonstrations. Initial policy metadata is intentional system history. Login,
logout and restart never clear employee work.

## First Administrator and employee access

For a genuinely new installation only, the authorized local operator runs:

```powershell
uv run --frozen --python 3.14.6 python scripts/manage_security.py --database 'PATH_TO_SELECTED_DATABASE' authorize-setup
```

Open the printed private credential-file path locally. Its value is not printed.
Refresh the website: First-time setup appears only with a valid local authorization.
Enter the setup code, a unique name and a 12–128-character password. Authorization
expires after 15 minutes; creation/consumption is atomic. A new authorization revokes
the previous one; initialized stores reject another bootstrap. No account is created
by the authorization command. Existing interactive CLI `bootstrap` is an alternative.

Ordinary employees see Sign in / Create account. They choose their own credentials,
not privileged roles. The form requests Finance, Procurement, Expense Processing,
Legal, Document Review, or Operations / Other. This preference grants no permissions.
Requests remain pending with zero access. Administrator → People shows the preference,
verifies the employee, and selects the actual role/department or declines the request.
Reviewer roles retain their server-selected department even if a client sends another.
Approval/decline requires confirmation and the current request revision, and records
the authenticated Administrator. Declined requests cannot sign in or later be approved;
their password hash is cleared. A duplicate request does not reopen a declined request.
Duplicate requests never replace credentials or reveal existing accounts. Setup and
registration have separate bounded attempt budgets. Operator instructions belong in
this guide, not every employee's login screen.

The additive department-request migration adds nullable `requested_department`,
`rejected_by` and `rejected_at` columns. Populated stores receive a timestamped
`.before_department_requests_v1.*.db` backup before migration. Legacy rows remain
unchanged; requests without a preference can still be reviewed. To preserve the old
status constraint without rebuilding history, declined requests retain `status=pending`
with `rejected_at` set; both pending-list and approval predicates exclude them.
Schema creation is automatic when starting against the selected database. Read-only
historical audits must not construct a repository. Keep backups private.

Returning employees retain authorized assignments, queues, documents/history,
decisions and summaries. Deactivation, session revocation, secure password changes,
Administrator resets and last-Administrator safeguards remain enforced.

## Worker and diagnostic commands

```powershell
uv run --frozen --python 3.14.6 python scripts/batch_worker.py --database 'PATH_TO_SELECTED_DATABASE' --max-items 50
uv run --frozen --python 3.14.6 python scripts/run_agents.py path/to/document.pdf
uv run --frozen --python 3.14.6 python scripts/process_document.py path/to/document.pdf
```

Worker/agent CLI honor `IDP_DATABASE_PATH` and `.env`; explicit worker `--database`
overrides it. These are trusted local tools, not employee HTTP routes. The diagnostic
`process_document.py` runs the deterministic baseline, not the authenticated product.
It writes no JSON by default; `--output path/to/report.json` requests an export.
Normal React upload accepts one or many files through durable batches. Legacy
single-upload API remains compatible. No working CLI entry point is removed.

## Storage lifecycle and retention policy

| Category | Owner/location | Lifecycle |
|---|---|---|
| Operational records | Selected SQLite DB | Fields, metadata, runs/versions, cases, jobs, policies, audit history persist. No automatic record deletion. |
| Retained originals | `batch_sources/` beside DB | Randomized names, stored hashes, scoped access. Reuse only authorized, linked, contained, hash-verified sources. Preserve referenced originals. |
| Temporary uploads/OCR | OS temp / memory | Single-upload directories cleaned on success and failure. Rendered pages/OCR stay in memory. Crash leftovers need inspection. |
| Research outputs | Private `results/`, evaluators `research/tools/` | Explicit experiments only; ordinary processing creates no experiment directory. Freeze prior evidence. |
| Logs/diagnostics | Console or operator-selected file | API access logs disabled to protect grants. No automatic file logger added. Review optional diagnostics at 30 days; archive before approved disposal. |
| JSON/CSV exports | In-memory response → Downloads | No permanent server export copy; expiring grant metadata remains in DB. User owns downloaded copies. |
| Backups | Private `data/backups/` and existing migration siblings | Verified recoverable copies, no automatic expiry. Keep source dependencies with database evidence. |

Sources receive a 30-day eligibility timestamp, **not** an automatic deletion deadline.
Existing governance allows only explicitly confirmed cleanup of expired unlinked
failed sources after at least five exhausted attempts. Active cases, linked processing
originals, audit references and dependencies remain protected. Damaged/missing or
unauthorized sources are not reused. Duplicate events remain recorded even if model
results and source bytes are reused. Paths never come from clients.

No timer sweeps research, audit or security history. Before removing an orphan
`idp_web_*` temporary directory, verify no active process owns it and obtain approval
for any private files. Never recursively sweep shared temp roots. Log age does not
prove evidence is disposable. This is a conservative policy, not a new cleanup daemon.

## Safe fresh-database cutover

1. Inventory databases, sidecars, sources and experiment dependencies.
2. Back up privately; verify every archived hash and SQLite integrity.
3. Build an empty candidate using existing migrations, without accounts.
4. Verify onboarding/processing in a separate disposable database; leave candidate empty.
5. Obtain approval for the exact inventory and configuration cutover.
6. Stop the selected app/worker, select the candidate, then authorize its first Admin.
   Preserve original database/source files for rollback.

Never erase old audit rows or copy demo users to simulate a clean installation.
ZIP copies preserve bytes but do not rewrite absolute retained-source paths. Restoring
to a different root needs an explicit restore plan. The approved cutover is complete;
these steps describe the procedure for any future cutover. The current installation
still requires local authorization before its first Administrator can be created.

## Verification

```powershell
uv run --frozen --python 3.14.6 python scripts/run_tests.py
uv run --frozen --python 3.14.6 python -m unittest discover -s tests -p 'test_*.py' -v
npm --prefix frontend run build
node --experimental-strip-types --test frontend/tests/presentation.test.mjs
```

Tests use isolated synthetic data and simulated LLMs; existing PDF OCR tests use real
RapidOCR. Live Groq/research evaluators are separate and opt-in. Explain count changes
instead of silently narrowing discovery. Do not claim unexecuted browser checks.
