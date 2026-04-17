#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import yaml


def load_manifest(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit("Manifest root must be a mapping.")
    return data


def run(cmd: list[str], dry_run: bool) -> None:
    print("+", " ".join(cmd))
    if dry_run:
        return
    subprocess.run(cmd, check=True)


def resolve_default_branch(item: dict[str, object]) -> str:
    owner = str(item["owner"])
    name = str(item["name"])
    fallback = str(item.get("default_branch", "main"))
    try:
        output = subprocess.check_output(
            ["gh", "repo", "view", f"{owner}/{name}", "--json", "defaultBranchRef"],
            text=True,
        )
        data = json.loads(output)
        branch = data["defaultBranchRef"]["name"]
        if branch:
            return str(branch)
    except Exception:
        pass
    return fallback


def sync_repo(item: dict[str, object], mirror_root: Path, dry_run: bool) -> None:
    owner = str(item["owner"])
    name = str(item["name"])
    branch = resolve_default_branch(item)
    url = str(item.get("url") or f"https://github.com/{owner}/{name}.git")
    target = mirror_root / name

    if not target.exists():
        run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--single-branch",
                "--branch",
                branch,
                url,
                str(target),
            ],
            dry_run,
        )
        return

    git_dir = target / ".git"
    if not git_dir.exists():
        raise SystemExit(f"Mirror target exists but is not a git checkout: {target}")

    run(["git", "-C", str(target), "remote", "set-url", "origin", url], dry_run)
    run(["git", "-C", str(target), "fetch", "origin", branch, "--prune"], dry_run)
    run(["git", "-C", str(target), "checkout", branch], dry_run)
    run(["git", "-C", str(target), "reset", "--hard", f"origin/{branch}"], dry_run)
    run(["git", "-C", str(target), "clean", "-fd"], dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync safe product repo mirrors from a manifest.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = load_manifest(args.manifest)
    repos = data.get("repositories") or {}
    mirror_root = Path(str(repos.get("safe_mirror_root"))).expanduser()
    items = repos.get("items") or []

    if not items:
        raise SystemExit("No repositories.items found in manifest.")

    mirror_root.mkdir(parents=True, exist_ok=True)
    print(f"Mirror root: {mirror_root}")

    for item in items:
        if not isinstance(item, dict):
            raise SystemExit("repositories.items entries must be mappings.")
        print(f"Syncing {item['owner']}/{item['name']}...")
        sync_repo(item=item, mirror_root=mirror_root, dry_run=args.dry_run)

    print(f"Synced {len(items)} repositories.")


if __name__ == "__main__":
    main()
