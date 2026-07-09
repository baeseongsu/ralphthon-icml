# ralphthon-icml

Codex plugin and skills repository for `Ralphthon @ICML "Auto Research" supported by Codex`.

This repo packages a small, event-specific Codex surface in the same style as the local Vercel plugin package: plugin manifest, discoverable `SKILL.md` files, slash commands, and lightweight validation.

## Included

- `.codex-plugin/plugin.json` plugin manifest for Codex discovery.
- `skills/hello-ralphthon-icml/SKILL.md` for attendee welcome, QR/POP copy, and event orientation.
- `commands/hello-ralphthon-icml.md` slash command guide for producing a welcome pack.
- `scripts/validate_plugin.py` stdlib validation for required files and frontmatter fields.

## Install

Install this repository as a local Codex plugin from its parent marketplace or plugin source path. The plugin id is:

```text
ralphthon-icml
```

Codex discovers skills from:

```text
skills/
```

## Usage

Ask naturally:

```text
Create a Ralphthon @ICML attendee welcome pack.
Draft QR and POP copy for Ralphthon @ICML.
Brief me on event orientation for guests arriving at NAVER D2SF 강남.
```

Or invoke the command directly:

```text
/hello-ralphthon-icml
```

The command guides the agent through preflight, planning, verification, and a compact output format. When network access is available, the agent should verify the live Luma page before finalizing attendee-visible details.

## Event Facts

- Luma: <https://luma.com/hjuo7auc>
- Title: `Ralphthon @ICML "Auto Research" supported by Codex`
- Venue: `NAVER D2SF 강남`, 서울 서초구 서초대로74길 14 삼성화재 서초타워 18층
- Host/calendar: Team Attention / Goobong Jeong

## Roadmap

| Command | Status | Purpose |
| --- | --- | --- |
| `/hello-ralphthon-icml` | Included | Welcome and orient attendees, operators, QR/POP traffic, and guestbook engagement. |
| `/auto-research` | Planned | Teach and run the auto-research skill/tutorial/wrapper for hackathon participants. |
| `/world-model-ideation` | Planned | Turn world-model research into sponsor narrative, brand awareness, and project ideation. |

## Validation

Run:

```bash
python3 scripts/validate_plugin.py
```

Expected result:

```text
Validation passed
- plugin: ralphthon-icml
- checked files: 4
- skill: hello-ralphthon-icml
- command: /hello-ralphthon-icml
```

## Continuation On Another Mac

```bash
mkdir -p ~/team-attention/code-repos
git clone https://github.com/team-attention/ralphthon-icml.git ~/team-attention/code-repos/ralphthon-icml 2>/dev/null || \
  git -C ~/team-attention/code-repos/ralphthon-icml pull --ff-only
cd ~/team-attention/code-repos/ralphthon-icml
python3 scripts/validate_plugin.py
```

Next work should add Track 1/Track 2 skills only after Ralphthon output formats
are fixed in the ops SOT.

## Privacy

This repository uses public event facts and planning-safe summaries only. Do not paste raw Fireflies transcripts, attendee private data, or unapproved sponsor notes into skills or commands.
