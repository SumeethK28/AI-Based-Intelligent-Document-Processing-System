# Human review and department operations

Milestone 4 adds a single deterministic review service shared by Review Center and
Department Workspaces. It does not implement authentication, RBAC or a versioned
business-rule engine. Typed names are unauthenticated prototype identifiers. Team
assignment routes operational ownership and never grants access or changes validated
business routing. Procurement additionally surfaces unresolved invoice/PO references.

## Workflow

Search/filter the queue by type, routing department, received date, risk, case status,
operator, identifiers, currency/amount or batch. Priority/risk and oldest received
records come first; age uses the actual UTC received timestamp, not an invented SLA.
Approved/rejected cases can be included explicitly. Inspect the retained source beside
fields, OCR/evidence, fallback/human provenance, PO comparison and validation flags.
Legacy or single-upload sources may be missing; that limitation is displayed.

Enter a prototype operator identifier. Every action needs a reason. Corrections
require a deterministic preview and explicit confirmation. Decisions and reassignment
also require confirmation. Save changes, then inspect the revalidation before making
a separate decision. No Groq requests occur during review. Invalid corrections can be
retained as audited drafts; they stay in manual review and cannot be approved.

Corrected values and evidence must be supported by original OCR, and the evidence quote
must contain the corrected value. A previously known PO reference cannot be cleared to
bypass verification. Missing mandatory fields, unverifiable evidence, unresolved POs,
high risk and unsupported contracts block approval. Exactly two distinct supported
contract parties are required; existing unsupported-structure warnings cannot be erased
by the editor. Text presence does not prove label/party association: inspect the actual
source and record a reason. Where OCR cannot support a visually apparent correction,
escalate; this milestone has no authenticated source-attestation override.

Approve, reject, request correction or escalate explicitly. Approval records review
judgment only. Rejection and requests/escalation keep normal business processing
blocked. Claim a case, assign/reassign a team/operator, update open/in-review/on-hold
status, or set priority. Status updates cannot approve/close/reopen a terminal case
silently; use a recorded decision. Claiming another operator's case requires explicit
reassignment. Authenticated ownership enforcement is intentionally not claimed.

## Migration and history

Repository initialization applies review-v1 after batch-v1. A populated database is
first backed up consistently with SQLite to DATABASE.before_review_v1.TIMESTAMP.db.
The additive migration creates processing_versions, review_events and review_cases,
plus revision and processing_version_id on documents. Current available legacy output
is captured as legacy_current_snapshot; no historical decisions/events are invented.
Legacy original columns remain unchanged. Existing current decision/case state is
represented separately from unavailable historical events.

Each new/reprocessed model output is captured as an immutable version, including OCR.
Human edits change the current working result, never the preserved processing original.
Events link the processing version, actor kind (prototype operator or system), timestamp,
old/new values, decision, reason, notes, revision change and validation/risk/PO results.
Rule versions remain null because a versioned rule engine is not implemented. Reserved
system: identifiers cannot be entered through the human-review mutation API.

SQLite triggers reject normal UPDATE/DELETE of events and processing versions. This
is append-only application history, not cryptographic tamper protection; a database
administrator can alter the schema. All writes use a transaction and expected revision.
Stale actions fail rather than overwrite. Corrections revalidate again inside the save
transaction; decisions recheck current fields and available PO records. An unexplained
high-risk signal is preserved conservatively. Existing static validation/anomaly/routing
rules apply; this does not introduce later business-rule configuration.

Forced reprocessing captures a new model version, retains earlier originals/events,
resets the current review to pending, releases assignment and reopens the case. A system
event records that reset. Batch reconciliation records a system event when checks change
and cannot overturn rejection, correction requests or escalation. Duplicate uploads
retain the existing review/version and do not create a fictitious model version.

Correcting, rejecting/escalating or reprocessing a referenced PO also invalidates
dependent invoices with a system event. Earlier invoice approvals return to correction
review instead of silently trusting the changed PO. Fresh invoice approval checks the
PO's current validation, risk and human decision; a rejected or restricted PO blocks it.

## Compatibility and verification

The older repository.update_review entrypoint now requires expected_revision and a
nonempty reason in notes; it delegates to guarded decisions and identifies its caller
as prototype:compatibility-api. Unsafe or unversioned approvals are deliberately rejected.
UI edits/confirmations are tied to the displayed revision; changed records prompt fresh
inspection. Notes remain document-specific. Authentication and full correction-claim
authorization remain future milestones, not implied by these safeguards.

Run component and integration regressions through Python 3.14.6 and uv:

```
uv run --python 3.14.6 python scripts/run_tests.py
uv run --python 3.14.6 python -m unittest discover -s tests -v
```

Tests and browser UAT use isolated databases. No original database is deleted/reset and
no earlier evaluation report is overwritten. Review actions execute no payment, legal
agreement, external business transaction or live model request.
