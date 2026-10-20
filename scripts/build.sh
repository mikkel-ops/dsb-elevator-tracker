#!/usr/bin/env bash
# Build Lambda zips for arm64 / Python 3.12 without Docker: uv downloads
# manylinux wheels for the target platform directly.
set -euo pipefail
cd "$(dirname "$0")/.."

build() {
  local name=$1; shift
  local dir=build/$name
  rm -rf "$dir" "build/$name.zip"
  mkdir -p "$dir"
  uv pip install --quiet --target "$dir" \
    --python-platform aarch64-manylinux2014 --python-version 3.12 --only-binary=:all: \
    "$@"
  # Packages to ship (boto3 is provided by the Lambda runtime).
  for pkg in scraper api; do
    [[ $name == scraper && $pkg == api ]] && continue
    rsync -a --exclude __pycache__ "$pkg" "$dir/"
  done
  find "$dir" -name '__pycache__' -prune -exec rm -rf {} +
  find "$dir" -exec touch -t 202001010000 {} +
  (cd "$dir" && find . -type f | LC_ALL=C sort | zip -qX "../$name.zip" -@)
  echo "build/$name.zip $(du -h "build/$name.zip" | cut -f1)"
}

build scraper requests beautifulsoup4 pyyaml
build api fastapi mangum beautifulsoup4 pyyaml
