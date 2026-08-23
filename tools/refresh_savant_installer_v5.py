#!/usr/bin/env python3
"""Compatibility launcher for the current Challenger Savant refresh.

The workflow calls this stable path. The implementation now lives in v7, which
uses four-day Statcast windows, rejects the 25,000-row cap, and safely skips a
valid no-game window before Opening Day.
"""
from refresh_savant_installer_v7 import base

if __name__ == "__main__":
    raise SystemExit(base.main())
