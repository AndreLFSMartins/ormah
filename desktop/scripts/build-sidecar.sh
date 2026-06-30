#!/usr/bin/env bash
# Downloads the uv binary for the current (or specified) Rust target triple
# and places it in desktop/src-tauri/binaries/ where Tauri's externalBin picks it up.
#
# Usage:
#   ./desktop/scripts/build-sidecar.sh                          # auto-detects target
#   ./desktop/scripts/build-sidecar.sh aarch64-apple-darwin     # explicit target
#
# Called automatically by CI before `cargo tauri build`.
# Run manually once before `cargo check` / `cargo tauri dev` on a dev machine.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARIES_DIR="$SCRIPT_DIR/../src-tauri/binaries"
mkdir -p "$BINARIES_DIR"

# Determine target triple
if [[ $# -ge 1 ]]; then
    TARGET="$1"
else
    TARGET="$(rustc -vV 2>/dev/null | awk '/host:/ {print $2}')"
fi

if [[ -z "$TARGET" ]]; then
    echo "error: could not determine Rust target triple (is rustc installed?)" >&2
    exit 1
fi

# Map Rust triple → uv release asset name
case "$TARGET" in
    aarch64-apple-darwin)   UV_ASSET="uv-aarch64-apple-darwin.tar.gz" ;;
    x86_64-apple-darwin)    UV_ASSET="uv-x86_64-apple-darwin.tar.gz" ;;
    x86_64-unknown-linux-gnu) UV_ASSET="uv-x86_64-unknown-linux-gnu.tar.gz" ;;
    aarch64-unknown-linux-gnu) UV_ASSET="uv-aarch64-unknown-linux-gnu.tar.gz" ;;
    *)
        echo "error: unsupported target '$TARGET'" >&2
        exit 1
        ;;
esac

DEST="$BINARIES_DIR/uv-$TARGET"

if [[ -f "$DEST" ]]; then
    echo "uv sidecar already present: $DEST"
    exit 0
fi

URL="https://github.com/astral-sh/uv/releases/latest/download/$UV_ASSET"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Downloading $UV_ASSET for $TARGET..."
curl -fsSL "$URL" | tar -xz -C "$TMP"

cp "$TMP/uv-$TARGET/uv" "$DEST"
chmod +x "$DEST"
echo "Installed uv sidecar → $DEST"
