#!/usr/bin/env python3
"""Check the portable LoomQ runtime and optionally run the public smoke test."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REQUIRED_FILES = (
    "adapter.py",
    "evaluator.py",
    "qasm_parser.py",
    "simulator.py",
    "transpiler.py",
    "submission.yaml",
    "backend_capabilities.json",
    "l2_policy.json",
)
OPTIONAL_SDKS = ("spinqit", "pyqpanda", "pyqpanda3", "braket")


def check_runtime() -> list[str]:
    errors: list[str] = []
    if sys.version_info < (3, 10):
        errors.append("Python 3.10 or newer is required")
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            errors.append("missing required file: %s" % relative)
    for relative in ("backend_capabilities.json", "l2_policy.json"):
        try:
            json.loads((ROOT / relative).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append("invalid %s: %s" % (relative, exc))
    try:
        from adapter import SUPPORTED_TARGETS  # type: ignore

        if tuple(SUPPORTED_TARGETS) != ("spinq", "originq", "braket"):
            errors.append("adapter target contract is incomplete")
    except Exception as exc:  # noqa: BLE001 - diagnostic script must report clearly
        errors.append("adapter import failed: %s" % exc)
    try:
        with tempfile.NamedTemporaryFile(prefix="loomq-check-", delete=True) as handle:
            handle.write(b"ok")
            handle.flush()
    except OSError as exc:
        errors.append("temporary-file check failed: %s" % exc)
    return errors


def run_public_smoke() -> int:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluator.py"),
            "--level",
            "l1",
            "--target",
            "spinq,originq,braket",
        ],
        cwd=ROOT,
        check=False,
    )
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-public",
        action="store_true",
        help="also run the no-key L1 smoke test for all three targets",
    )
    args = parser.parse_args()
    errors = check_runtime()
    if errors:
        print("ENVIRONMENT INVALID")
        for error in errors:
            print("- %s" % error)
        return 1

    print("ENVIRONMENT OK: Python %s" % platform_version())
    for package in OPTIONAL_SDKS:
        status = "installed" if importlib.util.find_spec(package) else "absent (internal fallback is supported)"
        print("SDK %s: %s" % (package, status))
    print("L2 credentials: %s" % ("configured" if all(os.environ.get(name) for name in (
        "LOOMQ_LLM_BASE_URL", "LOOMQ_LLM_API_KEY", "LOOMQ_LLM_MODEL"
    )) else "not configured; L2 is intentionally skipped"))
    if args.run_public:
        return run_public_smoke()
    return 0


def platform_version() -> str:
    return ".".join(str(part) for part in sys.version_info[:3])


if __name__ == "__main__":
    raise SystemExit(main())
