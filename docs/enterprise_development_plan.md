# Enterprise platform assessment and incremental plan

Audit: 11 October 2026. Baseline commit `0defb2f`; working tree clean at start.
Scope of this increment: Milestone 1 assessment and Milestone 2 dashboard/navigation.
Current stack: React/TypeScript, FastAPI, Python 3.14.6, uv, RapidOCR, Groq,
LangGraph and SQLite. The assessment below records the original milestone scope;
see [architecture](architecture.md) for the current runtime and startup instructions.

## Evidence and research limits

Inspected source modules, database repository/schema, all existing test suites,
ingestion/preprocessing, prompts, validators, graph, UI and evaluation scripts.
Read `results/final_verification_report.md` and `results/quality/quality_report.md`
and their measured artifacts. Five invoice/PO cases achieved 32/32 expected fields
in the latest hybrid run; eight synthetic receipt/contract cases achieved 60/60
scalar fields, with initial failures retained. These small related/clean samples
do not establish production accuracy. Model output and hybrid fallback must be
evaluated separately. Prior browser UAT is not verification of the new interface.

No original project report, research paper, related-work section or architecture
document was found in the workspace; docs/notebooks were empty. The supplied
master brief is the available intended architecture. No related-work or novelty
claim can be reviewed without those source documents. Existing results stay intact.

## Architecture mapping and gaps

| Stage | Actual implementation | Remaining gap |
|---|---|---|
| Ingestion | PDF/JPEG/PNG single-file loading | Signature/size/page limits, persistent source retention, mixed batches/ZIP safety |
| Preprocessing | OpenCV helpers exist | Not connected to OCRProcessor; no evaluated rotation/noise strategy |
| OCR | RapidOCR, page regions and confidence | PDFs materialize all pages; unbounded page/pixel memory; OCR is serial |
| Classification/extraction | Real Groq with bounded retries, typed output | Two calls/document, quotas; self-reported confidence is not accuracy |
| Hybrid fallback | Evidence-grounded currency/party/receipt fallback; certified seller tax column | Conservative abstention; complex/multipage layouts not evaluated |
| Validation | Required/optional fields, evidence, dates/arithmetic; safe contract support limits | Semantic evidence association and business-specific policies |
| Anomalies | Deterministic amounts/party/evidence rules | Not learned fraud detection; thresholds not currency-specific |
| Cross verification | Stored PO reference/vendor/currency/total checks | PO lookup scans JSON; no line-item matching; business duplicates not checked |
| Business rules | Constants embedded in agents | No persisted versions, administrative validation or decision rule audit |
| Human review | Decision/notes persisted, no external execution | No actors, roles, corrections/revalidation, immutable events or locking |
| Routing | Safe status/department assignment after checks | Assignment alone is not an actionable/authorized workspace |
| Dashboard | Four technical tabs; history/review and JSON export work | 500/1000 row caps undercount KPIs; no filters, operational overview or currency totals |
| Persistence | Unique SHA-256 documents, transactional runs, duplicate cache and forced reprocess | Runs have no snapshots/status/latency; decisions overwritten; no jobs/failures/source paths |

Intended flow places cross verification before anomalies and adds business rules,
final decisions and dashboard. Actual proven graph is Classification → Extraction
→ Validation → Anomaly Detection → Cross-Document Verification → Routing.
Cross verification merges its issues into anomalies/risk before routing. Keep this
tested order for Milestone 2; a later rule stage must preserve mandatory/evidence/PO
guards. Do not reorder the working graph for cosmetic conformity.

## Recommended architecture

Keep the existing processing services and graph. Introduce a thin UI console with
reusable components and a read-only operations query service over SQLite. Load OCR
and Groq lazily when processing starts, rather than on dashboard startup. Compute
counts in SQL over all matching unique records, not a capped UI list. Retrieve only
page-sized summaries; load OCR/full JSON only for the selected record. Monetary
aggregation uses Decimal and existing parsing; group currency and review/risk
category separately. Unknown currency must stay unknown and is never converted.

Later migrations should be additive, versioned and reversible: jobs/batch items,
source retention metadata, run snapshots/outcomes/latency, review events and row
versions, rule versions and actor/department membership. Back up before migration;
never delete/reset existing records. Legacy missing measurements stay unavailable.

Use a bounded serial batch runner first (durable per-item state, retry failed items,
PO ordering/reverification considered). Add small bounded concurrency only after
provider quotas and SQLite contention are measured. Defer brokers/distributed
workers and framework/database migrations until observed workload justifies them.

## Navigation and milestone boundaries

1. Overview: actionable real-data counts, department backlog, exceptions and recent activity.
2. Process Documents: existing single-document workflow and downloads preserved.
3. Document Repository: selected-record details, server-side metadata filtering/pagination.
4. Review Center: existing decision/notes workflow with evidence and escalation context.
5. Department Workspaces: real department-filtered queues (not authorization).
6. Business Analytics: full-cohort distributions and currency/category-separated invoice values.
7. Business Rules: inspect current rules; explicitly read-only until versioned engine exists.
8. Audit & Settings: prototype boundaries, processing history and data-handling information.

No fake charts, savings, latency, success trends or turnaround KPIs. Current run
schema records successful/cached submissions only; absent failure/latency/event
timestamps mean these metrics cannot be recovered reliably. Label this explicitly.

## Risk assessment

High: no authentication/RBAC (trusted local prototype only); external AI sends OCR
to Groq; original uploads are temporary and not retained; approval has no actor or
immutable audit; file extension-only validation and unbounded PDF/pixel ingestion.
Do not expose this service publicly or claim enterprise compliance.

Medium: hard-coded nominal amount threshold across currencies; two agent API calls
plus retries; PO JSON scanning; full-page image materialization; reprocess overwrites
latest result and resets review; duplicate business identifiers can differ in bytes.
An approval inside this prototype records a judgement, never payment/ERP execution.

UI risk: huge JSON panels and technical terms; expensive eager OCR/model creation;
metrics conflate pending department decisions with exceptional manual-review cases.
Address honest labels, empty states and full-cohort counts now; do not disguise
unfinished authorization/rules/correction features as working controls.

## Prioritized milestones and acceptance

| Milestone | Increment | Verification gate |
|---|---|---|
| 1 | This audit and plan | Actual implementation/stages and measured limitations documented |
| 2 | Theme-aware sidebar console, reusable views, real overview/query filters | All existing tests plus counts/currency/filter/navigation tests; real browser checks on backup DB; original DB preserved |
| 3 | Persistent mixed batch jobs, partial failure/retry, safe exports/ZIP limits; indexed identifier search | Idempotency, ZIP traversal/bomb rejection, partial completion, quota/write contention tests |
| 4 | Correct/revalidate preview, immutable review events, locking, claim/reassign | Original evidence retained; stale write rejection; mandatory/PO guards enforced on decisions |
| 5 | Validated/versioned rules and operational/financial BI | Conflict tests; rule attribution; currency/category denominators; no invented KPIs |
| 6 | Prototype authentication + server-side authorization, retention/source retrieval, limits | Cross-department denial, uploads/signatures/limits, retrieval and formula-injection tests |
| 7 | Controlled OCR-only/LLM-only/hybrid/full experiments | Same source data/settings, precision/recall denominators, abstentions/false approvals, noisy/rotated/multipage cases; no invented savings |

At each gate run existing tests, focused new regressions, browser checks where
available and report actual failures/untested functionality. No commit/push without
explicit approval. Milestone 2 introduces no schema migration or new dependencies.
