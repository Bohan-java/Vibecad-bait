#!/usr/bin/env python3
"""Export machine-readable donor scene, texture, material and mesh mappings."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTRACTED = ROOT / "extracted" / "donor"
DOCS = ROOT / "docs"
ORIGINAL_LEVEL_BACKUP = ROOT / "backups" / "001_before_material_replacement" / "level.SCNE"


def read_scene(path: Path) -> tuple[str, dict]:
    document = json.loads("{" + path.read_text(encoding="utf-8").strip() + "}")
    name = next(iter(document))
    return name, document[name]


def write_csv(name: str, fieldnames: list[str], rows: list[dict]) -> None:
    path = DOCS / name
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    summaries: list[dict] = []
    textures: list[dict] = []
    materials: list[dict] = []
    models: list[dict] = []
    objects: list[dict] = []

    for scene_path in sorted(EXTRACTED.glob("*.SCNE")):
        source_path = ORIGINAL_LEVEL_BACKUP if scene_path.name == "level.SCNE" and ORIGINAL_LEVEL_BACKUP.exists() else scene_path
        scene_name, scene = read_scene(source_path)
        for section_name, value in scene.items():
            count = len(value) if isinstance(value, (dict, list)) else int(value is not None)
            summaries.append({"scene_file": scene_path.name, "scene_root": scene_name, "section": section_name, "count": count})

        for logical_name, spec in scene.get("Texture", {}).items():
            binary = spec.get("Binary", "")
            textures.append(
                {
                    "scene_file": scene_path.name,
                    "logical_name": logical_name,
                    "width": spec.get("Width", 1),
                    "height": spec.get("Height", 1),
                    "mips": spec.get("Mips", 1),
                    "faces": spec.get("Faces", 1),
                    "format": spec.get("Format", ""),
                    "texel_usage": spec.get("TexelUsage", ""),
                    "pixel_data_size": spec.get("PixelDataSize", ""),
                    "binary": binary,
                    "embedded": bool(binary and (EXTRACTED / binary).exists()),
                }
            )

        for material_name, spec in scene.get("Material", {}).items():
            resources = spec.get("Resource", {})
            if not resources:
                materials.append(
                    {
                        "scene_file": scene_path.name,
                        "material": material_name,
                        "effect": spec.get("Effect", ""),
                        "script": spec.get("Script", ""),
                        "resource_slot": "",
                        "logical_texture": "",
                    }
                )
            for resource_slot, resource in resources.items():
                materials.append(
                    {
                        "scene_file": scene_path.name,
                        "material": material_name,
                        "effect": spec.get("Effect", ""),
                        "script": spec.get("Script", ""),
                        "resource_slot": resource_slot,
                        "logical_texture": resource.get("Pixelmap", "") if isinstance(resource, dict) else "",
                    }
                )

        for model_name, spec in scene.get("Model", {}).items():
            primitives = spec.get("Prim", []) or [{}]
            vertex_binaries = [stream.get("Binary", "") for stream in spec.get("VertexStream", [])]
            for primitive in primitives:
                models.append(
                    {
                        "scene_file": scene_path.name,
                        "model": model_name,
                        "mesh": primitive.get("Mesh", ""),
                        "material": primitive.get("Material", ""),
                        "primitive_type": primitive.get("Type", ""),
                        "index_count": primitive.get("Count", ""),
                        "radius": spec.get("Radius", ""),
                        "min": json.dumps(spec.get("Min", []), separators=(",", ":")),
                        "max": json.dumps(spec.get("Max", []), separators=(",", ":")),
                        "index_binary": spec.get("IndexBuffer", {}).get("Binary", ""),
                        "vertex_binaries": ";".join(vertex_binaries),
                    }
                )

        for object_name, spec in scene.get("Object", {}).items():
            objects.append(
                {
                    "scene_file": scene_path.name,
                    "object": object_name,
                    "type": spec.get("Type", ""),
                    "target": spec.get("Target", ""),
                    "transform": spec.get("Transform", ""),
                    "matrix": json.dumps(spec.get("Matrix", []), separators=(",", ":")),
                }
            )

    write_csv("scene_summary.csv", ["scene_file", "scene_root", "section", "count"], summaries)
    write_csv(
        "texture_inventory.csv",
        ["scene_file", "logical_name", "width", "height", "mips", "faces", "format", "texel_usage", "pixel_data_size", "binary", "embedded"],
        textures,
    )
    write_csv("material_inventory.csv", ["scene_file", "material", "effect", "script", "resource_slot", "logical_texture"], materials)
    write_csv(
        "model_primitive_inventory.csv",
        ["scene_file", "model", "mesh", "material", "primitive_type", "index_count", "radius", "min", "max", "index_binary", "vertex_binaries"],
        models,
    )
    write_csv("object_inventory.csv", ["scene_file", "object", "type", "target", "transform", "matrix"], objects)
    print(f"Exported {len(textures)} textures, {len(materials)} material resources, {len(models)} model primitives and {len(objects)} objects")


if __name__ == "__main__":
    main()
