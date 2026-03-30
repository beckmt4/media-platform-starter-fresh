---
name: architecture-review
description: Review design changes for separation of development AI, runtime AI, storage safety, and media-class policy boundaries.
---

# Architecture Review Skill

Use this skill when reviewing architecture, repository layout, workflow boundaries, or deployment strategy.

## Checklist

- Confirm development AI and runtime AI are separated.
- Confirm GitHub stores code and definitions only.
- Confirm production workloads remain local.
- Confirm storage changes are safe for current pool health.
- Confirm the proposal identifies which media classes are affected.
- Confirm destructive actions have review gates.
- Confirm docs, tests, and policy files change together.

## Output format

1. decision
2. impacted areas
3. risks
4. missing policy updates
5. safe next step
