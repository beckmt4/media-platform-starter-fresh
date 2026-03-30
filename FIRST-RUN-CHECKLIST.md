# First Run Checklist

## 1. Put this repo under GitHub

1. Create a new empty GitHub repository.
2. Copy this folder into your workstation projects directory.
3. Open a terminal in the folder.
4. Run:

```bash
git init
git branch -M main
git add .
git commit -m "Initial media platform scaffold"
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

## 2. Open in VS Code

1. Open the folder in VS Code.
2. Install the recommended extensions when prompted.
3. Verify the Claude Code extension is installed and signed in.

## 3. Set local-only Claude settings

1. Copy `.claude/settings.local.example.json` to `.claude/settings.local.json`.
2. Put workstation-specific paths only in the local file.
3. Do not commit `.claude/settings.local.json`.

## 4. Read the control files first

Read in this order:
1. `README.md`
2. `CLAUDE.md`
3. `docs/000-architecture-overview.md`
4. `docs/020-vscode-claude-setup.md`
5. `config/media-domains.yaml`
6. `config/storage-layout.yaml`
7. `config/policies/*.yaml`

## 5. Use Claude Code the right way

Start from repo root and use this first message:

> Read `CLAUDE.md`, `README.md`, `docs/000-architecture-overview.md`, `config/media-domains.yaml`, `config/storage-layout.yaml`, and the relevant policy files. Summarize the current scaffold, identify the smallest safe next implementation step, then list the exact files you will create or modify before making changes.

## 6. First implementation target

Implement in this order:
1. `apps/catalog-api` skeleton
2. `services/media-policy-engine` contract models
3. `config/policies` validation tests
4. `services/subtitle-intel` scanner stub
5. `services/jav-normalizer` stub
6. `workers/subtitle-worker` interface stub
7. `workers/transcode-worker` interface stub

## 7. Branch workflow

Use branches like:
- `feature/catalog-api-skeleton`
- `feature/policy-models`
- `feature/subtitle-intel-scan`
- `docs/architecture-cleanup`
- `infra/unraid-runtime-stubs`

## 8. Keep GitHub and runtime separate

Allowed in GitHub Actions:
- lint
- tests
- schema validation
- config validation
- docs checks

Not allowed in GitHub Actions:
- subtitle generation
- media scans against your live library
- translation
- transcodes
- file mutation on runtime media

## 9. First local validations

Run:

```bash
python3 scripts/validate_config.py
```

Then ask Claude Code to add:
- pytest config
- ruff config
- YAML schema tests
- pre-commit config

## 10. First practical milestone

The first real milestone is not a full platform.
It is:
- a tracked media state model
- a lock rule model for manually sourced titles
- a validated policy layout
- a subtitle inventory scanner stub

That gives you a safe foundation before you touch real media.
