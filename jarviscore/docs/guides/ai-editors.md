---
icon: material/robot-happy
title: AI Editor Setup - Copilot, Claude Code, Cursor
description: Teach your AI coding editor JarvisCore. Install the JarvisCore skill for GitHub Copilot and Claude Code, wire up Cursor with AGENTS.md, and point any tool at llms.txt.
---

# AI Editor Setup

Your AI coding editor writes better JarvisCore code when it knows the framework. JarvisCore ships that knowledge as a skill: correct API contracts, the profile decision rule, configuration essentials, and the mistakes we see most, maintained in the same repo as the code it describes.

## Install the skill

From your project root:

```bash
jarviscore init --skill
```

This writes `SKILL.md` to the locations editors discover:

| Editor | Location | Loaded |
|---|---|---|
| GitHub Copilot | `.github/skills/jarviscore/` | Automatically, when a task matches the skill description |
| Claude Code | `.claude/skills/jarviscore/` | Automatically, same trigger model |

Commit these files. Everyone who opens the project gets an editor that knows JarvisCore.

## Cursor and other AGENTS.md tools

Tools that read `AGENTS.md` (Cursor, Codex, and others) get the same knowledge with one line in your project's `AGENTS.md`:

```markdown
When working with jarviscore code, read .github/skills/jarviscore/SKILL.md first.
```

## Any tool: llms.txt

The documentation site serves [llms.txt](https://jarviscore.developers.prescottdata.io/llms.txt), a curated index of these docs for AI ingestion. Point research agents or custom tooling at it instead of scraping.

## Keeping it current

The skill is versioned with the package. After upgrading JarvisCore:

```bash
jarviscore init --skill --force
```
