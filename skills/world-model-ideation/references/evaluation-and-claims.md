# World-Model Evaluation and Claim Guardrails

## Candidate Research Patterns

### Action-conditioned state prediction

- Question: does conditioning on an intervention improve next-state or multi-step prediction?
- Baseline: same model without the action/intervention input.
- Metrics: next-state error, rollout error by horizon, calibration, constraint violations.

### Planning with a learned model

- Question: does model-based lookahead improve task success under the same interaction budget?
- Baseline: reactive policy or model-free policy with matched compute/data.
- Metrics: task success, regret, unsafe states, planning latency, sample efficiency.

### Representation for downstream control

- Question: do learned latent dynamics retain information needed for control or forecasting?
- Baseline: static encoder or reconstruction-only representation.
- Metrics: downstream task score, probe performance, robustness under shift.

### Counterfactual intervention modeling

- Question: can the model distinguish outcomes caused by different actions in the same initial state?
- Baseline: observational predictor or scripted heuristic.
- Metrics: intervention ranking, counterfactual error, consistency, false causal conclusions.

## Minimum Evidence Bundle

- frozen dataset/task split and sampling rule;
- model/baseline configuration and compute budget;
- raw predictions or rollouts;
- metric implementation and smoke-test cases;
- at least one negative or failure example;
- uncertainty or repeated-run analysis when feasible;
- trace from each paper claim to a saved result.

## Failure Modes to Consider

- shortcut or leakage from observation to target;
- compounding rollout error;
- physically or logically invalid state transitions;
- action ignored by the model;
- distribution shift and out-of-support interventions;
- baseline given less data, compute, or privileged input;
- visual plausibility mistaken for predictive correctness.

## Public Claim Policy

Do not infer relationships from internal planning notes or draft partner language. For Dalpha or any partner, use only approved public copy. Until verified, treat award category, judging criteria, prize, product relationship, and world-model endorsement as unconfirmed. Exclude private participant/reviewer data, messaging links, raw conversations, tokens, and operational ledgers.

## Track Conversion

- Track 1: use the frozen spec and evidence bundle in the Auto Research short-paper template.
- Track 2: freeze the Track 1 paper and review its soundness, baseline fairness, metric validity, limitations, and evidence trace.
- Both: do not let the review retroactively change experimental results; revise the paper only with a visible version change.
