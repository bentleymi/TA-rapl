#!/usr/bin/env python3
"""Emit one JSON event per cycle with powercap RAPL domains and hwmon power chips."""
import sys

from rapl_common import discover, emit


def main():
    try:
        data = discover()
    except Exception:
        data = None
    if data is None or data.get("status") != "ok":
        data = {"status": "absent", "powercap": {}, "power_chips": {}}
    emit(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
