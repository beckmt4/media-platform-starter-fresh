---
name: unraid-storage
description: Evaluate storage and path decisions against Unraid shares, ZFS pools, scratch placement, and review/quarantine safety.
---

# Unraid Storage Skill

Use this skill when changing paths, mounts, share design, or working-storage behavior.

## Rules

- Fast scratch belongs on NVMe or dedicated scratch, not bulk media pools.
- Degraded or risky pools must not receive new workflow state, model files, or temporary mutation artifacts.
- Keep intake, work, review, and quarantine separate.
- Keep reports, manifests, and workflow state separate from disposable cache.
- Keep adult/JAV review and manifests logically isolated.
- Prefer deterministic mount paths shared across containers and workers.
