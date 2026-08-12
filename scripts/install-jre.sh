#!/usr/bin/env bash
# Put a Java runtime next to the app so binary .mpp files import on the server.
#
# WHY THIS EXISTS. MPXJ is the only production-grade reader for Microsoft
# Project's binary format, and it is a Java library — there is no pure-Python
# equivalent, and the .mpp format is proprietary enough that there won't be.
# Render's native Python runtime has no JVM and no way to apt-get one, so the
# runtime is fetched here at build time and lives in the project directory,
# which is the same filesystem the app runs from.
#
# WHY IT NEVER FAILS THE BUILD. .mpp import is a convenience: MSPDI XML is the
# richer path and a printed PDF now imports too, so an app that deploys without
# Java is fully usable and merely says "export as XML instead". An app that
# fails to deploy is not usable at all. Every failure here is therefore
# swallowed, and `schedule.mpp_available()` reports the truth at runtime.
#
# Local development needs nothing from this file: install a JRE however you
# normally would (Temurin, `winget install EclipseAdoptium.Temurin.17.JRE`)
# and JPype finds it on its own.
set -uo pipefail

TARGET="${JAVA_HOME:-$(pwd)/.jre}"
# Adoptium's redirect endpoint rather than a pinned asset URL: a pinned URL
# breaks silently when that release is superseded, and a wrong URL here would
# cost a deploy. Java 17 is MPXJ's floor and is LTS until 2029.
URL="https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jre/hotspot/normal/eclipse"

if [ -x "$TARGET/bin/java" ]; then
  echo "[jre] already present at $TARGET"
  exit 0
fi

echo "[jre] fetching a Temurin 17 JRE for .mpp import…"
mkdir -p "$TARGET" || { echo "[jre] could not create $TARGET; skipping"; exit 0; }

if ! curl -fsSL --retry 3 --max-time 300 "$URL" -o /tmp/jre.tar.gz; then
  echo "[jre] download failed — .mpp import will be unavailable, everything else is fine"
  exit 0
fi

# --strip-components=1: the tarball has a versioned top-level directory, and
# pinning JAVA_HOME to a version would break on the next release.
if ! tar -xzf /tmp/jre.tar.gz -C "$TARGET" --strip-components=1; then
  echo "[jre] extract failed — .mpp import will be unavailable"
  rm -f /tmp/jre.tar.gz
  exit 0
fi
rm -f /tmp/jre.tar.gz

if [ -x "$TARGET/bin/java" ]; then
  echo "[jre] ready: $("$TARGET/bin/java" -version 2>&1 | head -1)"
else
  echo "[jre] no java binary after extract — .mpp import will be unavailable"
fi
exit 0
