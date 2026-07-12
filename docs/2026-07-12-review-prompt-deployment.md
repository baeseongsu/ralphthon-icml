# Review Prompt Deployment Selection

## Default

Use the `default` entry in
`skills/auto-research/assets/review-optimization/deploy-manifest.json`.
It resolves to the kept P2 prompt:

```text
skills/auto-research/assets/review-optimization/smoke-prompt-calibration-v3.md
```

Pair it with the strict output schema:

```text
skills/auto-research/assets/review-optimization/generated-review.schema.json
```

At inference time, supply the complete prompt followed by the extracted paper
artifact as a clearly delimited, untrusted-data block. Disable tools, web search,
external memories, and paper-embedded instructions. Accept only JSON that passes
the schema and runtime validator.

## Experimental P3/P4

The full prompts are directly usable for controlled comparison:

- P3: `skills/auto-research/assets/review-optimization/smoke-prompt-reflection-v4.md`
- P4: `skills/auto-research/assets/review-optimization/smoke-prompt-reflection-v5.md`

Both rewrite all seven `Review sections` using the cumulative memory-driven
reflection workflow. They improve several Judge review-quality dimensions on the
fixed N=5 smoke, but they are not defaults because score-agreement gates failed.
Callers must select them explicitly and must not describe them as kept winners.

## Selection boundary

- P2 is the deploy default selected by the frozen N=5 development gate.
- P3/P4 are research artifacts for ablation, qualitative inspection, or a future
  larger development campaign.
- The sealed holdout has not been used to tune this selection.
- The result is a reproducible smoke decision, not evidence of general ICML
  reviewing performance.
