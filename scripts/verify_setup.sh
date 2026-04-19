#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"

echo "Package root: ${PACKAGE_ROOT}"
echo "Codex home: ${CODEX_HOME}"

command -v python3 >/dev/null
echo "python3: ok"

command -v git >/dev/null
echo "git: ok"

for skill in obsidian-intelligence-system product-intelligence-factory product-engineering-ops; do
  if [[ -d "${CODEX_HOME}/skills/${skill}" ]]; then
    echo "installed skill: ${skill}"
  else
    echo "missing installed skill: ${skill}" >&2
    exit 1
  fi
done

python3 "${PACKAGE_ROOT}/skills/product-intelligence-factory/scripts/init_product_manifest.py" --help >/dev/null
python3 "${PACKAGE_ROOT}/skills/product-intelligence-factory/scripts/init_intelligence_profile.py" --help >/dev/null
python3 "${PACKAGE_ROOT}/skills/product-intelligence-factory/scripts/validate_product_manifest.py" --help >/dev/null
python3 "${PACKAGE_ROOT}/skills/product-intelligence-factory/scripts/build_source_indices.py" --help >/dev/null
python3 "${PACKAGE_ROOT}/skills/product-intelligence-factory/scripts/rebuild_product_brain.py" --help >/dev/null
python3 "${PACKAGE_ROOT}/skills/product-intelligence-factory/scripts/sanitize_vault_privacy.py" --help >/dev/null
python3 "${PACKAGE_ROOT}/skills/product-engineering-ops/scripts/generate_engineering_readiness.py" --help >/dev/null
python3 "${PACKAGE_ROOT}/skills/obsidian-intelligence-system/scripts/scaffold_vault.py" --help >/dev/null
python3 "${PACKAGE_ROOT}/skills/obsidian-intelligence-system/scripts/audit_vault.py" --help >/dev/null
python3 "${PACKAGE_ROOT}/scripts/second_brain_wizard.py" --help >/dev/null

echo "bundled scripts: ok"
