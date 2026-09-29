"""CLI: `python -m flooreplay seed` loads fixtures idempotently."""

import sys

from .incident_jobs import run_worker
from .seeding import run_seed


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"seed", "worker"}:
        print("usage: python -m flooreplay seed|worker")
        return 2
    if sys.argv[1] == "worker":
        run_worker()
        return 0
    counts = run_seed()
    print(f"seeded: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
