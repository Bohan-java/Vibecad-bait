#!/usr/bin/env python3
"""Repack the local extracted donor while preserving original archive metadata."""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORIGINAL = ROOT / "donor" / "original" / "arena_020_int_original.iff"
DEFAULT_EXTRACTED = ROOT / "extracted" / "donor"
DEFAULT_OUTPUT = ROOT / "output" / "arena_020_int_venice_material_pass.iff"
STAGED_OUTPUT = ROOT / "output" / "install" / "levels" / "arena_020_int.iff"


def clone_info(original: zipfile.ZipInfo) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(original.filename, original.date_time)
    info.compress_type = zipfile.ZIP_STORED
    info.comment = original.comment
    info.extra = original.extra
    info.internal_attr = original.internal_attr
    info.external_attr = original.external_attr
    info.create_system = original.create_system
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL)
    parser.add_argument("--extracted", type=Path, default=DEFAULT_EXTRACTED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(args.original, "r") as source:
        original_infos = source.infolist()
    original_names = {info.filename for info in original_infos}
    extracted_files = {
        path.relative_to(args.extracted).as_posix(): path
        for path in args.extracted.rglob("*")
        if path.is_file()
    }
    missing = original_names - extracted_files.keys()
    if missing:
        raise SystemExit(f"Refusing to build: {len(missing)} original entries are missing")

    with zipfile.ZipFile(args.output, "w", allowZip64=True) as target:
        for original_info in original_infos:
            data = extracted_files[original_info.filename].read_bytes()
            target.writestr(clone_info(original_info), data)
        for name in sorted(extracted_files.keys() - original_names):
            info = zipfile.ZipInfo(name, (2014, 1, 1, 17, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            target.writestr(info, extracted_files[name].read_bytes())
    STAGED_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.output, STAGED_OUTPUT)
    print(f"Built {args.output} with {len(extracted_files)} entries")
    print(f"Staged load-ready filename at {STAGED_OUTPUT}")


if __name__ == "__main__":
    main()
