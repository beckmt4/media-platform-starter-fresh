# Unraid Runtime — CA Apps Deployment

All services run as Docker containers managed through **Unraid Community Applications (CA Apps)**.

## Service port map

| Service | Port | Purpose |
|---|---|---|
| catalog-api | 8000 | Source-of-truth state API |
| media-policy-engine | 8001 | Policy evaluator |
| subtitle-intel | 8002 | Subtitle inspection |
| jav-normalizer | 8003 | JAV title normalization |
| subtitle-worker | 8004 | Whisper transcription jobs |
| transcode-worker | 8005 | ffmpeg/mkvtoolnix jobs |

## First-time setup

### 1 — Build the images on Unraid

SSH into the Unraid server and run from the repo root:

```bash
docker build -t media-platform/catalog-api:latest         apps/catalog-api/
docker build -t media-platform/media-policy-engine:latest  services/media-policy-engine/
docker build -t media-platform/subtitle-intel:latest       services/subtitle-intel/
docker build -t media-platform/jav-normalizer:latest       services/jav-normalizer/
docker build -t media-platform/subtitle-worker:latest      workers/subtitle-worker/
docker build -t media-platform/transcode-worker:latest     workers/transcode-worker/
```

Rebuild any image after code changes. The Dockerfiles pin to `python:3.11-slim` and install only declared runtime deps.

### 2 — Copy shared config to appdata

```bash
mkdir -p /mnt/user/appdata/media-platform/config
cp -r config/policies /mnt/user/appdata/media-platform/config/
cp config/media-domains.yaml /mnt/user/appdata/media-platform/config/
```

Re-copy whenever policy files change. `media-policy-engine` mounts this path read-only.

### 3 — Install CA Apps templates

Copy the XML files to the Unraid user templates directory:

```bash
cp infra/unraid/templates/*.xml /boot/config/plugins/dockerMan/templates-user/
```

The templates will appear in **Apps → My Templates** in the Unraid UI. Click each one to configure and deploy.

### 4 — Deploy order

Start containers in this order (each depends on the previous):

1. `catalog-api` — must be up first; all others report state to it
2. `media-policy-engine`
3. `subtitle-intel`
4. `jav-normalizer`
5. `subtitle-worker`
6. `transcode-worker`

## GPU acceleration

### NVIDIA (NVENC / CUDA)

In the CA Apps template for `subtitle-worker` or `transcode-worker`, add to **Extra Parameters**:

```
--gpus all
```

Requires the Nvidia Driver plugin installed on Unraid.

### Intel QuickSync

Add to **Extra Parameters** on `transcode-worker`:

```
--device /dev/dri
```

## Whisper model cache

`subtitle-worker` caches downloaded models at `/mnt/user/appdata/media-platform/whisper-models`.
This path persists across container restarts. The first job run will download the configured model
(default: `large-v3`, ~3 GB). Subsequent runs load from cache.

## Shared media paths

The containers use the same mount points as `config/storage-layout.yaml`:

| Host path | Container path | Used by |
|---|---|---|
| `/mnt/user/Domestic_TV` | `/mnt/dtv` | subtitle-intel, subtitle-worker, transcode-worker |
| `/mnt/user/International_TV` | `/mnt/itv` | subtitle-intel, subtitle-worker, transcode-worker, jav-normalizer |
| `/mnt/user/appdata/media-platform/media-work` | `/mnt/container/media-work` | all workers |

Adjust host paths to match your Unraid share names.

## Updating a service

```bash
# Rebuild the image
docker build -t media-platform/catalog-api:latest apps/catalog-api/

# Restart the container from the Unraid Docker tab
# (Stop → Start, or use the restart button)
```

No data is stored inside containers — all state is in `/mnt/user/appdata/`.
