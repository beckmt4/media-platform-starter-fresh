# Architecture Overview

This repository uses a source-controlled, local-runtime model.

## Split of responsibility

### GitHub
Stores:
- code
- workflow definitions
- prompts
- schemas
- docs
- infra definitions
- tests

Runs:
- lint
- tests
- schema validation
- build validation

### Homelab runtime
Runs:
- subtitle language detection
- subtitle generation
- subtitle translation
- subtitle scoring
- media inspection
- audio cleanup
- HEVC conversion
- workflow orchestration
- policy evaluation against live files

## Principle

Development AI is separate from production AI.
Claude Code helps build the platform.
Runtime services do the actual media work locally.
