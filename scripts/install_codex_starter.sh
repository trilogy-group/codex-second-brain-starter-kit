#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
TARGET_DIR="${CODEX_HOME}/skills"

mkdir -p "${TARGET_DIR}"

for skill in obsidian-intelligence-system product-intelligence-factory product-engineering-ops; do
  rm -rf "${TARGET_DIR}/${skill}"
  cp -R "${PACKAGE_ROOT}/skills/${skill}" "${TARGET_DIR}/${skill}"
done

echo "Installed bundled skills to ${TARGET_DIR}"
echo "Next:"
echo "  1. Run ./scripts/verify_setup.sh"
echo "  2. Run ./scripts/bootstrap_test_workspace.sh --help"
