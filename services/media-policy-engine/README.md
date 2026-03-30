# media-policy-engine

Evaluates inspected media facts against policy contracts and returns a list of safe, deterministic actions. No media files are read or mutated here.

## Inputs

A `MediaFacts` document describing:
- media domain (one of 11 defined in `config/media-domains.yaml`)
- detected original language
- video codec, remux flag, HDR flag
- subtitle tracks (language, confidence, type)
- audio tracks (language, type, stereo flag)
- catalog tags (e.g. `locked`, `manual-source`)

## Outputs

A `PolicyEvaluationResult` containing:
- a list of `PolicyAction` items (keep, remove, quarantine, generate, transcode, review)
- `requires_review` aggregate flag
- evaluation notes

## Policy contracts

Rules are loaded from `config/policies/`:
- `subtitles.yaml`
- `audio.yaml`
- `transcode.yaml`

The evaluator defaults to least-destructive action for any ambiguous case.
Locked or manually-sourced items are short-circuited: all mutations are blocked.

## Running locally

```bash
cd services/media-policy-engine
pip install -e ".[dev]"
POLICY_DIR=../../config/policies uvicorn media_policy_engine.main:app --reload --port 8001
```

API docs at `http://localhost:8001/docs`.

## Running tests

```bash
cd services/media-policy-engine
pytest
```

Tests use the real policy YAML files from `config/policies/` — no mocks.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | Health check |
| POST | /evaluate | Evaluate MediaFacts → PolicyEvaluationResult |

## Next steps

- Wire up to `apps/catalog-api` state transitions (state changes after evaluation).
- Add `/evaluate/batch` for multi-file inspection results.
- Integrate with `services/subtitle-intel` output as input facts.
