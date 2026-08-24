#!/usr/bin/env python3
"""Validate one normalized LoomQ real-hardware evidence JSON file."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COMPETITION_START = datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc)
COMPETITION_DEADLINE = datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def validate_result(data: Any, *, check_window: bool = True) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["result must be a JSON object"]

    for field in ("backend", "job_id", "shots", "counts", "bit_order", "timestamp"):
        if field not in data:
            errors.append("missing field: %s" % field)
    if errors:
        return errors

    for field in ("backend", "job_id"):
        if not isinstance(data[field], str) or not data[field].strip():
            errors.append("%s must be a non-empty string" % field)

    shots = data["shots"]
    if type(shots) is not int or shots <= 0:
        errors.append("shots must be a positive integer")

    counts = data["counts"]
    if not isinstance(counts, dict) or not counts:
        errors.append("counts must be a non-empty object")
    else:
        for key, value in counts.items():
            if not isinstance(key, str) or not key or set(key) - {"0", "1"}:
                errors.append("counts keys must be non-empty binary strings")
            if type(value) is not int or value < 0:
                errors.append("counts values must be non-negative integers")
        if type(shots) is int and sum(counts.values()) != shots:
            errors.append("counts total must equal shots exactly")

    if data["bit_order"] != "little":
        errors.append('bit_order must be "little"')

    timestamp = _parse_timestamp(data["timestamp"])
    if timestamp is None:
        errors.append("timestamp must be an ISO-8601 value with timezone")
    elif check_window and not (COMPETITION_START <= timestamp <= COMPETITION_DEADLINE):
        errors.append("timestamp is outside the competition window")

    meta = data.get("meta")
    if not isinstance(meta, dict):
        errors.append("meta must be an object")
    else:
        if meta.get("is_hardware") is not True:
            errors.append("meta.is_hardware must be true")
        if meta.get("is_mock") is True:
            errors.append("mock results cannot be submitted as hardware evidence")
        device_id = meta.get("platform_device_id")
        if not isinstance(device_id, str) or not device_id.strip():
            errors.append("meta.platform_device_id must be recorded")

    if isinstance(data.get("job_id"), str) and data["job_id"].startswith("local-"):
        errors.append("local job IDs cannot be hardware evidence")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument(
        "--allow-out-of-window",
        action="store_true",
        help="validate schema without enforcing the contest time window",
    )
    args = parser.parse_args()
    try:
        data = json.loads(args.result.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print("INVALID: %s" % exc)
        return 1
    errors = validate_result(data, check_window=not args.allow_out_of_window)
    if errors:
        print("INVALID")
        for error in errors:
            print("- %s" % error)
        return 1
    print("VALID: normalized hardware evidence schema and time window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
