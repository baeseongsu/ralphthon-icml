# A100-micro-v1 Runbook

Use this only on the Training path when generating new Karpathy evidence. A Track 2-only review of a frozen paper does not use this runbook or W&B/VESSL onboarding.

## 1. Approval and GPU gate

1. Run `vesslctl resource-spec list --usable-only` and select one currently usable single-A100 spec.
2. Show organization/team/cluster/spec, image, hourly price, available credit, storage capacity and price, wall-clock cap, estimated compute/storage cost, and cleanup plan.
3. Obtain **explicit confirmation** for that exact card. Free credit does not waive this gate.
4. After Workspace creation, verify and retain the exact live identity:

   ```bash
   set -euo pipefail
   nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
   GPU_IDENTITY="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader)"
   export GPU_IDENTITY
   test "$(printf '%s\n' "$GPU_IDENTITY" | sed '/^$/d' | wc -l)" -eq 1
   printf '%s\n' "$GPU_IDENTITY" | grep -q "NVIDIA A100"
   ```

   **Do not fall back** to another GPU, CPU, or larger model. Stop on A100, CUDA, or FlashAttention incompatibility.

The [VESSL price page](https://docs.cloud.vessl.ai/pricing/gpu-instances) is a planning reference, not a quote. Use live values at approval time.

## 2. Pin and isolate

Choose a lowercase `RUN_TAG` containing only letters, digits, and single hyphens. Clone, pin, branch, and install the locked environment:

```bash
set -euo pipefail
export RUN_TAG="micro-001"
export UPSTREAM_SHA="228791fb499afffb54b46200aca536f79142f117"
export RUN_TIMEOUT_SECONDS="240"
git clone https://github.com/karpathy/autoresearch.git "autoresearch-$RUN_TAG"
cd "autoresearch-$RUN_TAG"
git switch --detach "$UPSTREAM_SHA"
git switch -c autoresearch/$RUN_TAG
test "$(git rev-parse HEAD)" = "$UPSTREAM_SHA"
uv sync --frozen

export CAMPAIGN_HOME="/approved/persistent/path/$RUN_TAG"
mkdir -p "$CAMPAIGN_HOME" outputs evidence .wandb-offline
touch experiments.jsonl
test ! -s experiments.jsonl
```

Using the campaign-specific `HOME` makes upstream's `~/.cache/autoresearch` an **isolated cache**. Never reuse a cache whose identity is uncertain.

## 3. Freeze executable inputs, prepare, then fingerprint

Freeze the complete pre-baseline preset before preparation:

```text
DEPTH=2
ASPECT_RATIO=64
HEAD_DIM=128
WINDOW_PATTERN="L"
VOCAB_SIZE=1024
MAX_SEQ_LEN=256
DEVICE_BATCH_SIZE=64
TOTAL_BATCH_SIZE=2**14
EVAL_TOKENS=2**18
TIME_BUDGET=120
```

Set `VOCAB_SIZE`, `MAX_SEQ_LEN`, `EVAL_TOKENS`, and `TIME_BUDGET` in `prepare.py`; set the remaining constants in `train.py`. Derived invariants are width 128, one head, gradient accumulation 1, evaluation steps: 16, and exact parameter count **786,468**. Add `assert num_params == 786468` after model construction and `print(f"parameters:       {num_params}")` to the terminal summary.

The successful terminal summary must also print these recorder inputs exactly: `depth`, `vocab_size`, `max_seq_len`, `device_batch_size`, `total_batch_size`, `eval_tokens`, `time_budget`, and `window_pattern`. The recorder rejects a successful run unless they equal the preset above. It also requires `training_seconds >= 120` and `total_seconds <= 240`. The 240-second external timeout includes compile, evaluation, and stalls; it must also fit inside the separately approved Workspace wall-clock and cost cap.

Copy and inspect the exact recorder before calculating any executable fingerprint:

```bash
export PLUGIN_ROOT="/path/to/installed/ralphthon-icml"
export WANDB_VERSION="0.28.0"
test -f "$PLUGIN_ROOT/skills/auto-research/scripts/record_experiment.py"
cp "$PLUGIN_ROOT/skills/auto-research/scripts/record_experiment.py" ./record_experiment.py
python3 record_experiment.py --help
```

Version `0.28.0` is the validated W&B SDK contract. Review and retest the privacy settings before changing it.

Now execute the frozen preparation and hash the actual data, tokenizer, and executable files that the campaign will use:

```bash
HOME="$CAMPAIGN_HOME" uv run prepare.py --num-shards 1
find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
  | sort -z | xargs -0 sha256sum > evidence/data-files.sha256
sha256sum \
  "$CAMPAIGN_HOME/.cache/autoresearch/tokenizer/tokenizer.pkl" \
  "$CAMPAIGN_HOME/.cache/autoresearch/tokenizer/token_bytes.pt" \
  > evidence/tokenizer-files.sha256
sha256sum prepare.py record_experiment.py > evidence/invariant-files.sha256
sha256sum train.py > evidence/baseline-train.sha256
DATASET_FINGERPRINT="$(sha256sum evidence/data-files.sha256 | awk '{print $1}')"
TOKENIZER_FINGERPRINT="$(sha256sum evidence/tokenizer-files.sha256 | awk '{print $1}')"
export DATASET_FINGERPRINT TOKENIZER_FINGERPRINT

git add -- prepare.py train.py record_experiment.py evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
git commit --only -m "chore: freeze A100-micro-v1 executable inputs" -- prepare.py train.py record_experiment.py evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
BASELINE_SHA="$(git rev-parse HEAD)"
LAST_KEPT_SHA="$BASELINE_SHA"
export BASELINE_SHA LAST_KEPT_SHA
git rev-parse HEAD > evidence/baseline-parent.sha
```

Raw data, tokenizer contents, outputs, and checkpoints are never committed. The four small SHA-256 manifests are committed with the three executable inputs so later edits to either a target or its manifest fail closed. The scoped `git add` makes the newly copied recorder and manifests known to Git; `git commit --only` excludes unrelated staged files. Before and after every GPU run, compare the manifests to `BASELINE_SHA`, check their targets, and recreate the data manifest so an added or removed shard also fails. Check `baseline-train.sha256` around the baseline; candidate and confirmation templates bind `train.py` to the exact Git tree they report.

## 4. W&B boundary

First complete the synthetic offline run from `wandb-onboarding`. Before online sync, show entity, project, visibility, and this exact **W&B allowlist**, then obtain **explicit confirmation**:

- `run_tag` and `trial`
- Git SHA, `A100-micro-v1`, and GPU identity
- dataset fingerprint and tokenizer fingerprint
- `val_bpb`, peak VRAM, exact parameter count, and elapsed time
- keep, discard, crash, or confirmation status

Use VESSL's current secure secret/environment mechanism. The user enters credentials privately. Do not place secrets in chat, commands, Git, the run card, ledger, datasets, or checkpoints.

The recorder forces W&B offline mode and writes only the allowlist. Capture its stdout JSON for every trial. Extract the exact run directory from that file before any separately confirmed sync:

```bash
RECORDER_JSON="outputs/$TRIAL.recorder.json"
# The trial-specific recorder invocation writes stdout with: > "$RECORDER_JSON"
WANDB_RUN_DIRECTORY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["wandb_run_directory"])' "$RECORDER_JSON")"
export WANDB_RUN_DIRECTORY
test -d "$WANDB_RUN_DIRECTORY"
```

Do not sync automatically. After the approved destination/upload confirmation, sync each captured run directory with the same destination:

```bash
uv run --with "wandb==$WANDB_VERSION" wandb sync --entity "$WANDB_ENTITY" --project "$WANDB_PROJECT" --skip-console --no-sync-tensorboard "$WANDB_RUN_DIRECTORY"
```

Never pass an API key on that command line.

## 5. Bounded experiment loop

### Baseline template

The explicit branches prevent a failed training command from being recorded as keep:

```bash
set -euo pipefail
TRIAL="baseline"
TRAIN_OUTPUT="outputs/$TRIAL.txt"
RECORDER_JSON="outputs/$TRIAL.recorder.json"
git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
sha256sum --check evidence/invariant-files.sha256
sha256sum --check evidence/data-files.sha256
find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
  | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
sha256sum --check evidence/tokenizer-files.sha256
sha256sum --check evidence/baseline-train.sha256

if timeout --signal=TERM --kill-after=30s "${RUN_TIMEOUT_SECONDS}s" env HOME="$CAMPAIGN_HOME" uv run train.py > "$TRAIN_OUTPUT" 2>&1; then
  git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
  sha256sum --check evidence/invariant-files.sha256
  sha256sum --check evidence/data-files.sha256
  find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
    | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
  sha256sum --check evidence/tokenizer-files.sha256
  sha256sum --check evidence/baseline-train.sha256
  uv run --with "wandb==$WANDB_VERSION" python record_experiment.py \
    --summary "$TRAIN_OUTPUT" --ledger experiments.jsonl \
    --wandb-dir .wandb-offline --entity "$WANDB_ENTITY" \
    --project "$WANDB_PROJECT" --run-tag "$RUN_TAG" --trial "$TRIAL" \
    --git-sha "$(git rev-parse HEAD)" --hypothesis "frozen baseline" \
    --change "none" --status keep --gpu-identity "$GPU_IDENTITY" \
    --dataset-fingerprint "$DATASET_FINGERPRINT" \
    --tokenizer-fingerprint "$TOKENIZER_FINGERPRINT" > "$RECORDER_JSON"
  WANDB_RUN_DIRECTORY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["wandb_run_directory"])' "$RECORDER_JSON")"
  BEST_VAL_BPB="$(awk '/^val_bpb:/ {print $2}' "$TRAIN_OUTPUT")"
  export WANDB_RUN_DIRECTORY BEST_VAL_BPB
else
  TRAIN_EXIT=$?
  FAILURE="baseline training exited $TRAIN_EXIT; inspect $TRAIN_OUTPUT"
  git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
  sha256sum --check evidence/invariant-files.sha256
  sha256sum --check evidence/data-files.sha256
  find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
    | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
  sha256sum --check evidence/tokenizer-files.sha256
  sha256sum --check evidence/baseline-train.sha256
  uv run --with "wandb==$WANDB_VERSION" python record_experiment.py \
    --summary "$TRAIN_OUTPUT" --ledger experiments.jsonl \
    --wandb-dir .wandb-offline --entity "$WANDB_ENTITY" \
    --project "$WANDB_PROJECT" --run-tag "$RUN_TAG" --trial "$TRIAL" \
    --git-sha "$(git rev-parse HEAD)" --hypothesis "frozen baseline" \
    --change "none" --status crash --failure "$FAILURE" \
    --gpu-identity "$GPU_IDENTITY" --dataset-fingerprint "$DATASET_FINGERPRINT" \
    --tokenizer-fingerprint "$TOKENIZER_FINGERPRINT" > "$RECORDER_JSON"
  WANDB_RUN_DIRECTORY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["wandb_run_directory"])' "$RECORDER_JSON")"
  export WANDB_RUN_DIRECTORY
  exit "$TRAIN_EXIT"
fi
git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
sha256sum --check evidence/invariant-files.sha256
sha256sum --check evidence/data-files.sha256
find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
  | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
sha256sum --check evidence/tokenizer-files.sha256
sha256sum --check evidence/baseline-train.sha256
```

### Candidate template

Run at most three sequential candidates. Set one hypothesis and make one `train.py` change before this template; the recorder rejects skipped or duplicate trial IDs.

```bash
set -euo pipefail
TRIAL="candidate-1"
HYPOTHESIS="smaller warmdown improves BPB"
CHANGE="WARMDOWN_RATIO only"
TRAIN_OUTPUT="outputs/$TRIAL.txt"
RECORDER_JSON="outputs/$TRIAL.recorder.json"
git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
sha256sum --check evidence/invariant-files.sha256
sha256sum --check evidence/data-files.sha256
find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
  | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
sha256sum --check evidence/tokenizer-files.sha256

if ! git commit --only -m "experiment: attempt $RUN_TAG $TRIAL" -- train.py; then
  echo "Candidate source commit failed; stop before training." >&2
  exit 1
fi
CANDIDATE_SHA="$(git rev-parse HEAD)"
export CANDIDATE_SHA
if ! test "$(git diff-tree --no-commit-id --name-only -r "$CANDIDATE_SHA")" = "train.py"; then
  echo "Candidate commit changed files outside train.py; stop." >&2
  exit 1
fi
if ! git diff --quiet "$CANDIDATE_SHA" -- train.py; then
  echo "Working train.py differs from the recorded candidate; stop." >&2
  exit 1
fi

if timeout --signal=TERM --kill-after=30s "${RUN_TIMEOUT_SECONDS}s" env HOME="$CAMPAIGN_HOME" uv run train.py > "$TRAIN_OUTPUT" 2>&1; then
  git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
  sha256sum --check evidence/invariant-files.sha256
  sha256sum --check evidence/data-files.sha256
  find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
    | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
  sha256sum --check evidence/tokenizer-files.sha256
  CANDIDATE_VAL_BPB="$(awk '/^val_bpb:/ {print $2}' "$TRAIN_OUTPUT")"
  if python3 -c 'import sys; raise SystemExit(0 if float(sys.argv[1]) < float(sys.argv[2]) else 1)' "$CANDIDATE_VAL_BPB" "$BEST_VAL_BPB"; then
    STATUS="keep"
  else
    STATUS="discard"
  fi
  uv run --with "wandb==$WANDB_VERSION" python record_experiment.py \
    --summary "$TRAIN_OUTPUT" --ledger experiments.jsonl \
    --wandb-dir .wandb-offline --entity "$WANDB_ENTITY" \
    --project "$WANDB_PROJECT" --run-tag "$RUN_TAG" --trial "$TRIAL" \
    --git-sha "$CANDIDATE_SHA" --hypothesis "$HYPOTHESIS" \
    --change "$CHANGE" --status "$STATUS" --gpu-identity "$GPU_IDENTITY" \
    --dataset-fingerprint "$DATASET_FINGERPRINT" \
    --tokenizer-fingerprint "$TOKENIZER_FINGERPRINT" > "$RECORDER_JSON"
  WANDB_RUN_DIRECTORY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["wandb_run_directory"])' "$RECORDER_JSON")"
  export WANDB_RUN_DIRECTORY
  if test "$STATUS" = "keep"; then
    export LAST_KEPT_SHA="$CANDIDATE_SHA"
    export BEST_VAL_BPB="$CANDIDATE_VAL_BPB"
  else
    git restore --source "$LAST_KEPT_SHA" -- train.py
    git commit --only -m "experiment: restore after $TRIAL" -- train.py
  fi
else
  TRAIN_EXIT=$?
  FAILURE="$TRIAL training exited $TRAIN_EXIT; inspect $TRAIN_OUTPUT"
  git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
  sha256sum --check evidence/invariant-files.sha256
  sha256sum --check evidence/data-files.sha256
  find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
    | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
  sha256sum --check evidence/tokenizer-files.sha256
  uv run --with "wandb==$WANDB_VERSION" python record_experiment.py \
    --summary "$TRAIN_OUTPUT" --ledger experiments.jsonl \
    --wandb-dir .wandb-offline --entity "$WANDB_ENTITY" \
    --project "$WANDB_PROJECT" --run-tag "$RUN_TAG" --trial "$TRIAL" \
    --git-sha "$CANDIDATE_SHA" --hypothesis "$HYPOTHESIS" \
    --change "$CHANGE" --status crash --failure "$FAILURE" \
    --gpu-identity "$GPU_IDENTITY" --dataset-fingerprint "$DATASET_FINGERPRINT" \
    --tokenizer-fingerprint "$TOKENIZER_FINGERPRINT" > "$RECORDER_JSON"
  WANDB_RUN_DIRECTORY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["wandb_run_directory"])' "$RECORDER_JSON")"
  export WANDB_RUN_DIRECTORY
  git restore --source "$LAST_KEPT_SHA" -- train.py
  git commit --only -m "experiment: restore after $TRIAL" -- train.py
fi
git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
sha256sum --check evidence/invariant-files.sha256
sha256sum --check evidence/data-files.sha256
find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
  | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
sha256sum --check evidence/tokenizer-files.sha256
```

Repeat sequentially for `candidate-2` and `candidate-3` at most. A nonzero training exit enters only the crash branch with a nonempty `failure`; it cannot fall through to keep/discard.

Rerun the best kept candidate unchanged as `winner-confirmation`. First prove the recorded commit's tree contains the same `train.py` as the kept winner, then use that exact SHA for either outcome:

```bash
set -euo pipefail
git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
sha256sum --check evidence/invariant-files.sha256
sha256sum --check evidence/data-files.sha256
find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
  | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
sha256sum --check evidence/tokenizer-files.sha256
if ! git diff --quiet "$LAST_KEPT_SHA" -- train.py; then
  echo "Current train.py does not match the kept winner; stop." >&2
  exit 1
fi
if ! git diff --quiet -- train.py; then
  echo "Current train.py has uncommitted changes; stop." >&2
  exit 1
fi
CONFIRMATION_SHA="$(git rev-parse HEAD)"
export CONFIRMATION_SHA
if ! test "$(git rev-parse "$CONFIRMATION_SHA:train.py")" = "$(git rev-parse "$LAST_KEPT_SHA:train.py")"; then
  echo "Confirmation commit does not contain the kept winner; stop." >&2
  exit 1
fi
TRIAL="winner-confirmation"
TRAIN_OUTPUT="outputs/$TRIAL.txt"
RECORDER_JSON="outputs/$TRIAL.recorder.json"

if timeout --signal=TERM --kill-after=30s "${RUN_TIMEOUT_SECONDS}s" env HOME="$CAMPAIGN_HOME" uv run train.py > "$TRAIN_OUTPUT" 2>&1; then
  git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
  sha256sum --check evidence/invariant-files.sha256
  sha256sum --check evidence/data-files.sha256
  find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
    | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
  sha256sum --check evidence/tokenizer-files.sha256
  uv run --with "wandb==$WANDB_VERSION" python record_experiment.py \
    --summary "$TRAIN_OUTPUT" --ledger experiments.jsonl \
    --wandb-dir .wandb-offline --entity "$WANDB_ENTITY" \
    --project "$WANDB_PROJECT" --run-tag "$RUN_TAG" --trial "$TRIAL" \
    --git-sha "$CONFIRMATION_SHA" --hypothesis "confirm kept candidate" \
    --change "none" --status confirmation --gpu-identity "$GPU_IDENTITY" \
    --dataset-fingerprint "$DATASET_FINGERPRINT" \
    --tokenizer-fingerprint "$TOKENIZER_FINGERPRINT" > "$RECORDER_JSON"
else
  TRAIN_EXIT=$?
  FAILURE="winner confirmation exited $TRAIN_EXIT; inspect $TRAIN_OUTPUT"
  git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
  sha256sum --check evidence/invariant-files.sha256
  sha256sum --check evidence/data-files.sha256
  find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
    | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
  sha256sum --check evidence/tokenizer-files.sha256
  uv run --with "wandb==$WANDB_VERSION" python record_experiment.py \
    --summary "$TRAIN_OUTPUT" --ledger experiments.jsonl \
    --wandb-dir .wandb-offline --entity "$WANDB_ENTITY" \
    --project "$WANDB_PROJECT" --run-tag "$RUN_TAG" --trial "$TRIAL" \
    --git-sha "$CONFIRMATION_SHA" --hypothesis "confirm kept candidate" \
    --change "none" --status crash --failure "$FAILURE" \
    --gpu-identity "$GPU_IDENTITY" --dataset-fingerprint "$DATASET_FINGERPRINT" \
    --tokenizer-fingerprint "$TOKENIZER_FINGERPRINT" > "$RECORDER_JSON"
fi
WANDB_RUN_DIRECTORY="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["wandb_run_directory"])' "$RECORDER_JSON")"
export WANDB_RUN_DIRECTORY
git diff --quiet "$BASELINE_SHA" -- evidence/data-files.sha256 evidence/tokenizer-files.sha256 evidence/invariant-files.sha256 evidence/baseline-train.sha256
sha256sum --check evidence/invariant-files.sha256
sha256sum --check evidence/data-files.sha256
find "$CAMPAIGN_HOME/.cache/autoresearch/data" -type f -print0 \
  | sort -z | xargs -0 sha256sum | cmp -s - evidence/data-files.sha256
sha256sum --check evidence/tokenizer-files.sha256
```

Claim improvement only when the confirmation result is also below baseline.

The ceiling is five 120-second runs: baseline, three candidates, and confirmation. Stop earlier at the approved cost/wall-clock cap or 16:30 hard cut. Upstream MFU uses an H100 constant, so it is diagnostic only; `val_bpb` is the research metric.

## 6. Closeout

Freeze logs and the confirmed winner, then produce Track artifacts under the evidence rules. Explain the tiny model, one-shard data, short evaluation, A100 environment, failures, and uncertainty. Inspect every recorder JSON and ledger line before approved sync.

Present Pause versus Terminate consequences, including retained-storage cost, and obtain the onboarding skill's confirmation before cleanup.

## Sources

- Karpathy autoresearch pinned source: <https://github.com/karpathy/autoresearch/tree/228791fb499afffb54b46200aca536f79142f117>
- W&B environment variables: <https://docs.wandb.ai/models/track/environment-variables>
- VESSL CLI cheatsheet: <https://docs.cloud.vessl.ai/cli/cheatsheet>
