#!/usr/bin/env python3
"""
Lint Ratchet Mechanism for Meridian Trading Platform.

Enforces a hard ceiling on Flake8 technical debt (violations <= 944).
Ensures that legacy debt cannot grow and that new code adheres to standards.
Exits with code 1 if total violations exceed the ceiling.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_CEILING = 944
EXCLUDED_DIRS = ".venv,__pycache__,frontend,infra,.agents"


def count_flake8_violations(
    target_dir: str = ".",
    max_complexity: int = 15,
    max_line_length: int = 127,
    exclude: str = EXCLUDED_DIRS,
) -> tuple[int, str]:
    """Run Flake8 and return total violation count and output."""
    cmd = [
        sys.executable,
        "-m",
        "flake8",
        target_dir,
        "--count",
        f"--max-complexity={max_complexity}",
        f"--max-line-length={max_line_length}",
        "--statistics",
        f"--exclude={exclude}",
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    combined_output = result.stdout
    if result.stderr:
        combined_output += ("\n" if combined_output else "") + result.stderr

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        if result.returncode == 0:
            return 0, combined_output
        raise RuntimeError(f"Flake8 execution failed unexpectedly:\n{combined_output}")

    last_line = lines[-1]
    try:
        count = int(last_line)
    except ValueError:
        raise ValueError(
            f"Could not parse violation count from last line: '{last_line}'\n"
            f"Output:\n{combined_output}"
        )

    return count, combined_output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enforce Flake8 lint debt ratchet ceiling."
    )
    parser.add_argument(
        "--ceiling",
        type=int,
        default=int(os.environ.get("FLAKE8_RATCHET_CEILING", DEFAULT_CEILING)),
        help=f"Maximum allowed Flake8 violations (default: {DEFAULT_CEILING})",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=".",
        help="Target directory to inspect (default: .)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress violation details and print only the summary",
    )

    args = parser.parse_args()

    # Resolve repo root directory if target is relative
    target_path = Path(args.target).resolve()
    print("=== FLAKE8 LINT RATCHET INSPECTION ===")
    print(f"Target: {target_path}")
    print(f"Ceiling: {args.ceiling}")

    try:
        count, output = count_flake8_violations(target_dir=str(args.target))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not args.quiet and output:
        print(output)

    print("=" * 50)
    print(f"Current Flake8 violations: {count} (ceiling: {args.ceiling})")

    if count > args.ceiling:
        excess = count - args.ceiling
        print(
            f"FAILED: Flake8 violations ({count}) exceed ratchet ceiling ({args.ceiling}) "
            f"by +{excess}! Technical debt increase is strictly rejected.",
            file=sys.stderr,
        )
        return 1

    print(
        f"PASSED: Flake8 violations ({count}) within allowed ratchet ceiling ({args.ceiling})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
