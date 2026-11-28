#!/bin/bash
# canary: c0ffee00-0206-4000-8000-000000000002
set -eu
python3 -c 'from pathlib import Path; p = Path("script.sh"); p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))'
