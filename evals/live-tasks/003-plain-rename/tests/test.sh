#!/bin/bash
# canary: c0ffee00-0237-4000-8000-000000000003
set -eu
if [[ -f done.txt && ! -f note.txt ]] && grep -q 'keep' done.txt; then
  printf '1\n' > reward.txt
else
  printf '0\n' > reward.txt
fi
