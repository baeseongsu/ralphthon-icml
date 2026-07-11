---
name: world-model-ideation
description: Use when turning a world-model or 월드모델, simulation, predictive-state, embodied-agent, intervention-model idea or 아이디어 into a testable Ralphthon research project or review target.
---

# World Model Ideation

## Overview

Convert an appealing demo concept into a falsifiable research claim, fair comparison, minimum experiment, and Track-ready artifact. Research substance comes before brand copy.

Read [the evaluation patterns and claim guardrails](references/evaluation-and-claims.md). Copy `assets/research-spec-template.md` into the project workspace.

## Preflight

Identify the environment, available observations and actions, prediction target, data and compute budget, deadline, target Track, permitted evidence, and external claims that require public verification.

## Idea Contract

Every selected idea must specify:

1. environment, state, observation, action/intervention, and prediction target;
2. one **falsifiable hypothesis**;
3. one named **baseline** that lacks the proposed world-model capability;
4. one primary **evaluation metric** and success threshold;
5. a **minimum experiment** that can disprove the hypothesis;
6. required evidence, compute/data budget, and reproducibility inputs;
7. at least three **failure mode** categories, including shortcut learning and distribution shift.

Reject ideas that cannot distinguish a world model from a scripted animation, generic predictor, or prompt-only demo.

## Workflow

1. Generate three candidate questions, not three product slogans. Score them for falsifiability, feasible evidence, baseline fairness, and deadline fit.
2. Freeze the research spec for the best candidate. Define the smallest end-to-end experiment before designing polished UI.
3. Run a smoke test that checks state/action alignment and metric calculation. Preserve negative and failed evidence.
4. Compare to the baseline and calibrate claims to uncertainty and sample size.
5. Route the result:
   - **Track 1:** use `auto-research` to produce the 2–4 page paper, workflow, and self-review.
   - **Track 2:** use `auto-research` to review a frozen world-model paper in ICML style.

Use project-native experiment commands. Preserve raw predictions, configs, metric outputs, exclusions, negative evidence, and failures before aggregation.

## Public-Claim Guardrail

**Do not claim** that Dalpha sponsors world-model research, uses world models, requires the topic, endorses the direction, or judges it unless approved public material says so. The Dalpha special-award category, criteria, and final wording are **unconfirmed**; do not invent a prize, benefit, relationship, or product capability.

World Model is an ideation theme, not a third Ralphthon Track. Keep sponsor or partner narrative separate from the scientific claim and mark proposed copy as draft.

## Verification

- Try to disprove the hypothesis rather than selecting only favorable cases.
- Check baseline fairness, metric validity, state/action alignment, sample definition, uncertainty, and representative failure cases.
- Confirm raw predictions, configs, metric outputs, and failed runs remain traceable.
- Remove unverified sponsor, award, partner, product, or endorsement statements from public output.

## Output

Return the ranked candidates, frozen research spec, minimum experiment, Track 1/Track 2 conversion path, evidence status, blockers, and every external claim that still needs public verification.

## Next Steps

- Evidence ready: continue with `auto-research` for Track 1.
- Frozen paper ready: continue with `auto-research` for Track 2.
- External claim unverified: omit it from public output and continue the research independently.

## Common Mistakes

- Beautiful simulation with no counterfactual test → add an action-conditioned prediction and baseline.
- Accuracy only → include calibration, consistency, rollout error, or task success as appropriate.
- One successful anecdote → predefine a sample and failure analysis.
- Sponsor-led premise → remove the brand assumption and verify public facts separately.
