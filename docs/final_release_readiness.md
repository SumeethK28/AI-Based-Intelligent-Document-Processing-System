# Research prototype release and paper readiness

Audit completed 2026-10-15, Asia/Calcutta. Evidence is preserved in
`results/final_release_20261014/`, named for the audit's start date. This is a local
research checkpoint, not a production release or a paper-submission approval.

## Release checklist

- [x] Review entry point, configuration, authentication, workers and additive migrations.
- [x] Use Python 3.14.6 and uv; keep the existing dependency lock unchanged.
- [x] Final component suite: 121/121 passed, 72.577 seconds.
- [x] Final integration suite: 11/11 passed, 10.689 seconds.
- [x] Reproduce and fix Unicode attachment headers with a real local HTTP test.
- [x] Keep related PO/invoice reads while excluding them from another team's review queue.
- [x] Block conflicts with an existing OCR-supported seller-layout certificate without
  overwriting model fields or copying baseline totals.
- [x] Preserve original data, supplied research documents and earlier evaluation outputs.
- [x] Verify Git whitespace and exclusions; leave index and Git history unchanged.
- [x] Save a proposed commit inventory and version label; do not create the commits/tag.
- [ ] Complete a fresh real-browser JSON/CSV download on the final build.
- [ ] Capture and inspect a full 1440-pixel desktop interface in a supported browser.
- [ ] Have the study coordinator dry-run the timer/record import workflow before recruitment.
- [ ] Obtain user approval before staging, committing, tagging or pushing this checkpoint.

The first two remaining UI checks are not claimed passed. Core exports were verified
against the actual HTTP endpoint and stored demonstration data. Browser download was
interrupted. The in-app browser did not honor the requested desktop viewport; actual
captures were approximately 842–947 pixels wide, with some controls clipped. They are
not evidence of complete desktop-width layout acceptance.

## Runtime and migration audit

`app/app.py` delegates to the authenticated Streamlit console. Default storage is
`data/idp.db`; `IDP_DATABASE_PATH` selects a different database. No first-browser-user
administrator registration or default administrator password exists. Bootstrap is local:

```
uv run --python 3.14.6 python scripts/manage_security.py bootstrap
uv run --python 3.14.6 streamlit run app/app.py
```

For another database, use the same path for the app and CLI:

```
uv run --python 3.14.6 python scripts/manage_security.py --database results/demo_new/idp.db bootstrap
uv run --python 3.14.6 python scripts/batch_worker.py --database results/demo_new/idp.db --max-items 50
```

The worker is a trusted local operator command using an internal server capability,
not a browser authentication bypass. Keep OS access restricted. CLI passwords are
prompted privately; never pass them as command arguments or place them in Git.

Repository initialization applies batch, review, policy and security migrations. They
use transactions, schema-presence checks and SQLite backups for populated databases.
Review/processing originals and policy/security events have append-only SQLite triggers;
legacy operator attribution remains unverified rather than being fabricated. These
triggers do not protect against an OS/SQLite administrator or provide cryptographic
audit integrity. Migration and idempotence behavior are covered by existing regressions.

Streamlit is configured for localhost, XSRF/CORS protection, 20 MB uploads and disabled
telemetry. The protected download helper uses localhost port 8767 and one-use 30-second
grants tied to current sessions. Two simultaneous app instances can compete for that
fixed port. The isolated demonstration used a test entry-point wrapper selecting 8769
only; authentication, processing, provider and application pages were real. This port
override must not be mistaken for proof of simultaneous default-port operation.

Warnings inspected: Windows LF-to-CRLF notices do not fail `git diff --check`;
Streamlit missing-ScriptRunContext messages occurred during bare/AppTest initialization.
No failing final tests were associated with those warnings. Groq quota exhaustion was a
real operational failure in the demo; it is retained and reported rather than suppressed.

## Executed demonstration and reproduction procedure

Use a new isolated database and project-generated synthetic files, never the original
database. The completed demo database is `results/final_release_20261014/demonstration.db`.
Disposable accounts were prepared locally. Their private credentials and all database
files stay under ignored results and must never be committed or published.

1. Sign in as the isolated administrator. Verify reviewer-only accounts lack intake,
   policy and account administration. Check backend permissions in addition to navigation.
2. Open Bulk Processing and upload all six PDFs from
   `results/milestone7_20261014/pilot_dataset/` with forced reprocessing unchecked.
   Confirm retention and external Groq processing explicitly, then submit/start.
3. Verify real RapidOCR/Groq execution, policy version 1, normal PO/receipt/contract
   routing, matched invoice and PO, mismatch escalation, and unsupported three-party
   contract escalation. Retain every attempt, including errors/retries.
4. Attempt to approve the unsupported contract: approval must remain blocked. Record
   needs_correction instead. Sign in as Finance and approve the matched invoice only
   after reviewing source evidence and the PO comparison.
5. Verify actor IDs, immutable events, original model versions, department queue and
   analytics. Confirm a Finance related PO is readable in the repository but absent
   from the Finance action queue, and that Legal cannot read or review Finance invoices.
6. Request an authorized export. Verify only scoped records, attachment bytes and
   one-use denial. Separately verify browser file delivery and full-width UI before
   recording those as passed. Do not publish a bearer download URL or account password.

Actually executed: six documents processed with real OCR/Groq through browser batch
submission; 40/40 annotated fields and 6/6 expected final routes. One invoice initially
failed due to provider quota after bounded retries; one explicit retry recovered it.
The failed attempt remains in history. Therefore first-attempt completion was 5/6,
not 6/6. Authenticated administrator needs_correction and Finance approved decisions
persisted. Unsupported-contract approval was blocked in the UI. Five separately
authenticated backend permission checks were denied. Scoped analytics contained three
authorized documents, including a related read-only PO. Actual HTTP JSON export returned
three scoped records with no-store and denied replay with HTTP 403. Browser JSON
delivery and browser Legal-negative interaction were not completed in this audit;
Legal denial was verified through backend calls. CSV UI delivery was also not tested.

The browser demonstration preceded the last seller-role guard. The final code then
replayed all six observed postprocessed states with cached OCR and preserved fields/
expected routes. This is recorded-state regression, not another live/browser run.

## Safe release fixes

1. First-time sign-in instructions show the local bootstrap command and refresh step.
2. Protected attachment headers now provide an ASCII fallback and UTF-8 filename*;
   non-Latin filenames no longer break the HTTP header.
3. Review queries use actionable department scope. Related-document read/export scope
   remains available; mutation guards are unchanged and still enforced.
4. Invoice validation checks an existing three-fragment seller-layout certificate
   only when its seller/ID/evidence are present and OCR-supported. Contradictory model
   seller or tax-ID fields cause manual review. Missing optional tax ID remains optional;
   unverified baseline hints do not become role truth. Model values are not replaced.

The last fix was motivated by a development case: both raw and hybrid extraction used
the client's tax ID and seller name on a degraded image. Before the fix, the graph
accepted the text-supported but wrong roles for normal departmental review. After the
fix, replay of exactly the same observed fields gives two role-conflict validation
errors and manual_review. Both before/after artifacts are preserved. It does not repair
the extraction itself or prove that every possible role error is detectable.

## Focused layout experiment and supported contribution

`scripts/evaluate_layout_fallback.py` generated six synthetic invoice layouts before
predictions and ran real RapidOCR plus one live Groq extraction per source. Invoice
type was supplied; classification is not an outcome of this experiment. Each hybrid
prediction reuses the identical parsed response and OCR. Raw responses, bounding boxes,
ground truth, baseline certificates and outcomes are retained.

| Case | LLM only tax ID | Hybrid tax ID | Interpretation |
| --- | --- | --- | --- |
| Seller left | Correct | Correct | No change |
| Seller right, reversed columns | Abstained | Correct | One natural layout recovery |
| Two competing seller-column IDs | Abstained | Abstained | Appropriate uncertainty retained |
| Stacked seller/client roles | Correct | Correct | No layout certificate used |
| Degraded image | Incorrect | Incorrect | Nonempty model error retained; final validation now escalates |
| Missing seller label | Abstained | Abstained | Unsupported role assignment not guessed |

There was one natural correct recovery and zero incorrect fallback additions in six
correlated development probes; hybrid abstained on two. On a separate, explicitly
simulated intervention removing tax_id from each recorded model response, fallback
recovered two correctly, added none incorrectly and abstained four times. Fabricated
certificate evidence and conflicting seller probes abstained in all six. Controlled
omissions are not natural live-model gains. A single discordant positive case is not
statistical evidence of population superiority. No blind baseline-total substitution
or first-tax-ID assumption was used.

A precise contribution statement is: a reproducible local IDP prototype combining
structured LLM extraction with selective geometry-certified recovery and conflict
escalation, deterministic cross-document/policy guards, and authenticated durable human
review, evaluated through task-specific paired experiments. The present observations
support feasibility and a narrow recovery example, not novel neural modeling,
industrial generalization or human productivity savings.

## Additional experiment protocol before stronger claims

Priority 1: freeze the final code/prompts/policies, then collect an independent paired
layout set before examining its predictions. A practical next pilot is 24 invoices
across at least four unseen template/supplier families: clear columns, reversed or
multiline roles, competing IDs/missing evidence, and degraded/rotated/multipage layouts.
Keep transformations and dependent documents in the same split. Two annotators should
independently label seller/client identities, all tax IDs, role rectangles, ambiguity
and intended review decisions; resolve disagreements before running models.

Run the same OCR/ground truth under raw LLM-only, hybrid extraction, and final validation
guards. Keep all outputs, failures and retry usage. Measure natural correct/incorrect
recoveries, retained wrong values, appropriate/incorrect abstentions and false
escalations. Report resolvable and ambiguous denominators separately. Test valid
multiline seller names to detect false role-conflict escalations. Use paired discordant
counts and family-level uncertainty; do not treat fields or transformed copies as
independent samples. Repeat a prespecified subset or all 24 three times if budget allows;
72 extraction calls are a planning scenario requiring a reviewed budget, not executed
results. Invoice type supplied versus actual classification must remain distinct.

Priority 2: obtain a licensed, independently annotated real-world set with matching
schema/role labels. No corporate confidentiality or redistribution permission may be
assumed. The old standard invoice's license is unresolved. Use separate tuning/final
families and a frozen final evaluation; document any later test-driven change as tuning.

Priority 3: extend labeled safety cases to changed/rejected POs, conflicting IDs,
currency/vendor/total mismatches, arithmetic, unsupported contracts and ambiguity.
Keep oracle-field deterministic tests separate from live end-to-end tests. Report
false departmental acceptances/escalations and policy attribution; neither normal
routing nor a prototype approval is an external business execution.

Priority 4: if claiming efficiency or scalability, measure fresh live batch wall time,
actual attempts/tokens, OCR/API/retry/database stages and failure recovery at a declared
load. Existing 5/10/20 recorded-response cache workloads do not establish live inference
throughput. Price estimates need verified usage and model pricing; no cost reduction
or ROI is currently supported. Obtain approval before large live runs.

## Executable human-versus-assisted study

Prepare a new pack:

```
uv run --python 3.14.6 python scripts/prepare_human_study.py --output results/study_new
```

The completed preparation is `results/final_release_20261014/human_study_v2/`. Open
`study_timer.html` locally. Sources A/B each contain a PO, mismatching invoice, receipt
and two-party contract with matched difficulty and fictional identifiers. The source,
reference PO, required field names, policy, correctness criteria and final recording
form are identical across conditions. Coordinator ground truth is separate from the
operator HTML and must not be shown during tasks. The pack has planned slots, not
recruited participants or completed observations.

Use four counterbalanced schedules: manual A then assisted B; assisted B then manual A;
manual B then assisted A; assisted A then manual B. Within each block process PO before
invoice, then receipt/contract. Assign consenting anonymous operators to schedules;
record actual order and training, use independent practice sources, and avoid seeing
the same source twice. Four operators/32 task observations can establish study
feasibility only; a defensible inferential sample size requires a pilot variance and
predeclared meaningful effect, not a fabricated power claim.

Give operators the same instructions: enter the specified fields from the source,
check the reference PO and fixed policy, choose the correct department/escalation,
record a reason, and verify accuracy before finishing. In manual mode no AI output is
provided. In assisted mode use the actual application, import only that source's actual
JSON into the same form, then verify/correct it. Do not prefill generator ground truth
as if it were an AI prediction. Coordinator should check the imported document identity.

Start when the source first becomes available in either arm, before assisted upload
or inference. The recorder measures total elapsed time and active segments. Pause
active time during AI waiting or external interruption, with separate event categories;
resume for source checks, correction and exception resolution. Record both active and
elapsed time, AI wait, interruptions, correction count, reason, workload 1–7 and
completion. Capture exception-resolution segments separately with an observer if a
dedicated exception-time estimate is needed. Failed/abandoned tasks remain in the
study log; do not discard slow or incorrect observations.

Score actual exported records against the separate coordinator truth:

```
uv run --python 3.14.6 python scripts/analyze_human_study.py --ground-truth results/study_new/coordinator_ground_truth.json --records results/study_new/records --output results/study_analysis_new
```

The analyzer validates basic timing and record identity, scores field/route
correctness, rejects duplicate participant/case records and compares time only for
balanced, fully correct four-type blocks. It does not verify recruitment, actual
assignment/order or human provenance automatically: the coordinator must do those
checks. Report accuracy, false acceptances, workload and all failures for every arm,
alongside correct-completion time. Analyze paired participant differences, condition/
period effects and participant-level uncertainty rather than iid document timings.
Do not turn inference time into human time saved. Empty input was executed and yields
zero observations, zero participants and a null savings estimate. No participant
study was conducted. The browser timer itself still needs a coordinator dry-run.

## Paper audit and publication checklist

The source documents are in `results/milestone7_20261014/research_sources/`; there was
no project-root research_sources directory. Originals in `data/Docs of report and
research paper/` remain unchanged. The report proposes PaddleOCR/LayoutLMv3, Taipy,
FastAPI and PostgreSQL; the implementation uses RapidOCR, Groq, LangGraph, Streamlit
and SQLite. Only classification/extraction call the LLM; deterministic graph stages
are not independent autonomous reasoning agents. The original image orders
cross-document verification before anomalies; the implementation orders anomalies,
verification, business policy and routing, with policy binding before validation.

Replace or qualify claims of novel integration, fraud detection, complete semantic
evidence validation, efficiency, scalable automation and reduced human effort.
Six clean synthetic pilot successes and one layout recovery do not support them.
Evidence text occurrence is not calibrated accuracy or complete role correctness.
SQLite append-only history is not cryptographically tamper-proof. The paper's results
and methods placeholders need actual methods/results, not extrapolated success rates.

References 7 and 12 duplicate the same geoscience quality-control paper; reference 7
also has a malformed DOI rendering. Deduplicate/re-number and validate bibliographic
metadata, author spellings, complete venue/pages and DOI formatting against primary
sources. Not all references have been fully verified. The literature survey's blanket
claim that prior systems lack integrated validation is contradicted by
[IDP Accelerator](https://aclanthology.org/2026.acl-demo.11/). Compare tasks and guards
carefully with [DocLLM](https://aclanthology.org/2024.acl-long.463/),
[DocAgent](https://aclanthology.org/2025.emnlp-main.893/) and
[DocClaw](https://arxiv.org/abs/2608.18685), without importing their reported gains.

Suggested paper structure: bounded problem/claims; verified related-work comparison;
implemented architecture and trust boundaries; selective recovery/conflict methods;
dataset provenance/splits and protocol; extraction/safety/latency results with counts;
error/abstention/security limitations; conclusion limited to supported observations.
Use a systems/empirical contribution rather than claiming a new trained document model.

- [ ] Reconcile technology stack, graph order and actual LLM responsibilities.
- [ ] Deduplicate and verify references; complete methods and ethics/data provenance.
- [ ] Freeze and run a genuinely held-out paired role/layout evaluation.
- [ ] Independently adjudicate role/evidence labels and report harmful recoveries/errors.
- [ ] Report uncertainty, failures, rate limits, usage and task-specific denominators.
- [ ] Obtain licensed real-world evidence before industrial generalization.
- [ ] Run the human protocol before any human productivity or ROI claim.
- [ ] Run fresh load experiments before live-throughput/scalability claims.
- [ ] Prepare a sanitized, permitted supplementary artifact package separately from private archives.
- [ ] Have authors review limitations and target-venue requirements; no acceptance guarantee.

## Proposed Git checkpoint and inventory

Base is `ba4b347f1fbf5aaa266a2de906a8ce3a7ac02080`, the previously pushed Milestone 6
checkpoint. Proposed annotated tag after approval: `v0.1.0-research.m7`, matching the
existing package version 0.1.0. No tag or version bump has been created.

Proposed first commit: **Fix sign-in guidance and protected document review checks**.
Inventory: `src/idp/ui/security.py`, `src/idp/security/access.py`,
`src/idp/security/downloads.py`, `src/idp/agents/validation_agent.py`,
`scripts/test_security.py`, `scripts/test_validation.py`.

Proposed second commit: **Add reproducible research evaluations and study protocols**.
Inventory: `docs/milestone7_research.md`, `docs/final_release_readiness.md`,
`scripts/research_metrics.py`, `scripts/test_research_metrics.py`,
`scripts/research_ablation.py`, `scripts/research_batch_replay.py`,
`scripts/prepare_research_pilot.py`, `scripts/prepare_research_stress.py`,
`scripts/summarize_research.py`, `scripts/evaluate_layout_fallback.py`,
`scripts/prepare_human_study.py`, `scripts/analyze_human_study.py`.

There are six tracked modified files and twelve intended new files. Prefer explicit
file staging after approval, inspect the staged diff again, then commit and tag the
actual reviewed commit. Generated metrics, retained files, screenshots, raw responses,
private fixture credentials and SQLite snapshots/archives are intentionally excluded
by `/results/` and `/data/`. Do not force-add them. Keep the verified local preservation
archive and manifest as a private companion; a Git-only clone cannot reconstruct the
ignored observed outputs. No README, dependency or product stack rewrite belongs in
this checkpoint. No commit, tag, staging or push was performed during this audit.
