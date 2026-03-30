# Project Instructions

## Mission

Build and maintain a local-first media automation platform for a homelab.

The repository is the source of truth.
Production execution stays local on homelab hardware.
Do not move operational media processing into GitHub-hosted CI.

## Non-negotiables

- Keep all subtitle generation, translation, language detection, scoring, tagging, media inspection, and media mutation local.
- Do not propose cloud AI inference as a required dependency.
- Treat policy files in `config/policies/` as the contract.
- Treat storage layout in `config/storage-layout.yaml` as authoritative unless a change is explicitly requested.
- Prefer reversible changes.
- Prefer review queues over destructive automation.

## Coding rules

- Python services: Python 3.11+, FastAPI, Pydantic, pytest, ruff.
- Worker jobs: pure Python or shell wrappers around ffmpeg, mkvtoolnix, mediainfo, faster-whisper, and local model runtimes.
- Config is YAML unless JSON schema validation is required.
- Every service must include:
  - README
  - sample config
  - tests
  - structured logging
  - health endpoint or status command
- Every workflow must define:
  - trigger
  - inputs
  - outputs
  - retry behavior
  - timeout
  - review gate
  - state updates

## Architecture rules

- Keep development AI separated from runtime AI.
- Claude Code helps author code, tests, docs, schemas, and workflows.
- Runtime AI services expose local APIs and are called by local workflows.
- Do not couple runtime processing to Claude Code sessions.
- Do not assume all media classes share the same policy.
- Preserve original/native audio.
- Preserve English audio when available.
- Never auto-delete ambiguous subtitle tracks without policy confirmation.

## Change workflow

For significant changes:
1. inspect related docs and policy files first
2. propose the smallest safe change
3. update tests
4. update docs
5. summarize operational impact

## Repository map

- `apps/catalog-api` - source-of-truth catalog and state API
- `services/media-policy-engine` - policy evaluator
- `services/subtitle-intel` - subtitle inspection and language detection
- `services/jav-normalizer` - JAV title normalization and enrichment helpers
- `workers/transcode-worker` - video/audio mutation worker
- `workers/subtitle-worker` - subtitle generation and repair worker
- `workflows/n8n` - orchestration definitions that stay simple enough for n8n
- `workflows/engine` - complex orchestration definitions for custom coordinator
- `config/policies` - policy contracts
- `infra/unraid` - local runtime deployment definitions

## What Claude should ask itself before changing anything

- Is this change for development workflow or runtime workflow?
- Does this belong in GitHub Actions or only in local homelab runtime?
- Does this affect one media class or all media classes?
- Does this require a review gate?
- Is this safe on degraded storage?
