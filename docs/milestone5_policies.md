# Configurable policies and enterprise intelligence

## Architecture and safety audit

The existing graph classified, extracted, validated, detected anomalies, verified
invoices against POs, then routed. Validation hardcoded base mandatory fields, OCR
evidence, supported dates, parsed amounts, arithmetic tolerance 0.02 and two-party
contract checks. Anomalies used a nominal 100000 threshold, negative totals,
unverified extraction evidence, identical supplier/buyer names and validation failures.
PO checks required a unique reference match, complete totals and currencies, normalized
supplier equality and absolute amount difference at most 0.02. Routing blocked unknown
types, validation/evidence failures, unresolved PO issues and every non-low risk result.
Review additionally protected original evidence, disallowed erasing a known PO reference,
preserved independent high risk, used revisions and invalidated invoices after PO changes.
Batch reconciliation preserved human restrictions and independent anomalies.

Milestone 5 keeps those checks. Policy configuration is pinned when extraction completes,
before validation. The graph then runs validation → anomaly → cross-document verification
→ business policy → routing. Classification/extraction prompts and fallback code are
unchanged. Policy evaluation never calls Groq. Review and batch reconciliation bind the
recorded policy, not the currently active version. The cross-document verifier also
blocks a referenced PO with failed checks or a restrictive human decision during initial
processing, closing the earlier gap between processing and review approval checks.

## Rule schema and bounds

`mandatory_fields` covers all four types and can add their supported optional fields;
protected base fields cannot be removed. `high_value_thresholds` maps uppercase currency
codes to positive finite amounts; an absent currency uses `unknown_currency_threshold`,
which cannot exceed the baseline 100000. Currency thresholds do not imply conversion.
`po_tolerance` is an absolute same-currency difference in [0,1]; default 0.02.
`arithmetic_tolerance` is in [0,0.02]; default 0.02. These are deliberate conservative
prototype bounds, not percentage tolerances or configurable exchange rates.
`require_po_reference` and `require_contract_expiration` strengthen required information.
`duplicate_identifiers` remains `review`, matching normalized type, identifier and party
on distinct sources. `departments` maps types to supported business teams, after guards
pass. `escalate_all` adds manual review. No unknown keys or safety-disable switches exist.

Supplier equality, currency equality, complete unique referenced PO matching, verified
evidence, contract party/date/structure requirements and non-low risk remain protected.
A missing PO reference is optional by default, matching previous behavior; when enabled
it becomes a mandatory failure rather than being listed as an optional omission.
An engine/version failure uses protected defaults for checks and forces manual review.

Every new result stores `policy_version_id`, normalized `policy_config`, individual
`rule_outcomes` with passed/failed/not-applicable status and escalation attribution,
`policy_failed_rules`, and measured `policy_latency_ms`. Validation messages and anomaly
codes remain available alongside policy explanations. Guarded review events record policy
versions and outcomes; model outputs, OCR and earlier events remain append-only.

## Lifecycle, confirmation and rollback

The Business Rules workspace prominently describes trusted-local use. Typed names are
prototype identifiers, not authorization. Drafts are immutable validated JSON snapshots;
editing means creating another draft. A full preview against current stored documents is
required before activation. It stores outcomes, a document/revision/result fingerprint
and the active-generation number. Changes to documents or another activation invalidate
that preview. Subset previews are exploratory and cannot authorize activation. Empty
repositories cannot activate until test documents exist. Full previews are limited to
1000 documents; larger repositories need a future scalable preview workflow.

Activation needs an identifier, reason, explicit confirmation and a fresh full preview.
It only updates the active pointer for future checks. Historical versions can be previewed
and reactivated as rollback; activations remain traceable. No earlier document is silently
rewritten, reevaluated, approved or assigned a fabricated historical policy version.

Ordinary corrections, decisions and batch reconciliation use a document's recorded version.
Legacy unversioned results use protected baseline defaults and remain marked unversioned.
Explicit reevaluation requires the current active version, document revision, actor,
reason and confirmation. It records a complete new deterministic result in an append-only
review event; it does not invent a model run or edit a processing original. It resets
approval to pending, preserves rejected/correction/escalation restrictions, and always
requires another human decision. PO reevaluation invalidates dependent invoice approvals.
Independent high-risk flags remain protected even under a newer permissive threshold.

## Migration and recovery

The additive policy-v1 migration creates `policy_versions`, `policy_active`,
`policy_previews` and `policy_activations`, plus append-only triggers and an activation
history index. It inserts default policy 1 for future processing without editing legacy
documents, processing originals or review events. Repository initialization applies batch,
review and policy migrations in that order. Populated databases receive consistent SQLite
backups before each missing migration, named DATABASE.before_policy_v1.TIMESTAMP.db (and
the corresponding earlier migration backups when needed). Policy schema/default insertion
is transactional and rechecked after acquiring a write lock.

The Milestone 4 rollback point is commit afbcd517ed693e34a2b46c721311a0c5547650e8.
For code rollback preserve all new files, use that commit in a separate checkout and a
database COPY. Never reset/delete the current database or restore a backup over newer
review records. A restored database backup excludes later writes; retain the current
database separately and reconcile later records before any operational restore.
Operational policy rollback instead reactivates a historical policy after preview.

## Analytics definitions

Document filters select unique current records by UTC received date and optional type,
department, status, decision, search, currency, amount and batch membership. Invoice totals
use latest extracted fields once per source hash, separated by currency and eligibility,
supplier, received day, PO status and high-value flag. Unparseable totals are excluded and
counted; unspecified currency is separate. These are invoice values, never paid balances,
revenue or transactions. Distinct sources with duplicate business identifiers remain
visible duplicate indicators rather than silently removing potentially different records.

Eligibility requires a normal department workflow, passed validation, low risk, no PO
issues and no restrictive human decision. Manual review and rejection are separate.
Backlog excludes approved/rejected cases; age is since receipt, not measured turnaround.
Correction and intervention rates use distinct affected documents over cohort documents;
event counts are separate. Run/duplicate counts include all stored runs for that document
cohort, including later runs. Legacy events and timings are unavailable, never invented.

Batch cohorts use job creation date and optional batch ID; other document filters do not
apply because queued/failed items may have no document. Completion/failure fractions use
terminal items only; completed, duplicate and review-required items count as successful
technical outcomes. Retries count items with multiple attempts, with failed attempts
reported separately. Single-upload failures before persistence are not recorded.
End-to-end timings use nonduplicate successful run snapshots with actual recorded duration;
batch attempt timings are separate. Median and nearest-rank p95 show sample counts.
No manual-effort, realized-savings or processing-speed improvement is inferred.

## Reproducible verification

Use Python 3.14.6 and uv:

```
uv run --python 3.14.6 python scripts/run_tests.py
uv run --python 3.14.6 python -m unittest discover -s tests -v
uv run --python 3.14.6 python research/tools/evaluate_policies.py
```

The evaluator creates a new results directory and isolated UAT database, 14 labeled
synthetic rule scenarios, expected/observed baseline and proposed decisions, false
acceptance/escalation denominators, explanations and latency repetitions. It measures
deterministic policy behavior, not OCR/classification/extraction accuracy. No model or OCR
calls occur in that evaluation. It also migrates a consistent copy of the original
database and verifies legacy values, integrity, foreign keys and unchanged original hash.
The default timestamp output preserves earlier reports. Browser evidence and actual
test outcomes are saved separately under results; this directory remains ignored by Git.

Limitations: no authentication/RBAC, cryptographic audit protection, payments, legal
execution, compliance certification, scalable previews above 1000 documents, historical
timing reconstruction or industrial-volume performance claims. The policy editor uses
described JSON categories; dedicated guided controls can be added in a later UI increment.
