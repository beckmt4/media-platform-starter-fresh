---
name: workflow-authoring
description: Author or update orchestration with explicit state transitions, retries, review gates, and local-runtime boundaries.
---

# Workflow Authoring Skill

Use this skill when creating or changing workflow files.

## Workflow contract

Each workflow must define:

- trigger
- inputs
- outputs
- state transitions
- retries
- timeout
- concurrency limit
- review gate
- rollback or quarantine action
- logging fields

## Placement rules

Use GitHub Actions for:
- lint
- unit tests
- schema validation
- docs validation
- container build validation
- dependency scanning

Use local homelab runtime for:
- media scanning
- subtitle generation
- translation
- subtitle language detection
- transcode
- ffmpeg or mkvmerge mutations
- bulk metadata reconciliation
