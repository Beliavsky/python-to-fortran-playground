#!/usr/bin/env bash
set -euo pipefail
# Pinned GNU development snapshot. Build once in a cached compiler-only layer.
snapshot=17-20261018
archive="gcc-${snapshot}.tar.xz"
checksum=9daddd2a42feb1cf66d33445cc4f17ff1abbdf2a5339eeddca4d95b96d47364e9c5ce95b4d6ba391d26262345add8233440cc1bf374322f61a52eb5140fd8048
build_root=$(mktemp -d /tmp/p2f-gcc17.XXXXXXXX)
trap 'rm -rf -- "$build_root"' EXIT
cd "$build_root"
curl --fail --location --retry 3 --connect-timeout 30 \
    "https://sourceware.org/pub/gcc/snapshots/${snapshot}/${archive}" -o "$archive"
printf '%s  %s\n' "$checksum" "$archive" | sha512sum --check -
tar -xf "$archive"
mkdir build
cd build
"../gcc-${snapshot}/configure" --prefix=/opt/gcc17 --enable-languages=c,fortran \
    --disable-bootstrap --disable-multilib --disable-libsanitizer
make -j4
make install-strip
# Take precedence over the stable base image's 000-local-lib.conf.
printf '%s\n' /opt/gcc17/lib64 /opt/gcc17/lib > /etc/ld.so.conf.d/000-gcc17.conf
ldconfig
printf '%s\n' '#!/bin/sh' 'exec /opt/gcc17/bin/gfortran "$@"' > /usr/local/bin/p2f-gfortran17
chmod 755 /usr/local/bin/p2f-gfortran17
case "$(p2f-gfortran17 -dumpfullversion)" in
    17.*) ;;
    *) echo 'Unexpected GNU development compiler version' >&2; exit 1 ;;
esac
p2f-gfortran17 --version
