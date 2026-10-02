#!/usr/bin/env python3
"""Tests that the YTM websocket skips websocket-client's UTF-8 validation.

Regression under test: without wsaccel, websocket-client validates every text
frame's UTF-8 byte by byte in pure Python while holding the GIL. The YTM
Companion pushes its full player state every few seconds while music plays;
on a 512x64 Pi 4 rig that validation took ~16% of the display process's GIL
time and stalled ~8% of scroll frames (0.6% without it), visible as the
scroll pausing and jumping.

Run: <core-venv>/bin/python plugins/ledmatrix-music/test_ytm_skip_utf8_validation.py
"""

import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_DIR))

try:
    import socketio  # noqa: F401
except ImportError:
    print("SKIP: python-socketio not installed (see requirements.txt)")
    sys.exit(2)

import ytm_client  # noqa: E402


def test_websocket_is_opened_without_utf8_validation():
    client = ytm_client.YTMClient()
    options = client.sio.eio.websocket_extra_options
    assert options.get('skip_utf8_validation') is True, options


def main():
    test_websocket_is_opened_without_utf8_validation()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
