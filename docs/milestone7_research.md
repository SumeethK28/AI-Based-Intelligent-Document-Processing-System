# Reproducible research evaluation

Use Python 3.14.6 and uv from the project root. All evaluators write to new directories
under `results/`, use isolated databases and refuse to overwrite existing experiments.
They do not write to the original database or send the supplied research reports to APIs.

## Prepare synthetic ground truth before predictions

```
uv run --python 3.14.6 python research/tools/prepare_research_pilot.py --output results/research_pilot_new/dataset
```

The generator produces six fictional single-page PDFs with source hashes, expected
field roles, expected routing, source-family labels and generator provenance. These are
development pilot cases, not an untouched independent industrial test set.

## Run bounded paired configurations

Default runs existing deterministic extraction with real RapidOCR, without model calls:

```
uv run --python 3.14.6 python research/tools/research_ablation.py --manifest results/research_pilot_new/dataset/manifest.json --output results/research_pilot_new/baseline
```

Opt-in live mode sends only the declared synthetic OCR to the configured Groq model:

```
uv run --python 3.14.6 python research/tools/research_ablation.py --manifest results/research_pilot_new/dataset/manifest.json --output results/research_pilot_new/live --live
```

A is the existing deterministic baseline. B is raw parsed live Groq output before
postprocessing. C applies existing extraction postprocessing/layout fallback to the same
B response. D runs the actual graph and persistence with cached OCR and the recorded B
response. C/D are paired replay of live output, not independent new API calls or model
latency measurements. Process the reference PO first as specified by the manifest.
Contract extraction is unsupported in A; report that task separately.

`--max-documents` is bounded to six and `--repeats` to two. The six-source first run
uses twelve planned logical calls. Repeat the preselected first two sources in another
new output directory with `--max-documents 2` for four additional logical calls.
The provider retains its bounded retries; response-group times include their overhead,
but individual HTTP retry counts are not separately instrumented. Raw returned content,
parsed fields, evidence, fallback changes, full D state, timings and response usage are
saved; keys, headers and exception bodies are not.

## Stress and batch work

```
uv run --python 3.14.6 python research/tools/prepare_research_stress.py --manifest results/research_pilot_new/dataset/manifest.json --output results/research_pilot_new/stress_dataset
uv run --python 3.14.6 python research/tools/research_ablation.py --manifest results/research_pilot_new/stress_dataset/manifest.json --output results/research_pilot_new/stress_A
uv run --python 3.14.6 python research/tools/research_batch_replay.py --predictions results/research_pilot_new/live/predictions.json --manifest results/research_pilot_new/dataset/manifest.json --output results/research_pilot_new/batches
```

Stress variants cover 90-degree rotation, low resolution, seeded noise, two-column tax
ID roles, split multipage fields and missing seller. They remain in the same development
families as their parents. Default stress evaluation measures only A with real OCR;
do not infer LLM performance on these variants.

Batch replay uses real batch submission, source hashing, graph checks, SQLite,
duplicate caching and forced reprocessing, with recorded live model outputs and cached
OCR. It measures local cache/framework work, not end-to-end live inference throughput.
Five/ten/twenty submitted items reuse at most six source-byte streams. Inspect persisted
failures even when a command exits successfully.

## Historical reanalysis and plots

`research/tools/research_metrics.py` reanalyses saved reports using role-sensitive present-slot
comparisons. Incorrect values count as FP and FN; omitted values as FN. Unannotated
extras are not labelled hallucinations. The evidence text-support flag is a proxy,
not independent role/evidence adjudication. Wilson intervals are descriptive iid
illustrations; correlated convenience samples do not establish population accuracy.

The completed bounded run is under `results/milestone7_20261014`. Its report separates
live results, historical reanalysis, deterministic tests and recorded-response timings.
The summary can be reproduced with a new output directory:

```
uv run --python 3.14.6 --with matplotlib python research/tools/summarize_research.py --root results/milestone7_20261014 --output results/research_summary_new --plots
```

Matplotlib is temporary for plotting; it is not added to product dependencies.
CSV tables, JSON summaries, PNG/PDF plots and an empty human-study recording template
are generated. No human time savings are computed without an actual manual baseline.

Large live runs, a licensed final dataset, new tuning and a human participant study need
a reviewed protocol and explicit approval when required by the original brief.
This pilot does not establish industrial generalization, fraud detection, production
security, legal validity or publication novelty.
