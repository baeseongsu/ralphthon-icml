# Review Prompt N=5 Campaign — Final P2 Deployment Winner

- Date: 2026-07-12
- Campaign: `n5-001`
- Frozen sample: 5 development papers
- Sample manifest SHA-256: `f9c12de011ba185f3aa830f0dcadd26375840bfde31962d73d1c6b93b8a1786f`
- Reviewer/Judge model: `gpt-5.4` / `gpt-5.4`
- Previous parent: `p0`
- Decision: `keep p2`; still final winner after P3/P4

## Final deploy artifact

- Reviewer prompt: `skills/auto-research/assets/review-optimization/smoke-prompt-calibration-v3.md`
- Prompt SHA-256: `sha256:3c25dd6f5759f02e1fcc316439ae66d3912c525237fcc9d24c2f9e89e95dd46f`
- Structured-output schema: `skills/auto-research/assets/review-optimization/generated-review.schema.json`
- Machine-readable selection: `skills/auto-research/assets/review-optimization/deploy-manifest.json`
- Status: manifest `default`; P3/P4 require explicit experimental opt-in

## Hypothesis

Giving significance an independent positive-evidence burden, rather than tying
it to soundness or originality, will preserve the useful evidence calibration
observed in P1 without inflating significance scores.

## Aggregate result

| Candidate | Composite | Reference-score agreement | Judge review quality | Decision |
| --- | ---: | ---: | ---: | --- |
| P0 | 0.895111 | 0.901333 | 0.888889 | baseline |
| P1 | 0.926889 | 0.909333 | 0.944444 | discard: dimension regression |
| P2 | 0.946556 | 0.965333 | 0.927778 | keep / final winner |
| P3 | 0.948556 | 0.936000 | 0.961111 | discard: component regression |
| P4 | 0.939111 | 0.922667 | 0.955556 | discard: no Composite gain |

P2 improved Composite by `+0.051444`, reference-score agreement by
`+0.064000`, and Judge review quality by `+0.038889` relative to P0.

## Dimension gates

| Dimension | P0 | P2 | Delta |
| --- | ---: | ---: | ---: |
| soundness | 0.800000 | 1.000000 | +0.200000 |
| presentation | 1.000000 | 1.000000 | +0.000000 |
| significance | 0.933333 | 0.933333 | +0.000000 |
| originality | 0.933333 | 0.933333 | +0.000000 |
| overall recommendation | 0.840000 | 0.960000 | +0.120000 |

No objective component regressed by more than `0.02`, and no dimension
agreement regressed by more than `0.05`. P2 therefore passes every frozen
selection gate and becomes the next parent.

P3 later achieved a slightly higher raw Composite and higher Judge quality, but
reference-score agreement regressed by `-0.029333`; soundness and overall
recommendation also violated dimension gates. P4 retained some Judge-quality
gain but fell below P2 on Composite and further regressed score agreement.
Consequently neither candidate replaced P2, and the loop stopped after P4.

## Experience carried forward

P1 demonstrated that a higher Composite is insufficient when a shared scoring
rule causes a dimension-specific regression. The campaign now maintains a
cumulative `experience-memory.md` containing every hypothesis, decision,
component and dimension delta, observed gain, regression, and next-candidate
constraint. P2 explicitly used P1's discarded significance failure and retained
its useful evidence calibration while separating significance from soundness.
The sanitized final memory is versioned at
`docs/experiments/review-prompt-n5-001-experience-memory.md`.

## Operational evidence

- Completed papers: `5/5`
- Reviewer/Judge calls: `10`
- Retries/failures: `0/0`
- Active wall time: `199.271` seconds
- Throughput: `90.329` papers/hour
- Aggregate evidence SHA-256: `cd468a53998e0860ab7b820c741d720d1d1ba038380ddefe169dd74f400f1ad3`

## Interpretation boundary

This is a development-sample optimization result over five papers, not a claim
of general review-prompt improvement. No holdout paper was evaluated. The full
generated reviews remain substantively re-identifiable even after exact known
identifier redaction, so W&B publication remains private and access-controlled.

## Direct use

Load the complete P2 Reviewer prompt and require output that validates against
the versioned schema above. Supply extracted paper content only as a clearly
delimited untrusted-data block, with tools, web search, external memories, and
paper-embedded instructions disabled. P2 is the deployment default for this
campaign; it is not a general-production claim beyond the frozen N=5 smoke.
