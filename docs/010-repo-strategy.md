# Repository Strategy

## Recommended approach

Start with a monorepo.

Why:
- one source of truth
- shared policy files
- shared schemas
- simpler Claude Code context
- easier coordinated PRs across docs, workflows, services, and infra

## When to split later

Split only when one of these becomes true:
- a service needs a different release cadence
- a service becomes reusable beyond this platform
- secrets or access controls need hard repo separation
- the repo becomes too large for practical local work

## Initial top-level modules

- `apps/catalog-api`
- `services/media-policy-engine`
- `services/subtitle-intel`
- `services/jav-normalizer`
- `workers/subtitle-worker`
- `workers/transcode-worker`
- `workflows/n8n`
- `workflows/engine`
- `config`
- `infra`
- `docs`
- `prompts`
- `schemas`
- `tests`
