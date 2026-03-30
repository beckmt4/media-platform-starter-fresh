from __future__ import annotations

from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    ROOT / "config" / "media-domains.yaml",
    ROOT / "config" / "storage-layout.yaml",
    ROOT / "config" / "policies" / "subtitles.yaml",
    ROOT / "config" / "policies" / "audio.yaml",
    ROOT / "config" / "policies" / "transcode.yaml",
    ROOT / "config" / "policies" / "arr-locks.yaml",
]

def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}

def main() -> int:
    missing = [str(p) for p in REQUIRED if not p.exists()]
    if missing:
        print("Missing required config files:")
        for item in missing:
            print(f"- {item}")
        return 1

    for path in REQUIRED:
        data = load_yaml(path)
        if not isinstance(data, dict):
            print(f"Config is not a mapping: {path}")
            return 1

    print("Config validation passed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
