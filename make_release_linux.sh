#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="$ROOT_DIR/release"
DIST_BIN="$ROOT_DIR/dist/tello_square_mission_linux"

"$ROOT_DIR/build_linux.sh"

mkdir -p "$RELEASE_DIR"
cp "$DIST_BIN" "$RELEASE_DIR/tello_square_mission"

cat > "$RELEASE_DIR/README.txt" << 'EOF'
Tello Square Mission (Linux)

Run:
  ./tello_square_mission

Options:
  --ssid TELLO-XXXXXX
  --side-cm 200

This program auto-connects to TELLO Wi-Fi and runs:
  takeoff -> 200x200 square perimeter -> land
EOF

chmod +x "$RELEASE_DIR/tello_square_mission"

echo "Release ready in: $RELEASE_DIR"
