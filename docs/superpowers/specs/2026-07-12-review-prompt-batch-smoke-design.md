# Review Prompt N=15 Batch Smoke Design

- Date: 2026-07-12
- Repository: `baeseongsu/ralphthon-icml`
- Goal: run one reproducible, privacy-preserving P0-versus-P1 review-prompt smoke on a frozen N=15 development sample and decide whether the pipeline is healthy enough to scale.

## 1. Outcome

Build a paper-level batch evaluation path for the ICML review-prompt optimizer, then execute exactly two prompt versions on the same 15 papers:

- `P0`: the existing reviewer baseline in `skills/auto-research/assets/review-optimization/smoke-prompt.md`.
- `P1`: P0 plus one coherent evidence-to-ordinal-score calibration intervention. P1 may update multiple related prompt sections, but it must preserve P0's section coverage, security rules, and output contract.

The smoke is successful when the pipeline completes and produces auditable evidence. P1 does not need to beat P0. A valid `discard` is a successful smoke outcome; N=15 is not sufficient evidence for a final prompt-improvement claim.

## 2. Frozen Inputs and Boundaries

### 2.1 Pseudo-labels and PDFs

- Pseudo-label directory: `data/pseudo_labels/`
- PDF directory: `/Users/seongsubae/Downloads/ralphton_pseudo_labels/matched_pdfs/`
- Expected identity: one JSON and one PDF with the same forum-ID filename stem.
- Permission provenance: user-supplied public ICML research material. The generated manifest records this as user-attested provenance rather than independently verified permission.

The repository currently contains 175 pseudo-label JSON files, including reference prose and ordinal score targets. They are pseudo-labels, not independently verified human ground truth. Results therefore use the term `reference-score agreement` in reports. The existing `HumanAgreement` metric name remains as a compatibility label, with `target_source=pseudo_label` recorded in provenance.

### 2.2 Data visible to each role

| Role | May see | Must not see |
| --- | --- | --- |
| Reviewer | PDF-derived text, P0 or P1, generated-review schema | pseudo-label prose, reference scores, aggregate score distributions, Judge prompt/output |
| Judge | PDF-derived text, generated review, reference prose, frozen Judge rubric/schema | numeric reference scores, candidate identity, candidate prompt |
| Local evaluator | generated review, Judge result, numeric reference targets | no new model input |
| W&B | pseudonymous paper ID, sanitized generated review/Judge result, aggregate predicted/reference distributions, allowlisted metrics/config | PDF/text, raw reference prose, original forum ID, per-paper reference labels, secrets |

The Judge prompt, Judge model, Reviewer model, output schemas, objective weights, regression thresholds, and frozen sample remain unchanged between P0 and P1.

## 3. Dataset Preflight and Split

### 3.1 Preflight classification

Every one of the 175 pairs receives exactly one status: `valid` or `excluded` with a reason. Preflight checks:

1. JSON parses and contains exactly the required pseudo-label fields.
2. JSON forum ID matches the filename stem and is unique.
3. All prose fields are nonempty and all ordinal scores are integers within the ICML ranges.
4. Matching PDF exists, begins with a PDF signature, and has a stable SHA-256.
5. `pdfinfo` succeeds and `pdftotext -layout -enc UTF-8` produces at least 1,000 characters.
6. PDF Title and Author metadata are present for fail-closed W&B redaction.

Current preflight evidence classifies 173 pairs as valid. Two PDFs are excluded from this smoke because redaction metadata is incomplete:

- `r8qbhgGHnC`: missing Title metadata.
- `xX8JgcSJqW`: missing Title and Author metadata.

The files are not deleted. A later campaign may add a separately reviewed metadata-recovery path.

### 3.2 Development and holdout

Split the 173 valid papers into:

- development: 138 papers
- holdout: 35 papers

Use split seed `20260712`. Allocate the holdout proportionally by `overall_recommendation` with the largest-remainder method. Within each recommendation stratum, add one paper at a time: choose the remaining paper that minimizes the summed L1 error between the selected subset's score marginals and the valid pool's marginals across soundness, presentation, significance, originality, overall recommendation, and confidence. Break equal-error ties by the lexical order of SHA-256(`seed || paper_id`). Persist the selected IDs, source hashes, algorithm version, and resulting marginal distributions in the manifest.

The batch runner refuses entries whose split is not `development`. Holdout scores and generated outputs are not evaluated during this Goal.

### 3.3 Frozen N=15 sample

Select 15 papers from development using sample seed `20260713`, largest-remainder recommendation allocation, and the same deterministic greedy marginal-distribution matching rule. Order the final sample by SHA-256(`sample_seed || paper_id`), then freeze the ordered IDs and sample-manifest SHA-256 before model inference. P0 and P1 must use the exact same ordered sample and configuration.

The sampler optimizes representativeness; it must not select examples based on model outputs or candidate performance. The frozen recommendation allocation is 12 score-4 papers and 3 score-5 papers.

## 4. Prompt Intervention

### 4.1 P0

P0 remains byte-for-byte unchanged. It defines the review sections, evidence grounding, ICML score ranges, rationales, prompt-injection guardrail, and strict JSON output.

### 4.2 P1 hypothesis

Hypothesis:

> Requiring an explicit evidence-to-ordinal-score calibration pass will reduce reference-score error and distribution collapse without degrading reference-based review quality.

P1 copies P0 and adds one calibration module that applies across the score-related sections:

1. Identify the strongest supporting evidence and most decision-relevant deficiency for each dimension.
2. Use explicit ordinal boundaries: score 2 requires a material flaw affecting a central claim; score 3 represents mostly solid work with material but bounded limitations; score 4 requires strong support with only minor limitations.
3. Do not penalize an absent optional experiment unless it is necessary for a central claim.
4. Reconcile overall recommendation with the dimension judgments without converting it into a mechanical average.
5. Treat confidence as evaluator certainty, not paper quality.
6. Link each score rationale to a paper section, table, figure, equation, or reported result when available.

P1 does not remove or shorten any P0 instruction and does not change the schema. The previous `smoke-prompt-v1.md` is excluded because it combined calibration changes with deletion of P0 instructions.

## 5. Batch Architecture

### 5.1 Dataset module

Add a pure dataset/preflight module that:

- validates all pairs;
- writes an immutable full-pool manifest and exclusion report;
- creates the development/holdout split;
- creates the ordered N=15 sample manifest;
- recomputes and verifies manifest hashes;
- refuses duplicate IDs, missing files, score-range violations, or holdout access.

Runtime manifests live under `.review-prompt-smoke/` and are not committed. Tests use synthetic temporary fixtures.

### 5.2 Single-paper runner instrumentation

Retain the existing isolated Reviewer and Judge `codex exec` calls. Add monotonic timing and bounded retry evidence for:

- PDF extraction and metadata preflight;
- Reviewer call;
- Judge call;
- scoring/local evidence;
- total paper wall-clock.

Each model call permits at most two attempts total. Retries apply only to timeout, rate-limit, transient transport, or schema-output failure. Every attempt and failure class is recorded. A paper that still fails causes the candidate to be marked `crash`; it is never silently removed from the denominator.

### 5.3 Candidate batch runner

Run papers sequentially by default (`workers=1`) so the first smoke measures a stable, low-risk baseline. The runner:

1. verifies the frozen sample manifest;
2. executes one candidate across all 15 papers;
3. preserves per-paper local evidence;
4. aggregates metrics and distributions;
5. creates one W&B offline run for the candidate;
6. emits a candidate summary and append-only ledger record.

P0 completes before P1 starts. The same batch configuration is passed to both.

## 6. Metrics and Selection

### 6.1 Per-paper metrics

- normalized agreement for soundness, presentation, significance, originality, and overall recommendation;
- mean reference-score agreement;
- Judge scores for the nine frozen rubric dimensions;
- mean JudgeQuality;
- signed `prediction - reference_target` gap per score dimension;
- penalties and failure state;
- Reviewer/Judge token usage and latency.

Confidence is recorded as a diagnostic prediction but is not included in HumanAgreement or CompositeScore.

### 6.2 Candidate aggregates

- macro mean HumanAgreement/reference-score agreement;
- macro mean JudgeQuality;
- `0.5 * HumanAgreement + 0.5 * JudgeQuality - 0.25 * Penalty`;
- dimension-level agreement and signed-gap mean/median;
- total/p50/p95/max Reviewer, Judge, and paper latency;
- total tokens, attempts, retries, failures, wall-clock, and papers/hour.

P1 is kept only when CompositeScore improves over P0 and the existing component and dimension regression gates pass. Otherwise it is discarded. No candidate becomes the next parent after a discard.

### 6.3 Score distributions

Predicted review scores are strict integers. Record counts and frequencies for:

- soundness, presentation, significance, originality: 1-4;
- overall recommendation: 1-6;
- confidence: 1-5;
- each Judge rubric dimension: 1-5.

Locally, also record per-paper reference targets, reference distributions, reviewer disagreement when multiple reviews exist, and signed-gap distributions.

W&B receives:

- predicted counts/frequencies;
- aggregate reference counts/frequencies with no paper linkage;
- Judge counts/frequencies;
- one `reviews/all` table with 15 pseudonymous rows;
- one `score_distributions` table and one `judge_distributions` table.

W&B never receives per-paper reference targets or raw reference prose.

## 7. W&B and Privacy

Use one run per candidate:

- entity/project: `seongsubae/review-prompt-smoke`
- group: campaign ID
- job type: `review-prompt-candidate`
- run name: candidate ID

Create offline runs first. Before sync, scan the exact offline payload for forum IDs, filenames, titles, method/title stems, authors, raw-reference field markers, and unexpected files. Sync only the two approved candidate directories. After sync, verify both runs via the authenticated W&B API and verify that the project is not anonymously readable.

The project stores no source PDF, extracted paper text, raw pseudo-label JSON, reference prose, individual reference scores, environment secrets, source identifiers, or console logs.

## 8. Local Evidence

The campaign output contains:

- full-pool manifest and exclusion report;
- development/holdout split manifest;
- frozen N=15 sample manifest;
- P0 and P1 prompt copies and hashes;
- per-paper generated review, Judge result, metrics, timing, usage, attempts, and provenance;
- candidate aggregates, distributions, reflection, and W&B offline run;
- campaign keep/discard decision;
- final smoke report with scale recommendation.

All runtime evidence is append-only or written to a new campaign directory. Existing evidence is never overwritten.

## 9. Testing and Verification

Tests must cover:

1. 175-pair preflight classification and explicit exclusions using synthetic fixtures for edge cases.
2. Deterministic split/sample generation and manifest-hash verification.
3. Holdout rejection and identical P0/P1 sample/config enforcement.
4. Strict integer predicted scores and range validation.
5. Multi-paper aggregation, p50/p95 timing, signed gaps, and score distributions.
6. Bounded retry and fail-closed 15/15 completion behavior.
7. W&B multi-row/two-distribution-table payload and exact allowlists.
8. Absence of reference prose, per-paper reference labels, identifiers, PDF/text, and secrets from W&B payloads.
9. Existing single-paper smoke compatibility and keep/discard lineage.

Before live inference, run the full repository test suite, plugin validator, Python compilation, `git diff --check`, and a model-free 175-pair preflight. After inference, recompute aggregate metrics from frozen per-paper evidence and require canonical JSON equality plus matching SHA-256 values against the saved summaries.

## 10. Stop and Completion Conditions

Stop and report rather than weakening the Goal when:

- a required PDF/label pair or user-attested permission provenance is missing;
- the frozen manifest or candidate configurations differ;
- Reviewer/Judge label-blindness cannot be proven;
- privacy scan finds source identifiers or reference data;
- either candidate fails to complete all 15 papers after bounded retries;
- W&B sync targets a different entity/project or is anonymously readable.

Complete only after P0 and P1 each finish 15/15, all tests and privacy gates pass, both private W&B runs are API-readable with the required rows/distributions, and the final report states the decision, score-distribution changes, wall-clock/throughput, limitations, and whether increasing N is operationally justified.

## 11. Non-goals

- Increasing N during this Goal.
- Evaluating or tuning on holdout.
- Optimizing the Judge prompt/model or Reviewer model.
- Claiming a general prompt improvement from N=15.
- Uploading source papers, reference prose, or individual target labels to W&B.
- Implementing full production-scale parallelism or direct-provider billing estimates.
