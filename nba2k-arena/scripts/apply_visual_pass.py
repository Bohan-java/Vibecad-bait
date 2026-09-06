#!/usr/bin/env python3
"""Apply a material-only Venice Beach visual pass to the donor level scene."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "extracted" / "donor" / "level.SCNE"
MANIFEST_PATH = ROOT / "textures" / "final" / "texture_manifest.json"
BACKUP_PATH = ROOT / "backups" / "001_before_material_replacement" / "level.SCNE"


def read_fragment(path: Path) -> dict:
    return json.loads("{" + path.read_text(encoding="utf-8").strip() + "}")


def write_fragment(path: Path, payload: dict) -> None:
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(compact[1:-1], encoding="utf-8")


def material(level: dict, name: str) -> dict:
    try:
        return level["Material"][name]
    except KeyError as exc:
        raise KeyError(f"Required donor material not found: {name}") from exc


def set_resource(level: dict, material_name: str, slot: str, logical_name: str) -> None:
    target = material(level, material_name)
    if slot not in target.get("Resource", {}):
        raise KeyError(f"Required resource slot not found: {material_name}.{slot}")
    target["Resource"][slot]["Pixelmap"] = logical_name


def set_parameter(level: dict, material_name: str, parameter: str, value: object) -> None:
    target = material(level, material_name)
    target.setdefault("Parameter", {})[parameter] = value


def texture_entry(spec: dict) -> dict:
    entry: dict[str, object] = {
        "Width": spec["width"],
        "Height": spec["height"],
        "Mips": spec["mips"],
        "Format": spec["format"],
        "Min": spec["min"],
        "Max": spec["max"],
        "PixelDataSize": spec["pixel_data_size"],
        "Binary": spec["binary"],
    }
    if spec["width"] == 1 and spec["height"] == 1:
        entry.pop("Width")
        entry.pop("Height")
        entry.pop("Mips")
    return entry


def apply(level: dict, manifest: dict[str, dict]) -> list[str]:
    logical = {name: spec["logical_name"] for name, spec in manifest.items()}
    for spec in manifest.values():
        level["Texture"][spec["logical_name"]] = texture_entry(spec)

    changed: list[str] = []

    # Court: preserve the donor court mesh and all line meshes, but remove the
    # donor branding/wood identity and supply the reference-inspired asphalt.
    set_resource(level, "floor_clutchtime_court:area_1_mat", "DetailAlbedoTexture", logical["asphalt"])
    set_resource(level, "floor_clutchtime_court:area_1_mat", "Logo0Texture", logical["asphalt"])
    set_parameter(level, "floor_clutchtime_court:area_1_mat", "ModulateAlbedo", [1.0, 1.0, 1.0])
    set_resource(level, "clutchtime_floor_apron:floor_mat", "AlbedoMap", logical["asphalt"])
    set_parameter(level, "clutchtime_floor_apron:floor_mat", "AlbedoModulate", [0.92, 0.94, 0.95, 1.0])
    changed += ["court surface", "floor apron"]

    # Seating and terraced edges become metal bleachers, concrete and grass.
    set_resource(level, "clutchtime_crowd_seating:chair", "AlbedoMap", logical["aluminum"])
    set_parameter(level, "clutchtime_crowd_seating:chair", "AlbedoModulate", [1.0, 1.0, 1.0, 1.0])
    set_resource(level, "clutchtime_balcony_b:balcony_mat", "AlbedoMap", logical["concrete"])
    set_parameter(level, "clutchtime_balcony_b:balcony_mat", "AlbedoModulate", [1.0, 1.0, 1.0, 1.0])
    set_resource(level, "clutchtime_balcony_b:balcony2_amt", "AlbedoMap", logical["grass"])
    set_parameter(level, "clutchtime_balcony_b:balcony2_amt", "AlbedoModulate", [1.0, 1.0, 1.0, 1.0])
    set_resource(level, "clutchtime_balcony_b:balcony4_mat", "AlbedoMap", logical["concrete"])
    set_parameter(level, "clutchtime_balcony_b:balcony4_mat", "AlbedoModulate", [1.0, 1.0, 1.0, 1.0])
    set_resource(level, "clutchtime_balcony_railing:railing_mat", "AlbedoMap", logical["aluminum"])
    changed += ["seating", "terraces", "railings"]

    # Lower enclosure reads as beach-side concrete. Existing normal/rough maps
    # remain in place, so only visible albedo identity changes.
    for name in (
        "clutchtime_mural_wall:mural_mat",
        "clutchtime_wall_corner:wallcorner_mat",
        "clutchtime_wall_f:wall_mat",
        "clutchtime_stands_tunnel:tunnel_mat",
        "clutchtime_stair_3step:steps_mat",
    ):
        set_resource(level, name, "AlbedoMap", logical["concrete"])
        set_parameter(level, name, "AlbedoModulate", [1.0, 1.0, 1.0, 1.0])

    wall_c = material(level, "clutchtime_wall_c:wall_mat")
    for layer in ("LAYER0", "LAYER1"):
        wall_c["Resource"][f"{layer}_AlbedoMap"]["Pixelmap"] = logical["concrete"]
        wall_c.setdefault("Parameter", {})[f"{layer}_AlbedoModulate"] = [1.0, 1.0, 1.0, 1.0]
    changed += ["walls", "stairs", "tunnel"]

    # Reuse mural and ceiling surfaces as a conservative sky continuation.
    for index in range(1, 6):
        set_resource(level, f"clutchtime_mural_wall:mural{index}_mat", "AlbedoMap", logical["sky"])
        set_parameter(level, f"clutchtime_mural_wall:mural{index}_mat", "AlbedoModulate", [1.0, 1.0, 1.0, 1.0])
    set_resource(level, "clutchtime_ceiling_a:ceilinga_mat", "AlbedoMap", logical["sky"])
    set_parameter(level, "clutchtime_ceiling_a:ceilinga_mat", "AlbedoModulate", [1.0, 1.0, 1.0, 1.0])
    set_resource(level, "clutchtime_ceilingpanel_c:panelc_mat", "AlbedoMap", logical["sky"])
    set_parameter(level, "clutchtime_ceilingpanel_c:panelc_mat", "AlbedoModulate", [1.0, 1.0, 1.0, 1.0])
    set_resource(level, "clutchtime_ceiling_ribs:ceilingribs_mat", "AlbedoMap", logical["dark_metal"])
    changed += ["mural sky continuation", "ceiling sky continuation", "dark structure"]

    # Neutralize arena-style animated boards/screens without deleting geometry.
    for index in range(1, 14):
        set_resource(level, f"clutchtime_court_dornaled:flp_scrf{index:02d}", "BaseTexture", logical["dark_metal"])
    for name in (
        "clutchtime_scorecube_screen:dorna_LCD_mat",
        "clutchtime_scorecube_screen:gamestats_ribbon_mat",
    ):
        set_resource(level, name, "BaseTexture", logical["dark_metal"])
    changed += ["LED boards", "score cube screens"]
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", action="store_true", help="restore level.SCNE from the first local backup")
    args = parser.parse_args()
    if args.restore:
        if not BACKUP_PATH.exists():
            raise SystemExit(f"Backup not found: {BACKUP_PATH}")
        shutil.copy2(BACKUP_PATH, SCENE_PATH)
        print(f"Restored {SCENE_PATH}")
        return

    if not MANIFEST_PATH.exists():
        raise SystemExit("Run scripts/create_visual_textures.py first")
    BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not BACKUP_PATH.exists():
        shutil.copy2(SCENE_PATH, BACKUP_PATH)

    before = read_fragment(SCENE_PATH)
    after = copy.deepcopy(before)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    changed = apply(after["level"], manifest)
    # Hard stop if anything structural changed in memory.
    for section in ("Light", "Model", "Object"):
        if before["level"].get(section) != after["level"].get(section):
            raise RuntimeError(f"Geometry-critical section changed unexpectedly: {section}")
    write_fragment(SCENE_PATH, after)
    print("Applied material-only visual pass:")
    for item in changed:
        print(f"- {item}")


if __name__ == "__main__":
    main()
