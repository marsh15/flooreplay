"""CLI: `python -m flooreplay seed` loads fixtures idempotently."""

import sys

from .seeding import run_seed


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "seed":
        print("usage: python -m flooreplay seed")
        return 2
    counts = run_seed()
    print(f"seeded: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
