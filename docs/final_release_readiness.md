# Research prototype release and paper readiness

## Current application checkpoint

The frontend is React and TypeScript, built with Vite, Tailwind and Radix.
FastAPI serves the frontend and authenticated HTTP endpoints. Python 3.14.6 and
uv manage RapidOCR, Groq, LangGraph, policy, review and SQLite services. See the
[architecture guide](architecture.md) for supported installation and startup commands.

The current branch is a local review candidate. Changes have not been staged,
committed, tagged, pushed or merged. The existing research tag is unchanged.

## Release checklist

- [x] React is the sole frontend; production assets are served by FastAPI.
- [x] Python 3.14.6 is pinned; uv's frozen lock resolves compatible dependencies.
- [x] Shared processing, review, security, worker and migration logic is preserved.
- [x] Component suite: 114 tests passed in the executed removal verification.
- [x] Pipeline/HTTP integration suite: 25 tests passed in the executed verification.
- [x] Production frontend type-check and build passed.
- [x] Actual loopback server served HTML, JS/CSS and authenticated page-data routes
  against a disposable database without model calls.
- [x] Hash comparison confirmed 584 historical data/evaluation files unchanged.
- [x] README files and private research archives are unchanged.
- [x] Original security and release reports were archived byte-for-byte with hashes
  under ignored `results/frontend_cleanup_*/original_documents/` before guide updates.
- [x] Review the final inventory and whitespace/secret exclusion audit.
- [ ] Obtain approval before staging, committing, tagging, pushing or merging.

These automated checks use simulated model providers; the existing PDF integration
executes real RapidOCR. They do not constitute a new live Groq evaluation or new
browser acceptance session. Previously accepted React visuals remain unchanged.
No accuracy, speed or human-productivity improvement is claimed by frontend cleanup.

## Safe demonstration procedure

Use a disposable database selected with `IDP_DATABASE_PATH`; never reprocess the
original database for a demonstration. Build the frontend and start the loopback
application, then sign in using privately created local test accounts.

1. Verify administrator/reviewer permissions and denied cross-department access.
2. Open Documents > Upload, preview a synthetic invoice/PO/receipt/contract batch,
   explicitly consent to retention and external AI processing, and submit.
3. Monitor Processing jobs. Check successful, duplicate and failed items separately;
   retry only eligible failed items. Retain all measured errors and attempts.
4. Inspect extraction evidence, validation, cross-document checks, policy explanations
   and department routing. Confirm mismatches and unsupported contracts need review.
5. Review authorized cases through My Work. Verify optimistic revisions, immutable
   events and safe approval restrictions before accepting a decision.
6. Check scoped Insights and request separate fresh JSON/CSV downloads. Verify actual
   files and their record counts; do not count an HTTP response alone as browser delivery.
7. Test logout, expired/replayed download denial and role restrictions. Never share
   account passwords, API keys or download grants.

The upload API enforces 20 MB per file, 50 files and 100 MB per submission, with
signature, page and pixel checks. Cookie authentication, same-origin mutations,
server-side department scopes and one-use protected downloads are retained. The
loopback prototype still requires independent hardening for public deployment.

## Preserved evaluation evidence

Earlier measured outputs, historical model responses, screenshots, original research
documents and all databases remain under ignored local archives. Original release
reports are retained exactly; their historical counts, stack descriptions and UI
acceptance limitations must not be relabeled as results of the current frontend.
The latest cleanup verification remains in its existing ignored results directory.
Use the preserved original evidence when reconstructing past experiments.

## Research contribution and submission gaps

A defensible contribution is a measured systems study of conservative, evidence-grounded
layout recovery and document reconciliation with explicit abstention and human review.
Classification/extraction call the model; deterministic graph stages are not independent
autonomous reasoning agents. Evidence occurrence is not complete semantic correctness;
SQLite history is not cryptographic tamper-proofing. No automatic retraining, production
scalability or measured human time savings follows from the current implementation.

Prior small synthetic pilots establish feasibility only. Before submission:

- Freeze model/configuration, prompts, policy versions, dataset hashes and runtime.
- Independently annotate held-out seller/client layouts, reversed columns, multiple
  tax IDs, missing/conflicting evidence and degraded OCR.
- Evaluate identical inputs under LLM-only and hybrid configurations. Report correct
  recoveries, incorrect recoveries, abstentions, false escalations and uncertainty.
- Separate actual live-model results from simulated-provider regression checks.
- Run a balanced human-versus-assisted protocol with actual operators, identical tasks,
  correctness gates and observed times; do not invent participants or savings.
- Reconcile paper diagrams and stack claims with React/FastAPI, RapidOCR, Groq,
  LangGraph and SQLite. Report dataset size and unsupported document boundaries.
- Deduplicate incomplete references and verify primary-source bibliographic metadata.

Suggested paper structure: bounded problem and contribution; verified related work;
implemented architecture and trust boundaries; recovery and conflict rules; dataset and
paired protocol; measured accuracy/safety/latency; error analysis and limitations.

## Git inventory and artifact protection

Review frontend-removal deletions, dependency/lock changes, current documentation,
Python pin and adapted component/API tests together. Shared service edits are comments
only. Public README files remain unchanged. No databases, retained documents, model
weights, results, screenshots, credentials or original research files belong in Git.
Private credential TOML files, environment files and generated assets remain ignored.
Inspect staged files only after explicit authorization; do not rewrite prior history.
