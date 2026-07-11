# W&B Cloud Official Workflow

## Official Sources

- Signup: <https://wandb.ai/signup>
- Models Quickstart: <https://docs.wandb.ai/models/quickstart>
- CLI login: <https://docs.wandb.ai/models/ref/cli/wandb-login>
- User settings and API keys: <https://docs.wandb.ai/platform/app/settings-page/user-settings>
- Pricing: <https://wandb.ai/site/pricing/>

Verify the live official page when UI labels or plan details matter.

## Signup Handoff

The official signup flow may offer Apple, GitHub, Google, Microsoft, or email/password. Browser automation may open and inspect the page. The user completes provider choice, credentials, OAuth approval, CAPTCHA/MFA, email verification, legal acceptance, and final submission.

For a personal tutorial, recommend the Cloud-hosted Free plan and personal entity. Do not automatically join an organization, create a team, begin a trial, or make a payment choice.

## API Key and Login

Personal API keys are created in User Settings and the full secret may be shown only at creation. For a new key, the user stores it in a password or secrets manager and enters it directly into the forced terminal prompt:

```bash
uv tool run --from wandb wandb login --relogin --cloud --verify
```

The installed-project equivalent is `uv run wandb login --relogin --cloud --verify`. If credentials already exist and the user only wants validation, do not force a new prompt:

```bash
uv run wandb login --verify
```

Do not echo the key, pass it as an argument, print `WANDB_API_KEY`, or read credential files. Login may write credentials locally; explain this before requesting confirmation.

## Offline-First Tutorial

```bash
mkdir wandb-quickstart
cd wandb-quickstart
uv init --bare
uv add wandb
cp <skill-path>/assets/wandb-quickstart.py .
WANDB_MODE=offline uv run wandb-quickstart.py
```

Confirm a completed offline run before proposing an upload.

## Online Gate

Present this card and obtain explicit confirmation:

- entity:
- project:
- visibility/access:
- config keys and values:
- metric keys:
- code/Git capture:
- files, tables, artifacts, stdout, or system metadata expected to upload:

Before running, set or verify the approved project visibility in the W&B UI. Bind the approved destination explicitly rather than relying on the default team:

Then run:

```bash
WANDB_ENTITY=<approved-entity> \
WANDB_PROJECT=<approved-project> \
WANDB_MODE=online \
uv run wandb-quickstart.py
```

Verify the URL printed by W&B and inspect the intended entity, project, visibility, config, and metrics on the official run page.
