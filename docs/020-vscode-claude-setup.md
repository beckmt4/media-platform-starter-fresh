# VS Code + Claude Code Setup

## Workstation setup

1. Install VS Code.
2. Install the Claude Code extension.
3. Install Git.
4. Install Python 3.11+.
5. Clone this repository locally.
6. Open the repo in VS Code.
7. Copy `.claude/settings.local.example.json` to `.claude/settings.local.json`.
8. Adjust local path variables.
9. Open the Claude Code panel in VS Code.
10. Start a session from the repo root.

## Daily workflow

1. pull latest main
2. create a feature branch
3. open a Claude Code session in the repo
4. point Claude to the relevant policy and docs before coding
5. make changes
6. run local validation tasks
7. open PR
8. require review before merge

## Prompt starter

Use this first prompt inside the repo:

> Read `CLAUDE.md`, review the relevant files for this task, identify impacted media classes, then propose the smallest safe change and list the tests and docs that must be updated.
