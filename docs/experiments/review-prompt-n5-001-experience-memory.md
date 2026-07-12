# Review Prompt Optimization Experience Memory

This versioned snapshot contains only aggregate optimization experience. It is
the sanitized counterpart of the runtime memory consumed by the reflection
stage; raw papers, per-paper labels, reference-review prose, and identifiers are
not included.

## Baseline — p0

- Composite: 0.895111
- Reference-score agreement: 0.901333
- Judge review quality: 0.888889

## Experience — p1 — discard

- Parent: p0
- Hypothesis: Explicit evidence-to-ordinal calibration reduces score error and improves reference-based review quality.
- Decision: discard (`dimension_regression`)
- Composite delta: +0.031778
- Reference-score agreement delta: +0.008000
- Judge review-quality delta: +0.055556
- Dimension agreement deltas:
  - originality: +0.000000
  - overall_recommendation: +0.040000
  - presentation: +0.000000
  - significance: -0.066667
  - soundness: +0.066667
- Meta-level experience:
  - Preserve the overall-recommendation and soundness gains.
  - Do not repeat the significance regression.
  - Optimize the gated objective rather than Composite alone.

## Experience — p2 — keep

- Parent: p0
- Hypothesis: An independent positive-evidence burden for significance preserves review-quality gains without significance inflation.
- Decision: keep (`none`)
- Composite delta: +0.051444
- Reference-score agreement delta: +0.064000
- Judge review-quality delta: +0.038889
- Dimension agreement deltas:
  - originality: +0.000000
  - overall_recommendation: +0.120000
  - presentation: +0.000000
  - significance: +0.000000
  - soundness: +0.200000
- Meta-level experience:
  - Preserve direct evidence calibration and dimension independence.
  - P2 becomes the current parent.

## Experience — p3 — discard

- Parent: p2
- Hypothesis: Explicit claim-evidence-decision chains in all review sections improve rationale consistency and specificity without score-calibration regression.
- Decision: discard (`component_regression`)
- Composite delta: +0.002000
- Reference-score agreement delta: -0.029333
- Judge review-quality delta: +0.033333
- Dimension agreement deltas:
  - originality: +0.000000
  - overall_recommendation: -0.080000
  - presentation: +0.000000
  - significance: +0.000000
  - soundness: -0.066667
- Meta-level experience:
  - Preserve the Judge-quality and rationale-consistency insight.
  - Do not repeat the conservative shift in soundness and overall recommendation.
  - Detailed review structure must be decoupled from ordinal severity.

## Experience — p4 — discard

- Parent: p2
- Hypothesis: Restricting detailed evidence chains to central, score-driving points recovers P3 score calibration while retaining review-quality gains.
- Decision: discard (`no_composite_gain`)
- Composite delta: -0.007444
- Reference-score agreement delta: -0.042667
- Judge review-quality delta: +0.027778
- Dimension agreement deltas:
  - originality: +0.000000
  - overall_recommendation: -0.080000
  - presentation: +0.000000
  - significance: +0.000000
  - soundness: -0.133333
- Meta-level experience:
  - Wording the structure as lighter weight did not recover calibration.
  - Future work must add a direct non-penalization or adjacent-anchor calibration mechanism rather than only reducing checklist scope.
  - P2 remains the final parent; the loop stops after P4.
