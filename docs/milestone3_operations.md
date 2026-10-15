# Persistent batch processing

The operator workflow below describes the React application. Migration details
record the original batch milestone. Authentication and authorization added later
are described in [the security guide](milestone6_security.md).

Milestone 3 preserves the existing RapidOCR → hybrid LangGraph → SQLite workflow.
It adds bounded ingestion, persistent jobs/items/attempts, run idempotency keys and
snapshots, retained sources and derived repository search indexes. ZIP support is
deferred: this release accepts PDF, PNG and JPEG only.

## Migration and preservation

Repository initialization applies the additive batch-v1 migration once. Before
migrating a populated database it creates a consistent SQLite backup beside it,
named `DATABASE.before_batch_v1.TIMESTAMP.db`. Existing document IDs, hashes,
results, reviews and run records are preserved. New nullable run columns do not
invent historical snapshots. Derived search data is backfilled. FTS5 trigram search
serves substrings of three or more characters; shorter queries scan normalized text
without parsing every document JSON. Metadata, currency/amount, PO and batch queries
have indexes. Amount indexes are approximate floating-point filtering only; financial
aggregation uses Decimal and separates currencies. Migration needs disk space for
the backup and source storage. No dependencies or enterprise security system added.

## Operator workflow

Open Documents > Upload, choose one or many authorized files and inspect the
accepted/rejected preview rows. Confirm retention and Groq processing explicitly,
then submit; processing starts automatically. Repeated
requests with the same submission token return the same batch. Only accepted files
are saved. Monitor saved state in Processing jobs. For explicit operator-controlled
processing, run the worker from the project:

```
uv run --python 3.14.6 python scripts/batch_worker.py --database data/idp.db
```

Optionally add `--batch BATCH_ID` and `--max-items 50`. The worker is initially serial,
bounded to 50 items per command. Run again for remaining work. Browser-triggered
processing runs in the FastAPI server; it is not an independent worker service.
Browser refresh reads saved progress. Following application/worker shutdown, resume
from Processing jobs or restart the worker command. An OS file lock prevents
simultaneous workers for the same database;
SQLite transactions protect each claim/update. Restart closes an interrupted attempt
and requeues its item. A unique operation key recovers a committed run after a crash
between document persistence and item completion without another API call or run.

Terminal states are completed, duplicate, review_required and failed. Only failed
items can be explicitly retried (five total attempts). Attempt history remains.
Completed items are not retried. Forced reprocessing must be selected on submission
and resets the existing review decision, as the single-document workflow does.
One failure does not discard other items. Provider transient errors use the existing
bounded backoff; auth and malformed requests are not retried indefinitely. Persisted
business errors are allowlisted messages, never raw exceptions or provider bodies.

After all items become terminal, deterministic invoice verification is rerun against
available POs for referenced invoices (including newly ambiguous references). It reruns validation, anomaly and
routing checks without another model call. It never approves unresolved references,
and does not add a processing run or reset a human review decision. Order does not
determine the final PO result. Failed PO items remain genuine missing references
until a successful retry and subsequent reconciliation. New batch item snapshots
show post-batch reconciliation; processing-run snapshots retain original run output.

## Retention and limits

Sources use random local filenames beneath `batch_sources` beside the selected
database. The original filename is display metadata only. Retention eligibility is
30 days after submission. There is **no automatic deletion** in this milestone:
eligible files remain until an operator explicitly removes them after reviewing
recovery needs. Do not remove sources needed by queued/failed jobs. Retry requires a
present, intact source; hashes are checked before processing. Existing legacy files
and single uploads have no retrospectively retained original. Failed jobs retain
their sources for investigation.

This is a trusted local prototype. On Windows files inherit the account/directory
ACL; on Unix source permissions are private. It adds no authentication, encryption,
RBAC or compliance guarantees. Run on localhost and protect the source directory.
All UI source paths are resolved within this dedicated folder.

Limits: 50 files, 20 MB each, 100 MB total, 10 pages/PDF, 100 pages/batch, 16 million
pixels per decoded image/rendered PDF page, 40 million rendered pixels/PDF. Damaged,
encrypted, repaired PDFs, animated images and extension/signature mismatches are
rejected before OCR. File-level rejection is displayed in preview; rejected files
are not batch items. The HTTP adapter applies request-size and same-origin checks;
this local prototype is not a hardened public upload gateway.

## Results and repository

Reopen any batch from persisted history. Inspect current/terminal states, safe
failures, attempts, measured durations, validation/cross-document/routing outcomes
and financial totals. Download JSON/CSV summaries. Amount totals count unique invoice
document IDs once, keep currencies separate and show safety categories. These are
extracted values, not payments, throughput benchmarks or time savings. CSV formula
prefixes are escaped; JSON preserves original values.

Repository filters add currency, amount and batch membership. Export is explicitly
limited to 5,000 filtered records; narrow filters rather than silently truncating.
Open linked POs, retained batch source previews and new processing-run snapshots.
Earlier run snapshots remain unavailable. Department pages remain filters, not
authorization. No later business-rule/security milestone is implemented here.
