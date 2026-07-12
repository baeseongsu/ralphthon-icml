# Review Prompt N=15 Batch Smoke Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

Goal: Build and run one reproducible P0-versus-P1 review-prompt campaign over a frozen score-balanced N=15 development sample, with private W&B distributions and auditable keep/discard evidence.

Architecture: A pure dataset module freezes the pool, split, and sample. The isolated single-paper Codex adapter gains integer validation, retry, timing, and sanitized publish bundles. A batch runner aggregates 15 papers per candidate, while a separate publish phase creates one W&B run per candidate after the keep decision and any successful-candidate Git commit.

Tech stack: Python 3.9+ standard library, unittest, Poppler, authenticated Codex CLI, W&B SDK through uv.

## Global constraints

- Source: 175 pseudo-label JSONs in data/pseudo_labels and 175 matching PDFs under /Users/seongsubae/Downloads/ralphton_pseudo_labels/matched_pdfs.
- Exclude r8qbhgGHnC and xX8JgcSJqW for incomplete redaction metadata.
- Freeze 138 development and 35 sealed holdout with split seed 20260712.
- Freeze N=15 from development with sample seed 20260713.
- P0 and P1 use identical sample, models, Judge prompt, schemas, weights, and regression gates.
- Reviewer never sees reference prose or scores. Judge sees reference prose but never numeric targets or candidate identity.
- W&B receives pseudonymized generated/Judge content and aggregate distributions, never source documents, original IDs, raw references, or per-paper targets.
- Create offline W&B runs first and sync exactly two runs to seongsubae/review-prompt-smoke after a zero-hit privacy scan.
- Commit and push only a candidate that receives keep. Discard/crash stays in ignored local and W&B evidence.
- Do not inspect holdout outputs, increase N, optimize Judge/model, or claim general improvement.

---

### Task 1: Freeze integer schemas and batch scoring

Files:
- Modify skills/auto-research/assets/review-optimization/generated-review.schema.json
- Modify skills/auto-research/assets/review-optimization/judge.schema.json
- Modify skills/auto-research/scripts/review_prompt_scoring.py
- Create tests/test_review_prompt_batch.py

Interfaces:
- Consumes existing single-paper generated review, Judge, metric, timing, and usage records.
- Produces aggregate_paper_records, ordinal_distribution, strict integer validators, signed gaps, and deterministic percentile metrics.

- [ ] Step 1: Write failing tests that reject generated score 3.5 and Judge score 4.5 and that aggregate two synthetic paper records into score distributions, signed gaps, macro objectives, and p50/p95 latency.

~~~python
def test_generated_and_judge_scores_require_integers(self):
    with self.assertRaisesRegex(ValueError, "integer"):
        scoring.validate_generated_review(review_with_soundness(3.5))
    with self.assertRaisesRegex(ValueError, "integer"):
        scoring.validate_judge(judge_with_rubric_coverage(4.5))

def test_batch_aggregate_records_distributions_gaps_and_latency(self):
    result = scoring.aggregate_paper_records(two_valid_paper_records())
    self.assertEqual(result["sample_count"], 2)
    self.assertEqual(
        result["predicted_distributions"]["soundness"]["counts"],
        {"1": 0, "2": 0, "3": 1, "4": 1},
    )
    self.assertEqual(result["signed_gaps"]["soundness"], [0.0, 1.0])
    self.assertIn("p95", result["timing"]["reviewer_seconds"])
~~~

- [ ] Step 2: Run python3 -m unittest tests.test_review_prompt_batch.BatchScoringTest -v and confirm failure because floats are accepted and aggregate functions are absent.
- [ ] Step 3: Change all Reviewer/Judge ordinal schema properties to integer. Add _ordinal_integer, ordinal_distribution, a linear-interpolation percentile helper, and aggregate_paper_records.
- [ ] Step 4: Require aggregate_paper_records to macro-average HumanAgreement, JudgeQuality, and Penalty; recompute Composite; aggregate each dimension; preserve local signed gaps; and total usage, attempts, retries, failures, and timing.
- [ ] Step 5: Run python3 -m unittest tests.test_review_prompt_batch.BatchScoringTest tests.test_review_prompt_smoke -v and require all tests to pass.
- [ ] Step 6: Commit only these files with message feat: aggregate ordinal review scores.

---

### Task 2: Build the 175-pair preflight and frozen sample

Files:
- Create skills/auto-research/scripts/review_prompt_dataset.py
- Modify tests/test_review_prompt_batch.py

Interfaces:
- Consumes label/PDF directories, Poppler binaries, split/sample sizes and seeds.
- Produces preflight_pool, select_balanced, freeze_dataset, full classification, a mode-0600 sealed holdout manifest, a development manifest, and an ordered N=15 sample manifest.

- [ ] Step 1: Write failing tests for deterministic selection independent of input ordering, largest-remainder recommendation quotas, explicit metadata exclusions, exact 0600 holdout permissions, and absence of holdout IDs/labels from development artifacts.
- [ ] Step 2: Run python3 -m unittest tests.test_review_prompt_batch.DatasetContractTest -v and confirm the module/function failure.
- [ ] Step 3: Implement selector version score-marginal-greedy-v1 exactly as the approved design: UTF-8/NUL SHA tie-break, largest-remainder quotas, partial-subset marginal L1, canonical JSON, and stable output order.
- [ ] Step 4: Implement JSON ID/schema/range validation, PDF signature/SHA, pdfinfo Title/Author, pdftotext length, explicit exclusions, canonical manifest hashes, and atomic fresh-output writes.
- [ ] Step 5: Add a CLI with labels-dir, pdfs-dir, output-root, development-count, holdout-count, sample-count, split-seed, sample-seed, and permission-provenance.
- [ ] Step 6: Run the DatasetContractTest class and require all tests to pass.
- [ ] Step 7: Commit with message feat: freeze review prompt sample manifest.

---

### Task 3: Add label-blind timing, retry, and publish bundles

Files:
- Modify skills/auto-research/scripts/review_prompt_codex.py
- Modify tests/test_review_prompt_batch.py
- Modify tests/test_review_prompt_smoke.py

Interfaces:
- Consumes one sample entry, prompt/schema configuration, and maximum two attempts.
- Produces existing per-paper evidence plus timing.json, attempts.json, and publish-bundle.json with pseudonymized generated/Judge data only.

- [ ] Step 1: Write failing tests for one transient failure followed by success, two-attempt exhaustion, monotonic elapsed totals, fail-before-inference metadata validation, and absence of reference fields/original IDs in publish bundles.

~~~python
def test_codex_retry_is_bounded_and_records_attempts(self):
    output, usage, evidence = codex.run_codex_json_with_retry(
        invoke=fails_once_then_succeeds(),
        validator=lambda value: value,
        max_attempts=2,
        clock=fake_clock([0, 2, 2, 5]),
    )
    self.assertEqual(len(evidence["attempts"]), 2)
    self.assertEqual(evidence["elapsed_seconds"], 5)
~~~

- [ ] Step 2: Run python3 -m unittest tests.test_review_prompt_batch.CodexEvidenceTest -v and confirm missing functions.
- [ ] Step 3: Add run_codex_json_with_retry without changing the no-tools Codex command. Retry only timeout, rate-limit/transient transport, invalid JSON, or schema validation, at most two total attempts.
- [ ] Step 4: Measure extraction, metadata, auth preflight, Reviewer, Judge, scoring, and total time with time.perf_counter.
- [ ] Step 5: Add max-attempts default 2 and preserve all existing single-pair CLI behavior and label-blind prompt tests.
- [ ] Step 6: Run CodexEvidenceTest plus tests.test_review_prompt_smoke and require all tests to pass.
- [ ] Step 7: Commit with message feat: time and retry review inference.

---

### Task 4: Add one-run-per-candidate W&B batch tracking

Files:
- Modify skills/auto-research/scripts/review_prompt_tracking.py
- Modify tests/test_review_prompt_batch.py

Interfaces:
- Consumes 15 sanitized publish bundles, aggregate metrics/distributions, and source/kept Git SHAs.
- Produces record_wandb_batch_offline returning run ID/directory with reviews/all, score_distributions, and judge_distributions tables.

- [ ] Step 1: Write failing FakeWandb tests requiring exactly 15 review rows, both distribution tables, aggregate reference distributions without paper linkage, and rejection of source IDs/reference labels in any row.
- [ ] Step 2: Run python3 -m unittest tests.test_review_prompt_batch.WandbBatchTest -v and confirm failure.
- [ ] Step 3: Implement exact config and metric allowlists for campaign/sample/prompt/schema/model/auth/Git hashes, objectives, dimensions, timing, usage, attempts, failures, and throughput.
- [ ] Step 4: Validate every pseudonymous paper ID and generated/Judge schema before wandb.init. Log no paths, console, code, Git patch, machine metadata, requirements, or reference fields.
- [ ] Step 5: Run WandbBatchTest and all legacy smoke tracking tests.
- [ ] Step 6: Commit with message feat: track batch review distributions.

---

### Task 5: Build P1 and the batch campaign/publisher

Files:
- Create skills/auto-research/assets/review-optimization/smoke-prompt-calibration-v2.md
- Create skills/auto-research/scripts/review_prompt_batch.py
- Modify skills/auto-research/scripts/review_prompt_loop.py
- Modify tests/test_review_prompt_batch.py

Interfaces:
- Consumes frozen sample, P0/P1, and shared Reviewer/Judge configuration.
- Produces 30 per-paper outputs, two candidate aggregates/publish bundles, campaign decision, final report, and a publish command that creates two offline W&B runs after any keep commit.

- [ ] Step 1: Write failing fake-runner tests that require identical ordered sample/config hashes for P0/P1, baseline-before-candidate execution, 15/15 completion, fail-closed partial failure, and existing regression-gate selection.
- [ ] Step 2: Run python3 -m unittest tests.test_review_prompt_batch.BatchCampaignTest -v and confirm failure.
- [ ] Step 3: Create P1 by copying every P0 instruction and adding only the approved evidence-to-ordinal-score calibration block. Test that removing that block from P1 yields byte-equivalent P0 content apart from the title.
- [ ] Step 4: Implement run: verify sample hash, execute P0 then P1 with W&B disabled, aggregate, call candidate_decisions, and write campaign.json, append-only ledger, publish bundles, and final-report.md.
- [ ] Step 5: Implement publish: accept source-git-sha and optional kept-git-sha, read frozen bundles, and create exactly one offline W&B run per candidate.
- [ ] Step 6: Run all batch and smoke tests.
- [ ] Step 7: Commit implementation with message feat: run N15 review prompt campaign and push the branch before live inference.

---

### Task 6: Verify and execute the live campaign

Files:
- Modify skills/auto-research/SKILL.md
- Modify docs/2026-07-12-review-prompt-optimization-design.md
- Create docs/experiments/review-prompt-n15-001-decision.md only if P1 is kept
- Runtime .review-prompt-smoke/n15-001

- [ ] Step 1: Run full tests, py_compile, plugin validator, and git diff --check. Require zero failures.
- [ ] Step 2: Freeze the real pool with review_prompt_dataset.py using 138/35/15 and seeds 20260712/20260713. Require 173 valid, 2 explicit exclusions, 35 sealed holdout, and 15 development sample.
- [ ] Step 3: Immediately run review_prompt_batch.py run with P0, calibration-v2 P1, frozen Judge prompt/schemas, gpt-5.4 for both roles, workers 1, and max attempts 2. Require P0 and P1 each 15/15.
- [ ] Step 4: If campaign.json says P1 keep, write a sanitized decision doc, run full checks, commit the kept prompt/decision with message perf(review-prompt): keep calibration candidate, and push. If discard/crash, create no prompt commit.
- [ ] Step 5: Run the publish command through python-dotenv without printing WANDB_API_KEY. Supply source-git-sha and kept-git-sha only when applicable.
- [ ] Step 6: Scan exactly two offline W&B run directories against all source IDs, filenames, titles, derived title/method stems, authors, reference field markers, and unexpected files. Require zero explicit-identifier/reference hits.
- [ ] Step 7: Sync exactly those two directories to seongsubae/review-prompt-smoke with console and TensorBoard disabled.
- [ ] Step 8: Verify both online runs, metrics, 15 rows, and distribution tables through authenticated API. Verify private visibility with an unauthenticated GraphQL request requiring data.project to be null.
- [ ] Step 9: Canonically recompute all candidate aggregates from the 30 per-paper outputs and require matching hashes.
- [ ] Step 10: Update skill/design docs with exact commands and observed evidence; run full verification; commit and push documentation.
- [ ] Step 11: Report keep/discard, distribution deltas, wall-clock, p50/p95, throughput, attempts/retries/failures, residual re-identification limitation, and whether increasing N is operationally justified.
