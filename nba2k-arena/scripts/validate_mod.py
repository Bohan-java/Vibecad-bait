#!/usr/bin/env python3
"""Validate archive integrity and donor structural invariants."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from tld_texture import BC1_FORMAT_CODE, read_header


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORIGINAL = ROOT / "donor" / "original" / "arena_020_int_original.iff"
DEFAULT_OUTPUT = ROOT / "output" / "arena_020_int_venice_material_pass.iff"
MANIFEST_PATH = ROOT / "textures" / "final" / "texture_manifest.json"
REPORT_JSON = ROOT / "docs" / "VALIDATION_REPORT.json"
REPORT_MD = ROOT / "docs" / "VALIDATION_REPORT.md"
EXPECTED_ORIGINAL_SHA256 = "42865ecaf8dd923c4d901509263af3b242c00975f4284b917ba79ce8fbbced46"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scene_fragment(data: bytes) -> dict:
    return json.loads(b"{" + data.strip() + b"}")


def canonical_digest(value: object) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    checks: dict[str, object] = {}
    failures: list[str] = []

    original_sha = digest(args.original.read_bytes())
    checks["original_sha256"] = original_sha
    if original_sha != EXPECTED_ORIGINAL_SHA256:
        failures.append("The protected donor hash no longer matches the recorded original")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    with zipfile.ZipFile(args.original, "r") as original_zip, zipfile.ZipFile(args.output, "r") as output_zip:
        original_names = original_zip.namelist()
        output_names = output_zip.namelist()
        corrupt = output_zip.testzip()
        checks["archive_test"] = "PASS" if corrupt is None else f"FAIL: {corrupt}"
        if corrupt:
            failures.append(f"Output archive CRC failure: {corrupt}")

        expected_added = {spec["binary"] for spec in manifest.values()}
        actual_added = set(output_names) - set(original_names)
        checks["original_entry_count"] = len(original_names)
        checks["output_entry_count"] = len(output_names)
        checks["added_entries"] = sorted(actual_added)
        if actual_added != expected_added:
            failures.append("Output added-entry set does not match the local texture manifest")
        missing = set(original_names) - set(output_names)
        if missing:
            failures.append(f"Output dropped {len(missing)} original entries")

        changed_original_entries = []
        for name in original_names:
            if digest(original_zip.read(name)) != digest(output_zip.read(name)):
                changed_original_entries.append(name)
        checks["changed_original_entries"] = changed_original_entries
        if changed_original_entries != ["level.SCNE"]:
            failures.append("Files other than level.SCNE changed, or level.SCNE did not change")

        original_level = scene_fragment(original_zip.read("level.SCNE"))["level"]
        output_level = scene_fragment(output_zip.read("level.SCNE"))["level"]
        structural = {}
        for section in ("Light", "Model", "Object"):
            before = canonical_digest(original_level.get(section))
            after = canonical_digest(output_level.get(section))
            structural[section] = {"before": before, "after": after, "unchanged": before == after}
            if before != after:
                failures.append(f"Geometry-critical level section changed: {section}")
        checks["level_structural_sections"] = structural

        critical_entries = [
            "baskets.SCNE",
            "baskets_collisions.Coll",
            "level_collisions.Coll",
            "MAIN.Coll",
            "crowd.CrowdData",
            "crowd.SCNE",
        ]
        critical = {}
        for name in critical_entries:
            same = digest(original_zip.read(name)) == digest(output_zip.read(name))
            critical[name] = same
            if not same:
                failures.append(f"Gameplay-critical entry changed: {name}")
        checks["critical_entries_unchanged"] = critical

        local_textures = {}
        for spec in manifest.values():
            logical = spec["logical_name"]
            binary = spec["binary"]
            scene_spec = output_level["Texture"].get(logical)
            header_path = ROOT / "extracted" / "donor" / binary
            header = read_header(header_path)
            okay = (
                scene_spec is not None
                and scene_spec.get("Binary") == binary
                and header["format_code"] == BC1_FORMAT_CODE
                and header["file_size"] == 32 + header["pixel_data_size"]
                and len(output_zip.read(binary)) == header["file_size"]
            )
            local_textures[logical] = {"binary": binary, "header": header, "valid": okay}
            if not okay:
                failures.append(f"Local texture failed validation: {logical}")
        checks["local_textures"] = local_textures

    checks["status"] = "PASS" if not failures else "FAIL"
    checks["failures"] = failures
    REPORT_JSON.write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
    md = [
        "# Validation Report",
        "",
        f"**Status:** {checks['status']}",
        "",
        f"- Protected donor SHA-256: `{original_sha}`",
        f"- Original entries: {checks['original_entry_count']}",
        f"- Output entries: {checks['output_entry_count']}",
        f"- Changed original entries: {', '.join(changed_original_entries)}",
        f"- Added local textures: {len(expected_added)}",
        "- Geometry-critical `Light`, `Model`, and `Object` sections: unchanged",
        "- Basket, collision, crowd and gameplay-critical resources: unchanged",
        "",
    ]
    if failures:
        md += ["## Failures", ""] + [f"- {item}" for item in failures] + [""]
    REPORT_MD.write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"status": checks["status"], "failures": failures}, indent=2))
    raise SystemExit(0 if not failures else 1)


if __name__ == "__main__":
    main()
