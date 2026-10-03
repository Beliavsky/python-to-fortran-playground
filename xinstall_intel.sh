#!/bin/bash
# Build-time installation only. Submitted sandboxes remain network-blocked.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
# Intel's current chain may need roots newer than the base distribution bundle.
# Use a pinned Mozilla CA bundle for both curl and APT; never disable TLS checks.
export CURL_CA_BUNDLE="$(python -c 'import certifi; print(certifi.where())')"
curl --fail --show-error --silent --location \
  https://apt.repos.intel.com/intel-gpg-keys/GPG-PUB-KEY-INTEL-SW-PRODUCTS.PUB \
  | gpg --dearmor -o /usr/share/keyrings/oneapi-archive-keyring.gpg
printf '%s\n' 'deb [signed-by=/usr/share/keyrings/oneapi-archive-keyring.gpg] https://apt.repos.intel.com/oneapi all main' > /etc/apt/sources.list.d/oneapi.list
apt-get -o Acquire::https::CaInfo="$CURL_CA_BUNDLE" update
# Pin the compiler package rather than pulling a moving compiler release.
apt-get -o Acquire::https::CaInfo="$CURL_CA_BUNDLE" install -y --no-install-recommends intel-oneapi-compiler-fortran-2025.3=2025.3.3-30
cat > /usr/local/bin/p2f-ifx <<'WRAPPER'
#!/bin/bash
# Intel environment is initialized inside the unprivileged job, not via a shell
# command supplied by a visitor. Flags arrive as normal argv elements.
source /opt/intel/oneapi/setvars.sh > /dev/null 2>&1
exec ifx "$@"
WRAPPER
chmod 755 /usr/local/bin/p2f-ifx
/usr/local/bin/p2f-ifx --version
# setvars runs in the compiler subprocess, not the subsequent executable.
# Register Intel's redistributable libraries for standalone program execution.
find /opt/intel/oneapi/compiler \( -name 'libimf.so*' -o -name 'libsvml.so*' \
  -o -name 'libintlc.so*' -o -name 'libiomp5.so*' \) -printf '%h\n' \
  | sort -u > /etc/ld.so.conf.d/p2f-intel.conf
test -s /etc/ld.so.conf.d/p2f-intel.conf
ldconfig
