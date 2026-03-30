# How to Use This Starter

## What this starter is

This is a repository scaffold.
It is not a finished application.
It gives you:
- project structure
- Claude Code project instructions
- skill folders
- GitHub workflow placeholders
- policy/config file locations
- docs structure

## What you should do first

1. Put the repo in GitHub.
2. Open it in VS Code.
3. Install the Claude Code extension.
4. Read `CLAUDE.md`.
5. Use Claude Code to implement one small slice at a time.

## How to work with Claude Code in this repo

For every task:
1. open the repo root in VS Code
2. start Claude Code in the workspace
3. tell Claude to read `CLAUDE.md` first
4. point Claude to the exact files involved
5. make one small change set
6. run local checks
7. commit to a feature branch
8. open a PR

## Good first prompts

### Repo understanding

> Read `CLAUDE.md` and `README.md`, then explain this repo structure and tell me the best first implementation slice.

### Build the first API skeleton

> Read `CLAUDE.md`, then build a minimal FastAPI skeleton in `apps/catalog-api` with a health endpoint, Pydantic settings, README updates, and tests.

### Add policy validation

> Read `CLAUDE.md` and the YAML files in `config/policies/`. Add Python validation code and tests so malformed policy files fail CI.

### Start subtitle intelligence

> Read `CLAUDE.md`, `config/media-domains.yaml`, and `config/policies/subtitles.yaml`. Create a `services/subtitle-intel` stub that can inspect a media path and return a structured subtitle inventory JSON payload.

## What not to do first

Do not start with:
- full automation
- real transcode jobs
- live library mutation
- heavy UI work
- complex agent logic

That is how small projects get bloated and break.

## Definition of done for each PR

Each PR should include, when relevant:
- code
- tests
- docs update
- config update
- clear operational note
