#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

NAME=""
SLUG=""
MODE="hybrid"
VAULT=""
WORKSPACE=""
MANIFEST=""
ENTITY_SINGULAR="entity"
ENTITY_PLURAL="entities"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --slug) SLUG="$2"; shift 2 ;;
    --mode) MODE="$2"; shift 2 ;;
    --vault) VAULT="$2"; shift 2 ;;
    --workspace) WORKSPACE="$2"; shift 2 ;;
    --manifest) MANIFEST="$2"; shift 2 ;;
    --entity-singular) ENTITY_SINGULAR="$2"; shift 2 ;;
    --entity-plural) ENTITY_PLURAL="$2"; shift 2 ;;
    --help|-h)
      cat <<'EOF'
Usage:
  ./scripts/bootstrap_test_workspace.sh \
    --name "Product Name" \
    --slug "product-slug" \
    --mode hybrid \
    --vault "/absolute/path/to/vault" \
    --workspace "/absolute/path/to/workspace"

Optional:
  --manifest "/absolute/path/to/manifest.yaml"
  --entity-singular service
  --entity-plural services
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${NAME}" || -z "${SLUG}" || -z "${VAULT}" || -z "${WORKSPACE}" ]]; then
  echo "Missing required arguments. Use --help for usage." >&2
  exit 1
fi

mkdir -p "${WORKSPACE}/manifests" "${WORKSPACE}/reports" "${WORKSPACE}/_source_corpus/${SLUG}" "${WORKSPACE}/_repos" "${WORKSPACE}/_repo_mirrors" "${WORKSPACE}/_source_extract"

if [[ -z "${MANIFEST}" ]]; then
  MANIFEST="${WORKSPACE}/manifests/${SLUG}.yaml"
fi

python3 "${PACKAGE_ROOT}/skills/product-intelligence-factory/scripts/init_product_manifest.py" \
  --output "${MANIFEST}" \
  --name "${NAME}" \
  --slug "${SLUG}" \
  --mode "${MODE}" \
  --vault "${VAULT}" \
  --workspace "${WORKSPACE}"

python3 "${PACKAGE_ROOT}/skills/obsidian-intelligence-system/scripts/scaffold_vault.py" \
  --vault "${VAULT}" \
  --project "${NAME}" \
  --mode "${MODE}" \
  --entity-singular "${ENTITY_SINGULAR}" \
  --entity-plural "${ENTITY_PLURAL}" \
  --overwrite

python3 "${PACKAGE_ROOT}/skills/product-intelligence-factory/scripts/validate_product_manifest.py" \
  --manifest "${MANIFEST}" \
  --check-paths

python3 "${PACKAGE_ROOT}/skills/obsidian-intelligence-system/scripts/audit_vault.py" \
  --vault "${VAULT}" \
  --write "${VAULT}/80 Assets/vault-audit.md"

python3 "${PACKAGE_ROOT}/skills/product-engineering-ops/scripts/generate_engineering_readiness.py" \
  --manifest "${MANIFEST}" \
  --write "${WORKSPACE}/reports/${SLUG}-engineering-readiness.md"

cat <<EOF
Bootstrap complete.

Created:
- Manifest: ${MANIFEST}
- Vault: ${VAULT}
- Audit: ${VAULT}/80 Assets/vault-audit.md
- Readiness report: ${WORKSPACE}/reports/${SLUG}-engineering-readiness.md

Next:
1. Replace the sample repository entry in the manifest.
2. Add real source files to ${WORKSPACE}/_source_corpus/${SLUG}
3. Use the prompts in ${PACKAGE_ROOT}/prompts
EOF
