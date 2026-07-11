# ralphthon-icml

Codex plugin and skill repository for `Ralphthon @ICML "Auto Research" supported by Codex`.

The plugin exposes five event workflows as discoverable Agent Skills.

## Included

| Skill | Purpose |
| --- | --- |
| `hello-ralphthon-icml` | Welcome attendees and prepare QR/POP orientation copy. |
| `auto-research` | Build general Track 1 research, run bounded Karpathy A100-micro training, or package a no-compute Track 2 Review Agent and result. |
| `wandb-onboarding` | Guide W&B Cloud signup, private API-key login, and an offline-first synthetic run. |
| `vessl-cloud-onboarding` | Verify current VESSL Cloud and `vesslctl` setup before optional billable compute. |
| `world-model-ideation` | Convert a world-model concept into a falsifiable experiment and Track path. |

Each skill may include `references/` for detailed official guidance, `assets/` for reusable templates, and `agents/openai.yaml` for Codex UI metadata.

## Install

Install this repository as a local Codex plugin from its parent marketplace or plugin source path. The plugin ID is:

```text
ralphthon-icml
```

Codex discovers skills from `skills/`. Workflow behavior, verification, and output contracts live in each `SKILL.md`.

## Usage

Ask naturally or name a skill:

```text
Create a Ralphthon @ICML attendee welcome pack.
Use auto-research to freeze a research spec for Track 1 and Track 2.
Use wandb-onboarding to verify a synthetic W&B run offline before upload.
Use vessl-cloud-onboarding to check VESSL Cloud pricing without creating compute.
Use world-model-ideation to compare three falsifiable world-model questions.
```

W&B and VESSL Cloud use a hybrid browser-and-terminal workflow. Codex can open official pages, inspect visible state, and run safe diagnostics. The user handles credentials, OAuth, MFA, CAPTCHA, email verification, legal acceptance, API keys, payment details, and final signup submission.

## Auto Research Paths

`auto-research` starts by choosing exactly one mutually exclusive path:

- **Training path:** run a bounded experiment campaign based on [`karpathy/autoresearch` at commit `228791fb499afffb54b46200aca536f79142f117`](https://github.com/karpathy/autoresearch/commit/228791fb499afffb54b46200aca536f79142f117), then use verified evidence for a Track 1 paper. This path requires W&B and VESSL Cloud onboarding.
- **General Track 1 path:** use a non-Karpathy workflow or credible existing evidence to produce the research agent workflow, paper, and self-review. It **does not automatically require W&B, VESSL, or A100**.
- **Track 2-only:** freeze a reusable **Track 2 Review Agent** as `review-agent.md`, then use it to review an existing Track 1 paper without provisioning compute, cloning the training repository, or claiming a new experiment. Submit both the agent artifact and review result.

The Training path has one default preset, `A100-micro-v1`:

| Setting | Value |
| --- | ---: |
| Layers (`DEPTH`) | 2 |
| Width | 128 |
| Attention heads | 1 |
| Vocabulary | 1,024 |
| Context | 256 |
| Window | `L` |
| Device batch | 64 |
| Total batch | `2**14` |
| Gradient accumulation | 1 |
| Evaluation tokens | `2**18` |
| Evaluation steps | 16 |
| Training budget per run | 120 seconds |
| Expected parameters | 786,468 |

The campaign prepares one isolated data shard, runs one baseline, at most three candidate trials, and one confirmation rerun. It permits one hypothesis and one `train.py` change per candidate. Only a lower `val_bpb` that repeats in the confirmation run may support a Track 1 claim.

Experiment metadata is written first to the local append-only recorder `skills/auto-research/scripts/record_experiment.py`; W&B offline is the mandatory smoke-test mode. Before any approved sync, show the W&B entity, project, visibility, and upload allowlist. Never upload the dataset, checkpoint, credentials, or API key.

Before VESSL creates anything billable, query `vesslctl resource-spec list --usable-only` and show a live cost card with the exact resource spec, hourly price, credits, image, expected wall time, storage exposure, and cleanup choice. The run must use a confirmed **single A100**, verified with `nvidia-smi`; it must stop rather than silently fall back to another GPU or enlarge the model.

Manual live-account boundary: repository tests do not create accounts, submit OAuth/MFA/CAPTCHA, enter an API key, sync a W&B run, authenticate VESSL, or create/stop paid compute. Those steps remain user-controlled and require their documented action-time confirmations.

Test the full safety gate with this prompt:

```text
Use auto-research in Training path with A100-micro-v1. Verify W&B offline first, show the approved sync fields, inspect the current VESSL single-A100 live cost, and stop for confirmation before creating compute.
```

## Public Event Facts

- Luma: <https://luma.com/hjuo7auc>
- Title: `Ralphthon @ICML "Auto Research" supported by Codex`
- Venue: `NAVER D2SF 강남`, 서울 서초구 서초대로74길 14 삼성화재 서초타워 18층
- Track 1: AI Scientist agent plus a 2–4 page workshop-style short paper and self-review.
- Track 2: Review Agent plus an ICML-style structured review of a Track 1 paper.
- Ralph Loop: 12:30–15:30.
- Human editing and final paper/agent submission: 15:30–16:30.
- The final paper/agent hard cut is 16:30; peer and self-review follow.

Verify live attendee-visible facts before publishing event copy.

## Safety Boundaries

- Never commit passwords, API keys, access tokens, payment information, credentials, or account-specific configuration.
- Never publish private participant or reviewer data, guest exports, outreach status, private messaging links, raw Slack/Telegram/Gmail/Fireflies content, or internal operations ledgers.
- Do not fabricate research results, citations, runs, reviews, metrics, or evidence.
- Treat Dalpha award wording, criteria, prizes, product relationships, and world-model endorsement as unconfirmed until approved public copy exists.
- W&B online runs require a review of entity, project, visibility, and uploaded data.
- VESSL Cloud Workspace/Job creation requires live price, credit, resource, duration, and cleanup confirmation.

## Validation

Run:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate_plugin.py
```

Expected catalog output:

```text
Validation passed
- plugin: ralphthon-icml
- skills (5): auto-research, hello-ralphthon-icml, vessl-cloud-onboarding, wandb-onboarding, world-model-ideation
```

Validate an individual skill with the skill-creator helper:

```bash
uv run --with pyyaml ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/<skill-name>
```

## Continue on Another Mac

```bash
git clone https://github.com/team-attention/ralphthon-icml.git
cd ralphthon-icml
python3 -m unittest discover -s tests -v
python3 scripts/validate_plugin.py
```
