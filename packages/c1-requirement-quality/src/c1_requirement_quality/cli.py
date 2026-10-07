"""c1 CLI. Exit code 0 = success (docs/INTEGRATION_RULES.md section 4).

Usage: c1 run --srs <file> --out runs/<RUN-ID>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="c1")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="refine an SRS into c1/validated_requirements.json")
    run.add_argument("--srs", required=True, help="path to the SRS file")
    run.add_argument("--out", required=True, help="run folder, e.g. runs/RUN-1")
    return parser


def run(srs: Path, out: Path) -> None:
    """Skeleton only: replace with the real pipeline (see README for task order)."""
    (out / "c1").mkdir(parents=True, exist_ok=True)
    print(f"[c1] skeleton run srs={srs} out={out}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(Path(args.srs), Path(args.out))
    except Exception as err:  # noqa: BLE001 - CLI boundary
        print(f"[c1] {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
