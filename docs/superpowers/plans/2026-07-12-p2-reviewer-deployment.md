# P2 Reviewer-Only Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing `auto-research` skill run the manifest-selected P2 Reviewer on one local PDF without human labels, Judge inference, or W&B.

**Architecture:** A thin `review_prompt_deploy.py` adapter validates the checked-in deployment manifest and P2 hashes, then reuses the existing isolated Codex Reviewer primitives. It writes only a schema-valid JSON review, deterministic Markdown rendering, and provenance into a fresh atomic output directory.

**Tech Stack:** Python 3.12 standard library, Codex CLI ChatGPT auth, Poppler `pdftotext`, `unittest`, Markdown skill documentation.

## Global Constraints

- P2 is the only deployment default; P3/P4 remain experimental and unavailable through the deploy CLI.
- The model receives only the P2 prompt and delimited extracted paper text.
- The CLI has no human-review, reference-label, Judge, W&B, or prompt-selection argument.
- The runner persists no extracted paper text and never overwrites an output directory.
- At most two Reviewer attempts are allowed.

---

### Task 1: Pin and validate the P2 deployment contract

**Files:**
- Modify: `skills/auto-research/assets/review-optimization/deploy-manifest.json`
- Create: `tests/test_review_prompt_deploy.py`

**Interfaces:**
- Consumes: existing `deploy-manifest.json`, P2 prompt, and generated-review schema.
- Produces: `load_deployment(root: Path, manifest_path: Path) -> Deployment` with verified `candidate_id`, `model`, `prompt_path`, `schema_path`, and hashes.

- [ ] **Step 1: Write the failing manifest test**

```python
def test_manifest_pins_p2_model_prompt_and_schema_hashes(self):
    deployment = deploy.load_deployment(ROOT, MANIFEST)
    self.assertEqual(deployment.candidate_id, "p2")
    self.assertEqual(deployment.model, "gpt-5.4")
    self.assertEqual(deploy.sha256_file(deployment.prompt_path), deployment.prompt_sha256)
    self.assertEqual(deploy.sha256_file(deployment.schema_path), deployment.schema_sha256)
```

- [ ] **Step 2: Run the test and observe RED**

Run: `python3 -m unittest tests.test_review_prompt_deploy -v`

Expected: import or attribute failure because `review_prompt_deploy.py` and the manifest model/schema hash do not exist.

- [ ] **Step 3: Extend the manifest and implement strict loading**

Add `model` and `output_schema_sha256` under `default`. Define an immutable `Deployment` dataclass and reject path escapes, any default other than `p2`/`keep`, unknown default fields, missing files, and hash mismatches. Resolve repository-relative paths only after confirming `resolved_path.is_relative_to(root.resolve())`.

- [ ] **Step 4: Run the contract test and observe GREEN**

Run: `python3 -m unittest tests.test_review_prompt_deploy -v`

Expected: the manifest contract test passes.

### Task 2: Implement the Reviewer-only runtime with atomic evidence

**Files:**
- Create: `skills/auto-research/scripts/review_prompt_deploy.py`
- Modify: `tests/test_review_prompt_deploy.py`

**Interfaces:**
- Consumes: `Deployment`, local PDF path, output directory, Codex binary, `pdftotext` binary, timeout, and max attempts.
- Produces: `run(args, *, invoke=None, preflight=None, extract=None) -> dict[str, Any]` and three files: `review.json`, `review.md`, `provenance.json`.

- [ ] **Step 1: Write failing success, boundary, and cleanup tests**

```python
def test_success_writes_exact_reviewer_only_outputs(self):
    result = deploy.run(args, invoke=fake_reviewer, preflight=fake_auth, extract=fake_text)
    self.assertEqual(set(path.name for path in output.iterdir()),
                     {"review.json", "review.md", "provenance.json"})
    self.assertNotIn("judge", json.dumps(result).lower())

def test_request_has_no_reference_or_judge_blocks(self):
    request = deploy.deployment_request(P2.read_text(), "paper text")
    self.assertIn("BEGIN_UNTRUSTED_PAPER_TEXT", request)
    self.assertNotIn("REFERENCE_HUMAN_REVIEW", request)
    self.assertNotIn("independent Judge", request)

def test_failure_removes_new_output_directory(self):
    with self.assertRaises(Exception):
        deploy.run(args, invoke=failing_reviewer, preflight=fake_auth, extract=fake_text)
    self.assertFalse(output.exists())
```

- [ ] **Step 2: Run the tests and observe RED**

Run: `python3 -m unittest tests.test_review_prompt_deploy -v`

Expected: failures for missing runtime functions and output behavior.

- [ ] **Step 3: Implement the minimal runtime**

Reuse `codex_preflight`, `extract_pdf_text`, `reviewer_request`, `run_codex_json`, and `run_codex_json_with_retry` from `review_prompt_codex.py`; reuse `validate_generated_review`, `reserved_output_directory`, `sha256_file`, and `write_json`. Validate the PDF magic header before extraction, make exactly one Reviewer role call, render Markdown deterministically from the validated JSON, and store usage/attempt evidence in provenance.

- [ ] **Step 4: Add the label-free CLI**

Expose only `--paper-pdf`, `--output-dir`, optional `--model` constrained to the manifest model, `--codex-bin`, `--pdftotext-bin`, `--timeout-seconds`, and `--max-attempts {1,2}`. Print a compact JSON summary containing candidate ID, output directory, and review hash.

- [ ] **Step 5: Run deploy tests and observe GREEN**

Run: `python3 -m unittest tests.test_review_prompt_deploy -v`

Expected: all deployment tests pass with no network calls.

### Task 3: Expose deployment through the existing skill

**Files:**
- Modify: `skills/auto-research/SKILL.md`
- Modify: `README.md`
- Test: `tests/test_repository_contract.py`

**Interfaces:**
- Consumes: the Task 2 CLI.
- Produces: a discoverable, copy-pasteable P2 Reviewer-only workflow.

- [ ] **Step 1: Add a failing repository contract test**

Assert that `SKILL.md` names `review_prompt_deploy.py`, documents PDF-only input and the three outputs, and explicitly excludes human labels, Judge, and W&B from deployment.

- [ ] **Step 2: Run the contract test and observe RED**

Run: `python3 -m unittest tests.test_repository_contract -v`

Expected: failure because the deployment section is absent.

- [ ] **Step 3: Add concise skill and README guidance**

Add a `P2 Reviewer-only deployment` section with the exact command from the design, output descriptions, ChatGPT-auth requirement, and N=5 interpretation boundary. Update the README catalog description without duplicating the full workflow.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
python3 -m unittest tests.test_review_prompt_deploy tests.test_repository_contract -v
python3 -m unittest discover -s tests -v
python3 -m py_compile skills/auto-research/scripts/review_prompt_deploy.py
python3 scripts/validate_repo.py
git diff --check
```

Expected: all tests and repository validation pass; compile and diff checks exit 0.

- [ ] **Step 5: Commit and push `main`**

```bash
git add -- \
  skills/auto-research/assets/review-optimization/deploy-manifest.json \
  skills/auto-research/scripts/review_prompt_deploy.py \
  skills/auto-research/SKILL.md README.md \
  tests/test_review_prompt_deploy.py tests/test_repository_contract.py \
  docs/superpowers/plans/2026-07-12-p2-reviewer-deployment.md
git commit -m "feat(review-prompt): deploy P2 reviewer-only skill"
git push origin main
```
