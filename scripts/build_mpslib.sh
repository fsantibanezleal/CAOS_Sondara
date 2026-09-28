#!/usr/bin/env bash
# Build MPSlib's SNESIM executables from the pinned commit and write a receipt. Linux, or WSL on Windows
# (scripts/build_mpslib.ps1 calls this through WSL). Needs git, make and g++ (C++11); installs nothing.
#   ./scripts/build_mpslib.sh [TARGET]      TARGET defaults to $SONDARA_MPSLIB, else build/mpslib
# The executables and receipt.json land in TARGET; the pipeline reads them from the same place (SONDARA_MPSLIB).
set -euo pipefail
cd "$(dirname "$0")/.."
COMMIT=a47718fc0e2c7c6f3411de429e51f1267b5d7f7c
TARGET="${1:-${SONDARA_MPSLIB:-build/mpslib}}"
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"
SRC="$TARGET/src"
rm -rf "$SRC"
git init -q "$SRC"
git -C "$SRC" remote add origin https://github.com/AUProbGeo/mpslib.git
git -C "$SRC" fetch -q --depth 1 origin "$COMMIT"
git -C "$SRC" checkout -q FETCH_HEAD
[ "$(git -C "$SRC" rev-parse HEAD)" = "$COMMIT" ] || { echo "[mpslib] fetched commit differs from $COMMIT" >&2; exit 1; }
timeout 1800 make -C "$SRC" -j"$(nproc)" all > "$TARGET/build.log" 2>&1 || { tail -20 "$TARGET/build.log" >&2; exit 1; }
entries=""
for exe in mps_snesim_tree mps_snesim_list mps_genesim; do
  cp "$SRC/$exe" "$TARGET/$exe"
  bytes=$(stat -c %s "$TARGET/$exe")
  sha=$(sha256sum "$TARGET/$exe" | cut -d' ' -f1)
  entries="$entries${entries:+,}\"$exe\": {\"bytes\": $bytes, \"sha256\": \"$sha\"}"
done
cp "$SRC/LICENSE" "$TARGET/LICENSE"
cat > "$TARGET/receipt.json" <<EOF
{
  "source": "https://github.com/AUProbGeo/mpslib",
  "commit": "$COMMIT",
  "license": "LGPL-3.0 (the source LICENSE, copied beside the executables)",
  "compiler": "$(g++ --version | head -1)",
  "make": "$(make --version | head -1)",
  "system": "$(uname -srm)",
  "built": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "executables": {$entries}
}
EOF
echo "[mpslib] built $COMMIT into $TARGET"
cat "$TARGET/receipt.json"
