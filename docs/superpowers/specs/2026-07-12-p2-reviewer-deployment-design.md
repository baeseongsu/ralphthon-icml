# P2 Reviewer-Only Deployment Design

## Status

- Date: 2026-07-12
- Approved direction: extend the existing `auto-research` skill
- Deployment winner: `p2`
- Deployment manifest: `skills/auto-research/assets/review-optimization/deploy-manifest.json`
- P2 prompt SHA-256: `sha256:3c25dd6f5759f02e1fcc316439ae66d3912c525237fcc9d24c2f9e89e95dd46f`

## Goal

Add a label-free deployment path that accepts one local PDF and runs only the
kept P2 Reviewer. The command produces a strict structured review, a readable
Markdown rendering, and reproducibility metadata without invoking the Judge or
loading reference-review data.

## Non-goals

- Do not run prompt optimization, candidate selection, or holdout evaluation.
- Do not accept human-review JSON, numeric labels, reference prose, or paper IDs.
- Do not invoke the Judge or write W&B runs.
- Do not promote P3 or P4; both remain experimental discarded candidates.
- Do not claim that the N=5 development winner is universally optimal.

## Chosen architecture

Extend `auto-research` instead of creating another plugin skill. Add one thin
Reviewer-only runner that reuses the existing authenticated Codex isolation,
PDF extraction, bounded retry, structured-output validation, and atomic output
directory helpers.

### Components

1. `deploy-manifest.json` remains the source of truth for the selected candidate
   and gains the pinned Reviewer model plus output-schema SHA-256 required by
   runtime verification.
2. `review_prompt_deploy.py` loads the manifest, resolves its paths relative to
   the repository root, and verifies the P2 prompt hash before inference.
3. The runner extracts text with `pdftotext`, wraps it as untrusted paper data,
   and makes one no-tools, read-only, ephemeral `codex exec` Reviewer call.
4. The generated object is validated against `generated-review.schema.json` and
   the existing Python validator.
5. The existing `auto-research` skill documents the deployment trigger, command,
   outputs, and privacy boundary.

## Command contract

```bash
python3 skills/auto-research/scripts/review_prompt_deploy.py \
  --paper-pdf /absolute/path/paper.pdf \
  --output-dir /absolute/path/review-output \
  --model gpt-5.4
```

Required inputs:

- `--paper-pdf`: one existing PDF with sufficient extractable text.
- `--output-dir`: a path that does not already exist.

Optional operational inputs:

- `--model`, defaulting to the campaign model recorded for P2.
- Existing binary overrides and bounded timeout/retry controls used by the
  authenticated Codex runner.

The deployment command does not expose prompt selection. Changing the selected
prompt requires a reviewed change to the deployment manifest.

## Data flow and privacy boundary

```text
local PDF
  -> deterministic text extraction
  -> P2 prompt + delimited untrusted paper text
  -> isolated Reviewer Codex call
  -> schema validation
  -> review.json + review.md + provenance.json
```

The model receives only the pinned P2 prompt and extracted paper text. It does
not receive a human review, human score, reference text, Judge prompt/output,
W&B state, optimization memory, or holdout artifact. The runner does not persist
extracted paper text or upload any result.

## Outputs

The fresh output directory contains exactly:

- `review.json`: schema-valid Reviewer result.
- `review.md`: deterministic human-readable rendering of the same result.
- `provenance.json`: candidate ID, prompt/schema/PDF hashes, model, Codex CLI
  version, auth mode, token usage, attempts, retries, and elapsed time.

The Markdown renderer preserves all structured fields: summary, strengths,
weaknesses, questions, limitations, ethical concerns, evidence trace, scores,
and score rationales. It does not add model-generated claims beyond the JSON.

## Failure behavior

- Reject a missing/non-PDF input before model invocation.
- Reject a manifest path escape, unknown manifest fields, non-`keep` default,
  non-P2 default, or prompt/schema hash mismatch.
- Require authenticated Codex preflight before inference.
- Permit at most two recorded attempts using the existing retry policy.
- Reject schema-invalid output.
- Remove a newly reserved output directory on any failure; never overwrite an
  existing deployment result.

## Testing strategy

Use test-first development.

1. Contract test: the manifest selects P2 and its recorded hash matches the
   prompt bytes.
2. Reviewer-only boundary test: the request contains the P2 prompt and paper
   block but no Judge/reference/label block.
3. Successful-run test: a valid injected Reviewer response creates exactly the
   three outputs and the JSON/Markdown/provenance agree.
4. Failure test: invalid output or inference failure leaves no output directory.
5. CLI/default test: no prompt or human-review/Judge argument exists.
6. Regression suite: all existing repository and review-prompt tests remain green.

## Acceptance criteria

- A user can run P2 on one local PDF using Codex ChatGPT authentication and no
  human-review artifact.
- The deployed prompt is resolved only through the checked-in manifest and its
  SHA-256 is verified before inference.
- The run performs exactly one Reviewer call and zero Judge calls.
- Outputs are reproducible, schema-valid, and contain no stored extracted text.
- The skill documentation contains a copy-pasteable Reviewer-only example and
  clearly states the N=5 interpretation boundary.
