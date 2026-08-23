#!/usr/bin/env python3
"""Compatibility launcher for the current Challenger Savant refresh.

The workflow still calls this stable path. The implementation now lives in v6,
which uses 4-day Statcast windows so batter-vs-hand detail requests stay below
Baseball Savant's 25,000-row CSV cap.
"""
from refresh_savant_installer_v6 import base

if __name__ == "__main__":
    raise SystemExit(base.main())
