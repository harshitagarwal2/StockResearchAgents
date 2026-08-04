#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="$repo_root/docs/diagrams"
output_dir="$repo_root/assets/architecture"
renderer="@mermaid-js/mermaid-cli@11.12.0"

mkdir -p "$output_dir"

for name in system-context portable-components completed-publication research-quality-lineage; do
  npx --yes "$renderer" \
    --input "$source_dir/$name.mmd" \
    --output "$output_dir/$name.svg" \
    --puppeteerConfigFile "$source_dir/puppeteer-config.json" \
    --backgroundColor transparent \
    --quiet
done

printf 'Rendered architecture diagrams with %s\n' "$renderer"
