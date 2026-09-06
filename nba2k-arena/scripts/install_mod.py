#!/usr/bin/env python3
"""Guarded local installer for the NBA 2K26 mods/levels directory.

Dry-run is the default. Installation is only performed with ``--install`` and
always creates/verifies a local project backup before replacing the active mod.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / "output" / "install" / "levels" / "arena_020_int.iff"
GAME_ROOT = Path(r"D:\steam\steamapps\common\NBA 2K26")
BACKUP = ROOT / "backups" / "002_game_mod_before_install" / "arena_020_int.iff"
VALIDATION = ROOT / "docs" / "VALIDATION_REPORT.json"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-root", type=Path, default=GAME_ROOT)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    target = args.game_root / "mods" / "levels" / "arena_020_int.iff"
    if not target.exists():
        raise SystemExit(f"Expected active arena file not found: {target}")
    if args.restore:
        if not BACKUP.exists():
            raise SystemExit(f"Pre-install backup not found: {BACKUP}")
        shutil.copy2(BACKUP, target)
        if digest(BACKUP) != digest(target):
            raise SystemExit("Restore hash verification failed")
        print(f"Restored protected donor to {target}")
        return
    if not STAGED.exists():
        raise SystemExit(f"Staged build not found: {STAGED}")
    if not VALIDATION.exists() or json.loads(VALIDATION.read_text(encoding="utf-8")).get("status") != "PASS":
        raise SystemExit("Latest project validation report is not PASS")

    print(f"Staged: {STAGED} ({digest(STAGED)})")
    print(f"Active: {target} ({digest(target)})")
    print(f"Backup: {BACKUP}")
    if not args.install:
        print("Dry run only. Add --install to back up and replace the active mod file.")
        return

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    if not BACKUP.exists():
        shutil.copy2(target, BACKUP)
    if digest(target) == digest(STAGED):
        print("The staged build is already installed; no write was needed.")
        return
    if digest(BACKUP) != digest(target):
        raise SystemExit("Active arena differs from the preserved pre-install backup; refusing to overwrite")
    shutil.copy2(STAGED, target)
    if digest(STAGED) != digest(target):
        raise SystemExit("Installed file hash verification failed")
    print("Installed successfully; original active mod remains preserved in the local backup.")


if __name__ == "__main__":
    main()
