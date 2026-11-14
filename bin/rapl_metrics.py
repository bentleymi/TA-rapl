#!/usr/bin/env python3
"""Emit flat numeric metrics (one JSON event per cycle) for analytics."""
import sys

from rapl_common import discover, emit, metrics_payload


def main():
    try:
        data = discover()
    except Exception:
        data = {"status": "absent", "powercap": {}, "power_chips": {}}
    emit(metrics_payload(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
