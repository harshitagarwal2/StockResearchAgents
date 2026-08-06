#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="$repo_root/docs/diagrams"
output_dir="$repo_root/assets/architecture"
renderer="@mermaid-js/mermaid-cli@11.12.0"

mkdir -p "$output_dir"

for name in \
  system-context \
  portable-components \
  completed-publication \
  research-quality-lineage \
  solid-ports-adapters \
  source-to-dossier \
  company-analytics-lifecycle; do
  npx --yes "$renderer" \
    --input "$source_dir/$name.mmd" \
    --output "$output_dir/$name.svg" \
    --puppeteerConfigFile "$source_dir/puppeteer-config.json" \
    --backgroundColor white \
    --quiet

  npx --yes "$renderer" \
    --input "$source_dir/$name.mmd" \
    --output "$output_dir/$name.png" \
    --puppeteerConfigFile "$source_dir/puppeteer-config.json" \
    --backgroundColor white \
    --scale 2 \
    --quiet
done

python3 "$repo_root/scripts/architecture_render_manifest.py" \
  --root "$repo_root" \
  --renderer "$renderer" \
  --write

printf 'Rendered architecture SVG and PNG pairs with %s\n' "$renderer"
