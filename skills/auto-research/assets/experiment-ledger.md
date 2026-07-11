# experiments.jsonl Template

For a new campaign, initialize it as an empty file with `touch experiments.jsonl`, then confirm it has no lines. If the file already exists, do not truncate or replace it. Write one compact JSON object per completed run.

The object below is a schema example only. **Do not copy** it into the ledger; it is not evidence and is deliberately not a placeholder baseline:

```json
{"run_tag":"example-only","trial":"candidate-1","git_sha":"abcdef0","hypothesis":"one documented hypothesis","change":"one train.py change","val_bpb":1.2345,"peak_vram_mb":2048.0,"parameters":786468,"elapsed_seconds":140.0,"status":"discard","failure":null,"next_hint":"try a different single change","wandb_run":"offline-example"}
```

`run_tag` identifies the campaign and `trial` identifies one run within it. The W&B allowlist includes both `run_tag` and `trial`; ledger-only fields such as hypothesis, change, failure, and next hint are not uploaded as W&B config or metrics.

Allowed status values are `keep`, `discard`, `crash`, and `confirmation`. Baseline is keep/crash; candidates are keep/discard/crash; winner-confirmation is confirmation/crash and requires a prior kept candidate. Record baseline first, candidates sequentially without duplicates, and confirmation last. A keep, discard, or confirmation requires complete measured values for `val_bpb`, `peak_vram_mb`, `parameters` (exactly 786468), and `elapsed_seconds`. A crash requires a nonempty `failure`. Never add credentials, private participant data, dataset contents, or checkpoint contents. Never rewrite or remove an earlier line.
