#!/usr/bin/env python3
"""Reconcile a SpinQ Cloud platform export into the official L1 evidence schema.

The SpinQ Cloud console exports vendor-specific fields (`platform` /
`created_time_utc` / `task_status`) and may report a *requested* `shots` value
that differs from the actual number of returned samples. This script maps the
export onto the official result schema **without inventing any counts**:

- `backend` / `bit_order` / `timestamp` are derived from the export metadata;
- `shots` is set to the actual total of the returned counts; when the export's
  declared shots differs, a warning is printed and the difference is recorded
  in `meta` for the human reviewer;
- the original raw file is never modified.

Human verification is still required before claiming the real-machine score:
confirm `job_id` and the shot count against the SpinQ Cloud console.

Usage:
    python3 starter_kit/evidence/reconcile_evidence.py \
        --input  starter_kit/evidence/files/spinq_gemini_bell.json \
        --output starter_kit/evidence/files/spinq_gemini_bell.official.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def _utc_z(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def reconcile(raw: dict, backend: str) -> dict:
    counts = raw.get("counts")
    if not isinstance(counts, dict) or not counts:
        raise ValueError("export counts must be a non-empty object")
    for key, value in counts.items():
        if not isinstance(key, str) or re.fullmatch(r"[01]+", key) is None:
            raise ValueError("export count keys must be binary strings")
        if type(value) is not int or value < 0:
            raise ValueError("export count values must be non-negative integers")

    counts_total = sum(counts.values())
    declared_shots = raw.get("shots")
    if type(declared_shots) is not int:
        raise ValueError("export shots must be an integer")
    if counts_total != declared_shots:
        print(
            "WARNING: declared shots=%d but returned counts total=%d; "
            "official schema requires counts to sum to shots. "
            "Verify the actual shot count against the platform console before claiming this evidence."
            % (declared_shots, counts_total),
            file=sys.stderr,
        )

    timestamp_raw = raw.get("created_time_utc") or raw.get("start_time_utc") or raw.get("end_time_utc")
    if not isinstance(timestamp_raw, str) or not timestamp_raw.strip():
        raise ValueError("export has no usable UTC timestamp")

    return {
        "backend": backend,
        "job_id": str(raw.get("job_id", "")),
        "shots": counts_total,
        "counts": counts,
        "bit_order": "little",
        "timestamp": _utc_z(timestamp_raw),
        "meta": {
            "is_mock": False,
            "is_hardware": True,
            "evidence_source": "spinq-cloud-export",
            "reconciled": True,
            "declared_shots": declared_shots,
            "counts_total": counts_total,
            "platform": raw.get("platform"),
            "platform_code": raw.get("platform_code"),
            "machine_code": raw.get("machine_code"),
            "machine_name": raw.get("machine_name"),
            "task_name": raw.get("task_name"),
            "task_status": raw.get("task_status"),
            "start_time_utc": raw.get("start_time_utc"),
            "end_time_utc": raw.get("end_time_utc"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile SpinQ Cloud export into official schema")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--backend", default="spinq_cloud_qpu")
    args = parser.parse_args()

    source = Path(args.input)
    destination = Path(args.output)
    raw = json.loads(source.read_text(encoding="utf-8"))
    official = reconcile(raw, args.backend)
    destination.write_text(
        json.dumps(official, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("reconciled evidence written to %s" % destination)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("reconcile failed: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        sys.exit(1)
