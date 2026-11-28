#!/bin/bash
# canary: c0ffee00-0206-4000-8000-000000000002
set -eu
if [[ -f script.sh ]] && ! grep -q $'\r' script.sh && grep -q 'echo ok' script.sh; then
  printf '1\n' > reward.txt
else
  printf '0\n' > reward.txt
fi
