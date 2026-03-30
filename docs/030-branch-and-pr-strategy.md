# Branch and PR Strategy

## Model: GitHub Flow

This project uses **GitHub Flow** — the simplest model that enforces review
and keeps `main` deployable at all times.

```
main ──────────────────────────────────────────────────────────▶
        │                   │                    │
        └─ feature/foo ──▶ PR ──▶ squash merge   │
                            └─ feature/bar ──▶ PR ──▶ squash merge
```

**Why not Git Flow or trunk-based?**
- Git Flow adds a `develop` branch that provides no benefit for a single-operator homelab project.
- Trunk-based development works best with a CI gate strong enough to catch regressions — that gate
  is not yet in place. GitHub Flow gives a lightweight review step without the overhead.

---

## Branch rules

### `main`

- Always represents the latest deployable definitions, code, and policy.
- **No direct commits.** All changes arrive via PR.
- Protected: CI must pass before merge.
- Merge strategy: **squash merge** (keeps history linear and readable).

### Feature / fix / docs branches

| Prefix | When to use |
|--------|-------------|
| `feature/` | New capability, service stub, or workflow |
| `fix/` | Bug repair or broken test |
| `docs/` | Documentation-only change |
| `policy/` | Changes to `config/policies/*.yaml` |
| `infra/` | Changes to `infra/unraid/` or deployment definitions |
| `chore/` | Tooling, dependencies, CI, `.gitignore` |

### Naming convention

```
<prefix>/<scope>-<short-description>
```

Examples:
```
feature/catalog-api-skeleton
feature/subtitle-intel-stub
feature/policy-engine-models
fix/subtitle-confidence-threshold
docs/architecture-cleanup
policy/anime-subtitle-rules
infra/unraid-catalog-api-compose
chore/ruff-config
```

Rules:
- All lowercase, hyphen-separated.
- Scope is the service or area (`catalog-api`, `subtitle-intel`, `policy`, `docs`).
- Description is imperative and ≤ 5 words (`add-health-endpoint`, not `added-the-new-health-endpoint`).
- No personal identifiers in branch names.

---

## Branch lifecycle

```
1. git checkout main && git pull
2. git checkout -b feature/<scope>-<description>
3. Work in small commits (conventional commits format)
4. Push and open PR against main
5. CI passes → squash merge → delete branch
```

**Always branch from `main`.** Never branch from another feature branch.
Stacked branches (branch-on-branch) are a last resort for large sequential
changes and must be documented in the PR body.

Keep branches short-lived: aim to merge within **3 working days**. Longer
branches accumulate merge debt and make review harder.

---

## Commit message convention

Use **Conventional Commits**:

```
<type>(<scope>): <short summary>

[optional body]
[optional footer]
```

Types: `feat`, `fix`, `docs`, `chore`, `test`, `refactor`, `policy`, `infra`

Examples:
```
feat(catalog-api): add review queue resolve endpoint
fix(policy-engine): adult confidence threshold off-by-one
docs(architecture): clarify dev vs runtime AI boundary
policy(subtitles): add anime signs-songs keep rule
chore: add egg-info to .gitignore
```

---

## PR rules

- No direct pushes to `main`.
- Use the PR template in `.github/pull_request_template.md`.
- Link the related docs or policy change in the same PR when behavior changes.
- At least one self-review pass before merging (sole-operator projects).
- CI must be green: lint, tests, schema/config validation.
- Squash merge — the squash commit message becomes the canonical record.
- Delete the branch after merge.

---

## What belongs in GitHub Actions vs local runtime

| Allowed in CI | Not allowed in CI |
|---------------|-------------------|
| ruff lint | subtitle generation |
| pytest (unit + policy tests) | media file scanning |
| YAML schema validation | transcodes |
| config structure validation | translation |
| docs checks | file mutations on media |

CI validates code and definitions. Real media work runs only on homelab hardware.

---

## Release tagging

| Tag pattern | Purpose |
|-------------|---------|
| `v0.x.y` | Bootstrap milestones |
| `runtime-YYYY-MM-DD` | Local runtime bundle cuts deployed to homelab |
| `policy-YYYY-MM-DD` | Policy baseline snapshots (before bulk policy changes) |

Tagging is manual. Tag from `main` only, after merge.

---

## Current branch status (bootstrap phase)

During initial scaffold construction it is acceptable to stack feature work
linearly and merge everything to `main` at a natural milestone. Once `main`
is established as the baseline, all subsequent changes follow the rules above.
