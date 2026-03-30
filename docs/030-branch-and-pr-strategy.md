# Branch and PR Strategy

## Branch model

- `main` is always deployable for definitions and code
- `feature/*` for implementation work
- `fix/*` for repairs
- `docs/*` for docs-only changes
- `policy/*` for policy-only changes
- `infra/*` for deployment definition changes

## PR rules

- no direct pushes to `main`
- require at least one review
- require CI to pass
- require PR template completion
- squash merge by default
- link docs and policy updates in same PR when behavior changes

## Release approach

Use lightweight tags:
- `v0.x` during bootstrap
- `runtime-*` tags for local runtime bundle cuts
- `policy-*` tags for policy baseline changes
