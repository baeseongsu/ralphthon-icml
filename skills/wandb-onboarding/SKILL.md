---
name: wandb-onboarding
description: Use when signing up or 가입 for W&B Cloud, configuring a personal API key, checking authentication, or creating a first experiment-tracking run or 실험 추적 project.
---

# W&B Onboarding

## Overview

Guide signup with browser assistance, hand sensitive identity steps to the user, then verify the SDK offline before any upload. Read [the current official workflow](references/official-workflow.md) for URLs and commands.

## Preflight

Classify the target as signup, SDK authentication, offline tutorial, or online run. Confirm browser and `uv` availability without inspecting credentials, secret files, cookies, browser storage, or environment-variable values.

## Safety Contract

**Never ask** the user to paste an API key, password, MFA code, or OAuth token into chat. Do not read cookies, browser storage, password managers, `~/.netrc`, environment variable values, or raw credential files.

The user must complete identity-provider selection, credentials, OAuth consent, CAPTCHA, MFA, email verification, legal acceptance, final signup, and API-key copy. Use an **interactive prompt** for the key; never place it in a command argument, source file, generated asset, or repository.

## Workflow

1. Open the official W&B signup page with the available Browser skill. Inspect the current visible options; do not guess selectors when the page changes. If browser control is unavailable, give the exact manual link and checkpoint list.
2. Recommend the Cloud-hosted Free plan and personal entity for an individual tutorial. Present any discovered organization/team separately and let the user choose.
3. Hand off the sensitive signup steps. After the user returns, verify only the visible logged-in state.
4. Guide the user to User Settings → API Keys. The user creates and stores the key privately.
5. For existing credentials, run `wandb login --verify`. For a new key, explain the local credential write, obtain **explicit confirmation**, then run `wandb login --relogin --cloud --verify`. The user enters the key only in the interactive prompt.
6. Copy `assets/wandb-quickstart.py` into a disposable `uv` workspace. Run it first with `WANDB_MODE=offline` and inspect the completed local run.
7. Before any online run, show the target **entity**, **project**, **visibility**, metrics/config fields, code/Git capture setting, and files or data that would upload. Set or verify project visibility in the official UI, bind the approved destination through `WANDB_ENTITY` and `WANDB_PROJECT`, then obtain explicit confirmation.
8. Run once online, then verify the authoritative run URL and visible fields. Report what was uploaded and how to remove or change access if needed.

## Completion Levels

| Level | Evidence |
| --- | --- |
| Account ready | User confirms signup and visible logged-in state |
| SDK ready | `wandb login --verify` succeeds without exposing the key |
| Local tutorial ready | Offline run finishes and creates a local W&B run directory |
| Online tutorial ready | User-approved run appears at the intended entity/project and visibility |

## Stop Conditions

Stop before signup submission, team join/create, trial or payment selection, API-key creation/revocation, credential storage, or online upload unless the user has authorized that exact action. If authentication or upload partially succeeds, inspect status before retrying to avoid duplicate keys or runs.

## Verification

- Verify authentication with `wandb login --verify` without printing the key.
- For offline work, confirm the synthetic run completes and creates a local run directory.
- For online work, verify the authoritative W&B URL, entity, project, visibility, config, metrics, code/Git capture, and every uploaded file or data field.
- Report what was uploaded and the remaining privacy, access-control, deletion, or cleanup work.

## Output

Return the completion level, verified evidence, user handoff, exact planned or completed side effect, authoritative run URL when applicable, and remaining privacy or cleanup work.

## Next Steps

- Offline complete: review the upload card and stop for confirmation.
- Online approved: create one synthetic run and verify it.
- Online declined: preserve the local offline artifact and stop.

## Common Mistakes

- Key in a shell argument → use `wandb login --verify` and its interactive prompt.
- Immediate online test → prove the script with `WANDB_MODE=offline` first.
- Project name without entity/visibility → show all three before confirmation.
- “No dataset” assumed safe → config, metrics, logs, code, and system metadata can still upload.
