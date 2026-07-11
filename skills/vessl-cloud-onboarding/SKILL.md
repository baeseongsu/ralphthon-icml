---
name: vessl-cloud-onboarding
description: Use when signing up or 가입 for current VESSL Cloud, installing or authenticating vesslctl, checking organizations and teams, or preparing a first billable GPU Workspace, Job, or 기본 세팅.
---

# VESSL Cloud Onboarding

## Overview

Use only the current VESSL Cloud at **https://cloud.vessl.ai** and the `vesslctl` CLI. Separate free/read-only setup verification from billable compute creation. Read [the official workflow and command reference](references/official-workflow.md) when acting.

## Preflight

Classify the target as signup, CLI verification, cost review, or paid tutorial. Confirm the current product URL and whether `vesslctl` is installed without reading credentials or `~/.config/vesslctl/config.yaml`.

## Product and Secret Boundary

Do not mix the current Cloud product with **legacy** VESSL MLOps, its `vessl` Python CLI, or its Organization/Project model. Current Cloud uses Organization → Team → Workspace/Job.

Never ask for or inspect passwords, MFA codes, OAuth tokens, access-token values, cookies, browser storage, or `~/.config/vesslctl/config.yaml`. The user completes credentials, OAuth/SAML, CAPTCHA, email verification, legal acceptance, age confirmation, and final signup submission.

## Workflow

## Phase 1 — Signup and Free Setup Verification

1. Open the official signup page with the available Browser skill and inspect visible state. If browser control is unavailable, give the official link and manual checkpoints.
2. Hand sensitive signup and Organization creation submission to the user. Explain that the creator may receive administrative responsibility.
3. Before CLI installation, inspect the official install instructions, explain the binary/PATH change, and obtain **explicit confirmation**.
4. Enforce browser authentication with `vesslctl auth login --web`; the user completes the sensitive browser step. Do not fall back to terminal password entry.
5. Verify only with non-secret, read-only commands:

```bash
vesslctl auth status
vesslctl config show
vesslctl billing show
vesslctl org list
vesslctl team list
vesslctl cluster list
vesslctl resource-spec list --usable-only
```

Completing these checks is a valid stopping point. Do not imply that a paid tutorial is required for setup success.

## Phase 2 — Billable Compute Gate

Copy `assets/workspace-cost-card.md` and fill it from current official UI/CLI values. Before `vesslctl workspace create` or `vesslctl job create`, show Organization/Team, cluster/region, resource spec and GPU count, availability, **hourly price**, current **credit**, container **image**, storage capacity/rate/estimated duration and cost, mounts, exposed ports, expected **duration**, and **cleanup** plan. Obtain explicit confirmation for that exact resource.

After approval, create the smallest suitable resource, run `python -c 'print("Hello, VESSL Cloud!")'`, verify logs/output, and return immediately to cleanup.

## Cleanup Gate

**Pause** stops compute but can preserve state and leave storage charges. **Terminate** is destructive and stops the Workspace; verify any separate storage before claiming that all charges end. Show the consequence and obtain explicit confirmation immediately before either action. Never rely on credit exhaustion as automatic cleanup.

## Completion Levels

| Level | Evidence |
| --- | --- |
| Account ready | User confirms verified signup and Organization |
| CLI ready | Auth/config/org/team checks succeed without revealing tokens |
| Cost reviewed | Live cost card is complete; no compute created |
| Tutorial complete | Approved resource prints Hello, VESSL Cloud and reaches a verified cleanup state |

## Verification

- Verify auth/config/org/team/cluster/resource-spec state without exposing secrets.
- For compute, verify the exact approved resource, Hello VESSL output, live hourly exposure, current billing state, and final Pause/Terminate/storage state.
- Never claim all charges ended until compute and any separate persistent storage are both checked.

## Output

Return the completion level, verified evidence, waiting-for-user action, exact planned or completed side effect, hourly exposure, current billing/credit state, and cleanup state.

## Next Steps

- CLI ready: stop without cost, or prepare the live cost card.
- Cost approved: create one minimal resource and run Hello VESSL.
- Tutorial complete: obtain and execute a separate cleanup decision.

## Common Mistakes

- Using `vessl configure` → stop; that is the legacy product.
- “Cheapest GPU” without live inventory → compare `resource-spec list --usable-only` and prices.
- Creating before cleanup planning → fill the complete cost card first.
- Claiming Pause is free → report continuing storage or related charges.
