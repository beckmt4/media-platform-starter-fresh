# Media Platform Starter

Starter repository scaffold for a local-first media automation platform built from VS Code with Claude Code, backed by GitHub, and deployed to homelab infrastructure.

## Purpose

This repo is the source of truth for:

- service code
- workflow definitions
- prompts and Claude guidance
- infrastructure definitions
- policy files
- schemas
- tests
- docs

Production media processing still runs locally on homelab hardware. GitHub stores code and definitions only.

## Core rules

1. All operational AI workloads run locally.
2. GitHub Actions may validate code, docs, schemas, and config, but may not run real subtitle generation, translation, media scans, transcodes, or bulk media mutations.
3. Claude Code is a development assistant, not the production runtime.
4. Every workflow change must update policy, tests, and docs together.

## First-day tasks

1. Install VS Code and the Claude Code extension.
2. Clone this repo locally.
3. Copy `.claude/settings.local.example.json` to `.claude/settings.local.json` and adjust local-only paths.
4. Review `CLAUDE.md`.
5. Review `.claude/skills/`.
6. Open the repo in VS Code and use Claude Code from inside the repo root.
7. Create a feature branch and start with `docs/000-architecture-overview.md`.

## Top-level layout

- `.claude/` - Claude Code project config and skills
- `.github/` - PR templates and CI
- `.vscode/` - editor recommendations and tasks
- `apps/` - user-facing apps and APIs
- `services/` - long-running backend services
- `workers/` - stateless media workers
- `workflows/` - orchestration definitions
- `config/` - policy and environment-neutral config
- `infra/` - deployment definitions for local runtime
- `docs/` - architecture and operator docs
- `prompts/` - reusable authoring prompts
- `schemas/` - JSON/YAML schemas
- `tests/` - unit, integration, and policy tests
