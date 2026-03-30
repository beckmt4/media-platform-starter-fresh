# n8n Workflows

Only keep orchestration here when the flow is simple, visible, and review-friendly.

Good fit:
- intake notifications
- approval routing
- simple API chaining
- report delivery

Bad fit:
- large stateful media mutation logic
- complex retry trees
- long-running job coordination

## Workflows

### [intake-policy-dispatch.json](intake-policy-dispatch.json)

**Trigger**: `POST /webhook/arr-import` (Sonarr/Radarr on-import webhook)

**Flow**:
1. Normalize arr webhook payload → register item in catalog-api (`inbox`)
2. Scan media via subtitle-intel (`POST /scan`) → get MediaFacts
3. Evaluate policy via media-policy-engine (`POST /evaluate`)
4. **Review gate**: if `requires_review=true` → create review-queue entry, set state `review`, respond 202
5. **Dispatch**: extract `generate_english_subtitles` and `flag_for_transcode` actions, submit jobs to subtitle-worker and transcode-worker, set state `active`, respond 202

**Prerequisites before activating**:
- Set n8n Variables: `CATALOG_API_URL`, `POLICY_ENGINE_URL`, `SUBTITLE_INTEL_URL`, `SUBTITLE_WORKER_URL`, `TRANSCODE_WORKER_URL`
- subtitle-intel must expose `POST /scan` returning a `MediaFacts`-compatible body
- Configure per-node retry count and backoff after import (target: 2 attempts, 1 s)
- Set workflow max concurrency to 1 in Settings
- Wire an n8n error workflow to PATCH item state → `error` on unhandled failure
