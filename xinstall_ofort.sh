#!/bin/bash
# Trusted image construction only; submitted jobs have no network access.
set -euo pipefail
mkdir -p /opt/ofort-source
cd /opt/ofort-source
git init
git remote add origin https://github.com/beliavsky/ofort.git
git fetch --depth=1 origin 77301d0ca14680b38121fbc87b8dd2292f44bea9
git checkout --detach FETCH_HEAD
# This revision's Makefile omits the generated version header and LAPACK bridge.
# Build the unchanged upstream sources explicitly, including that bridge.
python scripts/write_build_version.py
gcc -O2 -Iinclude src/main.c src/ofort.c src/ofort_values.c src/ofort_stats.c \
    src/ofort_fixed_form.c src/ofort_lapack.c -lm -ldl -o ofort.exe
install -m755 ofort.exe /usr/local/bin/ofort
ofort --version
