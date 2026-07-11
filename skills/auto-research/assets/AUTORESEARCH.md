# A100-micro Campaign Control

## Fixed contract

- Upstream revision: `228791fb499afffb54b46200aca536f79142f117`
- Preset: `A100-micro-v1`, 786,468 parameters
- Identity: one campaign `run_tag`; trials are `baseline`, `candidate-1` through `candidate-3`, and `winner-confirmation`
- Hardware: exactly one NVIDIA A100; no GPU fallback
- Metric: `val_bpb`, lower is better; MFU is diagnostic only
- Budget: 120-second training budget and 240-second external timeout per run; baseline + three candidates + winner confirmation
- Data: one training shard, pinned validation shard, isolated cache
- Frozen identities: dataset fingerprint, tokenizer fingerprint, context, evaluation range

## Before baseline

- [ ] W&B synthetic offline tutorial passed
- [ ] Online entity/project/visibility and the W&B allowlist—including `run_tag`, `trial`, Git SHA, preset, GPU/fingerprints/metrics/status—received explicit confirmation
- [ ] VESSL live hourly price, credit, image, storage, duration, total estimate, and cleanup received explicit confirmation
- [ ] `nvidia-smi` proves exactly one A100
- [ ] Harness and exact parameter count are verified and committed
- [ ] Invariant code, data, tokenizer, and baseline `train.py` SHA-256 manifests are committed in the baseline lock commit
- [ ] A new `experiments.jsonl` is initialized as an empty file; the ledger documentation example was not copied
- [ ] `record_experiment.py` is copied locally; every W&B run remains offline until the separately confirmed `wandb sync`

## Trial rule

Write one hypothesis and one change before editing. After baseline, modify only `train.py`. Before and after every GPU run, verify the frozen code/data/tokenizer manifests and enforce the 240-second external timeout. Keep only a lower `val_bpb`; otherwise restore only that file from the last kept commit. Append the outcome even when it crashes. Trial IDs are unique and sequential; winner-confirmation requires a kept candidate and is last. Do not alter the harness, data, tokenizer, evaluation, logging allowlist, or prior ledger lines.

## Stop rule

Stop after three candidates, after winner confirmation, at the approved wall-clock/cost cap, on platform incompatibility, or at the event hard cut—whichever comes first. Never scale the model or select another GPU automatically.
