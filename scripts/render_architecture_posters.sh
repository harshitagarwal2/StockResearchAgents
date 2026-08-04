#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chrome_bin="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
source_dir="$repo_root/docs/renders"
output_dir="$repo_root/assets/architecture"

if [[ ! -x "$chrome_bin" ]]; then
  printf 'Chrome executable not found: %s\n' "$chrome_bin" >&2
  exit 1
fi

mkdir -p "$output_dir"

for name in system-overview portable-patterns research-quality; do
  "$chrome_bin" \
    --headless=new \
    --disable-gpu \
    --hide-scrollbars \
    --force-device-scale-factor=1 \
    --window-size=1800,1000 \
    --screenshot="$output_dir/$name.png" \
    "file://$source_dir/$name.html"
done

printf 'Rendered architecture posters with %s\n' "$chrome_bin"
