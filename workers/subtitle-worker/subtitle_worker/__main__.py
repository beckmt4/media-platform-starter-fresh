"""CLI entry point for subtitle-worker.

Usage:
  python -m subtitle_worker status
  python -m subtitle_worker run <job.json>
"""
from __future__ import annotations

import json
import sys

from .models import SubtitleJob
from .worker import SubtitleWorker, status


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if not args or args[0] == "status":
        info = status()
        print(json.dumps(info, indent=2))
        return 0 if info["status"] == "ready" else 1

    if args[0] == "run":
        if len(args) < 2:
            print("usage: python -m subtitle_worker run <job.json>", file=sys.stderr)
            return 2
        try:
            job_data = json.loads(args[1]) if args[1].startswith("{") else \
                json.loads(open(args[1]).read())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"error reading job: {exc}", file=sys.stderr)
            return 2

        job = SubtitleJob.model_validate(job_data)
        result = SubtitleWorker().run(job)
        print(json.dumps(result.model_dump(), indent=2, default=str))
        return 0 if result.status.value in ("complete", "skipped") else 1

    print(f"unknown command: {args[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
