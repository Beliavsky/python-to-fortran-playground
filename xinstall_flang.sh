#!/bin/bash
# Build-time only: install LLVM Flang, not the unrelated classic Flang project.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export CURL_CA_BUNDLE="$(python -c 'import certifi; print(certifi.where())')"
source /etc/os-release
if [[ "$VERSION_CODENAME" != bookworm ]]; then
  echo 'The pinned LLVM Flang package requires Debian bookworm.' >&2
  exit 1
fi
curl --fail --show-error --silent --location https://apt.llvm.org/llvm-snapshot.gpg.key \
  | gpg --dearmor -o /usr/share/keyrings/p2f-llvm.gpg
printf '%s\n' 'deb [signed-by=/usr/share/keyrings/p2f-llvm.gpg] https://apt.llvm.org/bookworm/ llvm-toolchain-bookworm-23 main' > /etc/apt/sources.list.d/p2f-llvm.list
apt-get -o Acquire::https::CaInfo="$CURL_CA_BUNDLE" update
apt-get -o Acquire::https::CaInfo="$CURL_CA_BUNDLE" install -y --no-install-recommends \
  'flang-23=1:23.1.5~++20261020014245+93acfd24c599-1~exp1~20261020134308.90' \
  'clang-23=1:23.1.5~++20261020014245+93acfd24c599-1~exp1~20261020134308.90'
flang-23 --version | grep -F '23.1.5'
