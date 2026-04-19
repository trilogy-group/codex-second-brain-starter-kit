#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SCRIPT = PACKAGE_ROOT / "scripts" / "bootstrap_test_workspace.sh"
VALIDATE_MANIFEST = (
    PACKAGE_ROOT / "skills" / "product-intelligence-factory" / "scripts" / "validate_product_manifest.py"
)
AUDIT_VAULT = PACKAGE_ROOT / "skills" / "obsidian-intelligence-system" / "scripts" / "audit_vault.py"
GENERATE_READINESS = (
    PACKAGE_ROOT / "skills" / "product-engineering-ops" / "scripts" / "generate_engineering_readiness.py"
)
REGISTRY_NAME = "second-brains.yaml"


@dataclass
class PortfolioPaths:
    root: Path
    registry: Path
    workspaces_root: Path
    manifests_root: Path
    vaults_root: Path


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def prompt(text: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    if value:
        return value
    if default is not None:
        return default
    return ""


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping at {path}")
    return data


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False))


def portfolio_paths(root: Path) -> PortfolioPaths:
    root = root.expanduser().resolve()
    return PortfolioPaths(
        root=root,
        registry=root / REGISTRY_NAME,
        workspaces_root=root / "workspaces",
        manifests_root=root / "manifests",
        vaults_root=root / "vaults",
    )


def ensure_registry_exists(root: Path) -> dict[str, Any]:
    paths = portfolio_paths(root)
    if not paths.registry.exists():
        raise SystemExit(f"Portfolio registry not found: {paths.registry}")
    return load_yaml(paths.registry)


def init_portfolio(
    *,
    root: Path,
    name: str,
    obsidian_root: Path | None,
    default_mode: str,
) -> Path:
    paths = portfolio_paths(root)
    if paths.registry.exists():
        raise SystemExit(f"Portfolio already exists: {paths.registry}")

    vaults_root = obsidian_root.expanduser().resolve() if obsidian_root else paths.vaults_root

    paths.root.mkdir(parents=True, exist_ok=True)
    paths.workspaces_root.mkdir(parents=True, exist_ok=True)
    paths.manifests_root.mkdir(parents=True, exist_ok=True)
    vaults_root.mkdir(parents=True, exist_ok=True)

    registry = {
        "version": 1,
        "portfolio": {
            "name": name,
            "root_path": str(paths.root),
            "registry_path": str(paths.registry),
            "workspaces_root": str(paths.workspaces_root),
            "manifests_root": str(paths.manifests_root),
            "vaults_root": str(vaults_root),
            "default_mode": default_mode,
            "created_at": now_iso(),
        },
        "brains": [],
    }
    write_yaml(paths.registry, registry)
    return paths.registry


def brain_defaults(registry: dict[str, Any], slug: str, name: str, vault_path: Path | None) -> tuple[Path, Path]:
    portfolio = registry["portfolio"]
    workspace = Path(str(portfolio["workspaces_root"])).expanduser().resolve() / slug
    if vault_path:
        vault = vault_path.expanduser().resolve()
    else:
        vault = Path(str(portfolio["vaults_root"])).expanduser().resolve() / name
    return workspace, vault


def ensure_unique_slug(registry: dict[str, Any], slug: str) -> None:
    brains = registry.get("brains") or []
    if any(brain.get("slug") == slug for brain in brains if isinstance(brain, dict)):
        raise SystemExit(f"A second brain with slug '{slug}' already exists.")


def add_brain(
    *,
    portfolio_root: Path,
    name: str,
    slug: str,
    mode: str,
    vault_path: Path | None,
    entity_singular: str,
    entity_plural: str,
) -> dict[str, Any]:
    registry = ensure_registry_exists(portfolio_root)
    ensure_unique_slug(registry, slug)

    workspace, vault = brain_defaults(registry, slug, name, vault_path)
    manifest_path = Path(str(registry["portfolio"]["manifests_root"])).expanduser().resolve() / f"{slug}.yaml"
    audit_path = vault / "80 Assets" / "vault-audit.md"
    readiness_path = workspace / "reports" / f"{slug}-engineering-readiness.md"

    run(
        [
            str(BOOTSTRAP_SCRIPT),
            "--name",
            name,
            "--slug",
            slug,
            "--mode",
            mode,
            "--vault",
            str(vault),
            "--workspace",
            str(workspace),
            "--entity-singular",
            entity_singular,
            "--entity-plural",
            entity_plural,
            "--manifest",
            str(manifest_path),
        ]
    )

    brain = {
        "name": name,
        "slug": slug,
        "mode": mode,
        "workspace_path": str(workspace),
        "vault_path": str(vault),
        "manifest_path": str(manifest_path),
        "audit_path": str(audit_path),
        "readiness_report_path": str(readiness_path),
        "entity_singular": entity_singular,
        "entity_plural": entity_plural,
        "status": "bootstrapped",
        "created_at": now_iso(),
    }
    registry.setdefault("brains", []).append(brain)
    write_yaml(portfolio_paths(portfolio_root).registry, registry)
    return brain


def list_brains(portfolio_root: Path) -> int:
    registry = ensure_registry_exists(portfolio_root)
    brains = registry.get("brains") or []
    if not brains:
        print("No second brains registered yet.")
        return 0

    print(f"Portfolio: {registry['portfolio']['name']}")
    print("")
    for brain in brains:
        print(f"- {brain['name']} ({brain['slug']})")
        print(f"  mode: {brain['mode']}")
        print(f"  workspace: {brain['workspace_path']}")
        print(f"  vault: {brain['vault_path']}")
        print(f"  manifest: {brain['manifest_path']}")
        print(f"  status: {brain.get('status', 'unknown')}")
    return 0


def validate_brain(brain: dict[str, Any]) -> dict[str, Any]:
    manifest = Path(str(brain["manifest_path"]))
    vault = Path(str(brain["vault_path"]))
    audit = Path(str(brain["audit_path"]))
    readiness = Path(str(brain["readiness_report_path"]))

    manifest_ok = manifest.exists()
    vault_ok = vault.exists()
    audit_ok = audit.exists()
    readiness_ok = readiness.exists()

    validate_ok = False
    if manifest_ok:
        try:
            subprocess.run(
                [sys.executable, str(VALIDATE_MANIFEST), "--manifest", str(manifest), "--check-paths"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            validate_ok = True
        except subprocess.CalledProcessError:
            validate_ok = False

    return {
        "slug": brain["slug"],
        "manifest_ok": manifest_ok,
        "vault_ok": vault_ok,
        "audit_ok": audit_ok,
        "readiness_ok": readiness_ok,
        "validate_ok": validate_ok,
    }


def doctor(portfolio_root: Path) -> int:
    registry = ensure_registry_exists(portfolio_root)
    brains = registry.get("brains") or []
    if not brains:
        print("No second brains registered yet.")
        return 0

    failures = 0
    for brain in brains:
        result = validate_brain(brain)
        print(f"- {brain['name']} ({brain['slug']})")
        print(f"  manifest exists: {'yes' if result['manifest_ok'] else 'no'}")
        print(f"  manifest validates: {'yes' if result['validate_ok'] else 'no'}")
        print(f"  vault exists: {'yes' if result['vault_ok'] else 'no'}")
        print(f"  audit exists: {'yes' if result['audit_ok'] else 'no'}")
        print(f"  readiness exists: {'yes' if result['readiness_ok'] else 'no'}")
        if not all(result[key] for key in ("manifest_ok", "validate_ok", "vault_ok", "audit_ok", "readiness_ok")):
            failures += 1
    return 1 if failures else 0


def refresh(portfolio_root: Path, slug: str | None = None) -> int:
    registry = ensure_registry_exists(portfolio_root)
    brains = registry.get("brains") or []
    selected = [brain for brain in brains if slug is None or brain.get("slug") == slug]
    if not selected:
        raise SystemExit("No matching second brain found to refresh.")

    for brain in selected:
        manifest = Path(str(brain["manifest_path"]))
        vault = Path(str(brain["vault_path"]))
        audit = Path(str(brain["audit_path"]))
        readiness = Path(str(brain["readiness_report_path"]))
        run([sys.executable, str(VALIDATE_MANIFEST), "--manifest", str(manifest), "--check-paths"])
        run([sys.executable, str(AUDIT_VAULT), "--vault", str(vault), "--write", str(audit)])
        run([sys.executable, str(GENERATE_READINESS), "--manifest", str(manifest), "--write", str(readiness)])
        brain["status"] = "refreshed"
        brain["last_refreshed_at"] = now_iso()

    write_yaml(portfolio_paths(portfolio_root).registry, registry)
    return 0


def interactive_mode() -> int:
    print("Codex Second Brain Wizard")
    print("")
    print("1. Initialize a new portfolio")
    print("2. Add a new second brain")
    print("3. List second brains")
    print("4. Doctor check all second brains")
    print("5. Refresh audits and readiness reports")
    choice = prompt("Choose an action")

    if choice == "1":
        root = Path(prompt("Portfolio root path"))
        name = prompt("Portfolio display name", "Second Brain Portfolio")
        obsidian = prompt("Obsidian root path (leave blank to use portfolio/vaults)", "")
        mode = prompt("Default mode", "hybrid")
        registry = init_portfolio(
            root=root,
            name=name,
            obsidian_root=Path(obsidian) if obsidian else None,
            default_mode=mode,
        )
        print(f"Created portfolio registry at {registry}")
        return 0
    if choice == "2":
        portfolio = Path(prompt("Portfolio root path"))
        registry = ensure_registry_exists(portfolio)
        default_mode = registry["portfolio"].get("default_mode", "hybrid")
        name = prompt("Second brain name")
        slug = prompt("Second brain slug")
        mode = prompt("Mode", str(default_mode))
        vault = prompt("Vault path (leave blank for portfolio default)", "")
        singular = prompt("Entity singular", "entity")
        plural = prompt("Entity plural", "entities")
        brain = add_brain(
            portfolio_root=portfolio,
            name=name,
            slug=slug,
            mode=mode,
            vault_path=Path(vault) if vault else None,
            entity_singular=singular,
            entity_plural=plural,
        )
        print(f"Bootstrapped {brain['name']} at {brain['vault_path']}")
        return 0
    if choice == "3":
        return list_brains(Path(prompt("Portfolio root path")))
    if choice == "4":
        return doctor(Path(prompt("Portfolio root path")))
    if choice == "5":
        portfolio = Path(prompt("Portfolio root path"))
        slug = prompt("Slug to refresh (leave blank for all)", "")
        return refresh(portfolio, slug or None)

    raise SystemExit("Unknown action.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Multi-second-brain portfolio wizard.")
    sub = parser.add_subparsers(dest="command")

    init_cmd = sub.add_parser("init-portfolio", help="Create a new second-brain portfolio root.")
    init_cmd.add_argument("--portfolio-root", required=True, type=Path)
    init_cmd.add_argument("--name", default="Second Brain Portfolio")
    init_cmd.add_argument("--obsidian-root", type=Path)
    init_cmd.add_argument("--default-mode", default="hybrid", choices=["product", "operations", "hybrid"])

    add_cmd = sub.add_parser("add-brain", help="Add and bootstrap a second brain inside a portfolio.")
    add_cmd.add_argument("--portfolio-root", required=True, type=Path)
    add_cmd.add_argument("--name", required=True)
    add_cmd.add_argument("--slug", required=True)
    add_cmd.add_argument("--mode", default="hybrid", choices=["product", "operations", "hybrid"])
    add_cmd.add_argument("--vault-path", type=Path)
    add_cmd.add_argument("--entity-singular", default="entity")
    add_cmd.add_argument("--entity-plural", default="entities")

    list_cmd = sub.add_parser("list-brains", help="List all second brains in a portfolio.")
    list_cmd.add_argument("--portfolio-root", required=True, type=Path)

    doctor_cmd = sub.add_parser("doctor", help="Validate all registered second brains.")
    doctor_cmd.add_argument("--portfolio-root", required=True, type=Path)

    refresh_cmd = sub.add_parser("refresh", help="Regenerate audit and readiness outputs.")
    refresh_cmd.add_argument("--portfolio-root", required=True, type=Path)
    refresh_cmd.add_argument("--slug")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        return interactive_mode()

    if args.command == "init-portfolio":
        registry = init_portfolio(
            root=args.portfolio_root,
            name=args.name,
            obsidian_root=args.obsidian_root,
            default_mode=args.default_mode,
        )
        print(registry)
        return 0
    if args.command == "add-brain":
        brain = add_brain(
            portfolio_root=args.portfolio_root,
            name=args.name,
            slug=args.slug,
            mode=args.mode,
            vault_path=args.vault_path,
            entity_singular=args.entity_singular,
            entity_plural=args.entity_plural,
        )
        print(yaml.safe_dump(brain, sort_keys=False, allow_unicode=False).strip())
        return 0
    if args.command == "list-brains":
        return list_brains(args.portfolio_root)
    if args.command == "doctor":
        return doctor(args.portfolio_root)
    if args.command == "refresh":
        return refresh(args.portfolio_root, args.slug)

    parser.error("Unknown command.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
