"""Prepare one floor-only candidate on the historical slot-700 repository base.

The scene comes from restore_repo_base.repository_pair(), never R7 or arena 011.
Only the R4 floor geometry and three albedo resources are reused. Existing lights,
exposure, floor lightmaps, shader passes and reflection textures remain unchanged.
No legacy build chain, file digest, or index-buffer checksum is calculated.
"""
from __future__ import annotations

from copy import copy, deepcopy
import io
import json
import math
from pathlib import Path
import struct
import tempfile
import zipfile

from restore_repo_base import ARCHIVED, NAMES, REVISION, ROOT, repository_pair

MAIN_NAME, FLOOR_NAME = NAMES
OUT = ROOT / "output/recovery_floor_step1"
R4_PACKAGE = ROOT / "output/revision4/venice_court_revision4.zip"
PACKAGE_NAME = "repo_base_floor_step1_700.zip"
STATUS = "FLOOR_ONLY_CANDIDATE_PREPARED_GAME_UNTESTED"
BASE_MATERIAL = "floor_clutchtime_court:area_1_mat"
LINE_TEMPLATE = "floor_clutchtime_court:floor_line_mat1"
MODEL_FIELDS = ("Prim", "VertexStream", "IndexBuffer", "IndexBufferCrc32")
LINE_TEXTURES = {
    "venice_v3:court_white_lines": "local/venice_v3/court_white",
    "venice_v3:court_lane_space_marks": "local/venice_v3/court_lane_marks",
}
CONCRETE_TEXTURE = "local/venice_v3/court_concrete"
TEXTURES = (*LINE_TEXTURES.values(), CONCRETE_TEXTURE)
TIMESTAMP = (2026, 9, 6, 12, 0, 0)


def parse_scene(raw):
    raw = raw.strip()
    result = json.loads(raw if raw.startswith(b"{") else b"{" + raw + b"}")
    if "level" not in result:
        raise ValueError("Expected the main level scene")
    return result


def check_archive(archive):
    names = archive.namelist()
    if not names or len(names) != len(set(names)):
        raise ValueError("Empty archive or duplicate member names")
    if any(info.flag_bits & 1 for info in archive.infolist()):
        raise ValueError("Encrypted archive member")


def check_geometry(base, donor, archive):
    """Validate the transferred bytes and the unchanged native floor metadata."""
    target = base["level"]["Object"]["__floor00__"]["Target"]
    old = base["level"]["Model"][target]
    new = donor["level"]["Model"][target]
    if donor["level"]["Object"]["__floor00__"] != base["level"]["Object"]["__floor00__"]:
        raise ValueError("R4 moved or rebound the floor object")
    if {k: v for k, v in old.items() if k not in MODEL_FIELDS} != {
        k: v for k, v in new.items() if k not in MODEL_FIELDS
    }:
        raise ValueError("R4 changed floor metadata outside the geometry fields")
    if len(new["Prim"]) != 74 or len(new["VertexStream"]) != 1:
        raise ValueError("Expected the R4 floor without the R5 pale-paint overlay")
    stream, index = new["VertexStream"][0], new["IndexBuffer"]
    if stream.get("Stride") != 28 or index.get("Format") != "R16_UINT":
        raise ValueError("Unsupported floor vertex/index layout")
    vb, ib = archive.read(stream["Binary"]), archive.read(index["Binary"])
    if len(vb) != stream["Size"] or len(ib) != index["Size"]:
        raise ValueError("Floor binary sizes differ from scene declarations")
    if (len(vb), len(ib)) != (785148, 53640):
        raise ValueError("Unexpected R4 floor geometry size")
    indices = [item[0] for item in struct.iter_unpack("<H", ib)]
    if max(indices) >= len(vb) // 28:
        raise ValueError("Floor index points outside the vertex buffer")
    for offset in range(0, len(vb), 28):
        position = struct.unpack_from("<3f", vb, offset)
        if not all(math.isfinite(v) for v in position):
            raise ValueError("Non-finite floor position")
        if any(v < lo - .001 or v > hi + .001
               for v, lo, hi in zip(position, old["Min"], old["Max"])):
            raise ValueError("Floor position exceeds the original bounds")
    cursor = 0
    for prim in new["Prim"]:
        if prim["Start"] != cursor or prim["Count"] % 3:
            raise ValueError("Invalid floor primitive range")
        if prim["Material"] not in {BASE_MATERIAL, *LINE_TEXTURES}:
            raise ValueError("Unexpected floor material dependency")
        cursor += prim["Count"]
    if cursor != len(indices):
        raise ValueError("Floor primitive ranges do not cover the index buffer")
    features = {prim["Mesh"] for prim in new["Prim"]}
    if not {"venice_v3:division_line", "venice_v3:center_outer_circle",
            "venice_v3:center_inner_circle"}.issubset(features):
        raise ValueError("The transferred floor is missing its center markings")
    return target, {
        "primitives": len(new["Prim"]), "vertices": len(vb) // 28,
        "indices": len(indices), "bounds_and_vertex_format_preserved": True,
        "floor_object_preserved": True, "finite_positions_and_valid_index_ranges": True,
        "pale_paint_overlay_included": False,
        "index_buffer_checksum_metadata_copied_without_recalculation": True,
    }


def make_candidate(base, donor):
    result = deepcopy(base)
    source, level = donor["level"], result["level"]
    target = level["Object"]["__floor00__"]["Target"]
    for field in MODEL_FIELDS:
        level["Model"][target][field] = deepcopy(source["Model"][target][field])
    for name, texture in LINE_TEXTURES.items():
        if name in level["Material"]:
            raise ValueError("New line material already exists in the base")
        source_material = source["Material"][name]
        template = level["Material"][LINE_TEMPLATE]
        for field in ("Effect", "Technique"):
            if source_material[field] != template[field]:
                raise ValueError("R4 lines do not use the baseline floor shader passes")
        material = deepcopy(template)
        material["Resource"]["DetailAlbedoTexture"] = {"Pixelmap": texture}
        level["Material"][name] = material
    level["Material"][BASE_MATERIAL]["Resource"]["DetailAlbedoTexture"] = {
        "Pixelmap": CONCRETE_TEXTURE,
    }
    for name in TEXTURES:
        if name in level["Texture"]:
            raise ValueError("New albedo texture already exists in the base")
        level["Texture"][name] = deepcopy(source["Texture"][name])
    return result


def validate_scene(base, candidate, donor):
    """Reject every scene change outside the explicit local floor whitelist."""
    restored = deepcopy(candidate)
    old, level, source = base["level"], restored["level"], donor["level"]
    target = old["Object"]["__floor00__"]["Target"]
    for field in MODEL_FIELDS:
        if level["Model"][target][field] != source["Model"][target][field]:
            raise ValueError("Transferred floor field differs from R4: " + field)
        level["Model"][target][field] = deepcopy(old["Model"][target][field])
    for name, texture in LINE_TEXTURES.items():
        expected = deepcopy(old["Material"][LINE_TEMPLATE])
        expected["Resource"]["DetailAlbedoTexture"] = {"Pixelmap": texture}
        if level["Material"].pop(name) != expected:
            raise ValueError("New line material changed a preserved shader or texture slot")
    slot = level["Material"][BASE_MATERIAL]["Resource"]
    if slot["DetailAlbedoTexture"] != {"Pixelmap": CONCRETE_TEXTURE}:
        raise ValueError("Unexpected court albedo binding")
    slot["DetailAlbedoTexture"] = deepcopy(
        old["Material"][BASE_MATERIAL]["Resource"]["DetailAlbedoTexture"])
    for name in TEXTURES:
        if level["Texture"].pop(name) != source["Texture"][name]:
            raise ValueError("Copied texture metadata differs from R4")
    if restored != base:
        raise ValueError("Scene changed outside the floor geometry/albedo whitelist")


def main():
    pair = repository_pair()
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(R4_PACKAGE) as package:
        check_archive(package)
        r4_bytes = package.read(MAIN_NAME)
    with zipfile.ZipFile(io.BytesIO(pair[MAIN_NAME])) as baseline, \
            zipfile.ZipFile(io.BytesIO(r4_bytes)) as r4, \
            tempfile.TemporaryDirectory(prefix="stage_", dir=OUT) as directory:
        check_archive(baseline)
        check_archive(r4)
        stage = Path(directory)
        base, donor = parse_scene(baseline.read("level.SCNE")), parse_scene(r4.read("level.SCNE"))
        target, geometry = check_geometry(base, donor, r4)
        candidate = make_candidate(base, donor)
        validate_scene(base, candidate, donor)
        model = donor["level"]["Model"][target]
        binary_names = [model["VertexStream"][0]["Binary"], model["IndexBuffer"]["Binary"]]
        binary_names.extend(donor["level"]["Texture"][key]["Binary"] for key in TEXTURES)
        if len(binary_names) != 5 or len(set(binary_names)) != 5:
            raise ValueError("Expected exactly two geometry and three albedo binaries")
        if set(binary_names).intersection(baseline.namelist()):
            raise ValueError("A new binary would overwrite an existing baseline member")
        additions = {name: r4.read(name) for name in binary_names}
        main_path = stage / MAIN_NAME
        scene_bytes = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"),
                                allow_nan=False).encode("utf-8")[1:-1]
        with zipfile.ZipFile(main_path, "w") as built:
            built.comment = baseline.comment
            for info in baseline.infolist():
                built.writestr(copy(info), scene_bytes if info.filename == "level.SCNE" else baseline.read(info))
            for name, raw in additions.items():
                built.writestr(zipfile.ZipInfo(name, TIMESTAMP), raw)
        with zipfile.ZipFile(main_path) as built:
            check_archive(built)
            if built.namelist() != baseline.namelist() + binary_names:
                raise ValueError("Unexpected archive membership or ordering change")
            changed = [name for name in baseline.namelist() if baseline.read(name) != built.read(name)]
            if changed != ["level.SCNE"]:
                raise ValueError("Changed an original binary, lightmap, basket or other scene")
            validate_scene(base, parse_scene(built.read("level.SCNE")), donor)
            for name, raw in additions.items():
                if built.read(name) != raw:
                    raise ValueError("Transferred binary differs from R4: " + name)
        (stage / FLOOR_NAME).write_bytes(pair[FLOOR_NAME])
        if (stage / FLOOR_NAME).read_bytes() != pair[FLOOR_NAME]:
            raise ValueError("Companion floor differs from the repository base")
        report = {
            "status": STATUS, "court_complete": False, "game_runtime_verified": False,
            "base": {"revision": REVISION, "directory": ARCHIVED,
                     "source_is_011": False, "source_is_r7": False},
            "reused_assets": {"archive": str(R4_PACKAGE.relative_to(ROOT)),
                              "model": target, "geometry": geometry},
            "changed_original_archive_members": changed,
            "added_archive_members": [{"name": name, "bytes": len(raw)} for name, raw in additions.items()],
            "changed_existing_model_fields": list(MODEL_FIELDS),
            "changed_existing_material_slots": [BASE_MATERIAL + ".Resource.DetailAlbedoTexture"],
            "added_materials": list(LINE_TEXTURES), "added_textures": list(TEXTURES),
            "preserved": {
                "all_original_members_except_level_scene_byte_identical": True,
                "all_scene_fields_outside_whitelist": True,
                "all_light_exposure_postprocess_and_floor_lightmap_data": True,
                "floor_object_userdata_bounds_vertex_format_and_gameplay_anchors": True,
                "all_existing_shader_effects_and_techniques": True,
                "baseline_base_normal_reflection_logo_textures_and_material_parameters": True,
                "companion_floor_byte_identical_to_repository": True,
            },
            "file_digests_computed": False, "game_directory_modified": False,
            "files": {name: {"bytes": (stage / name).stat().st_size} for name in NAMES},
            "limitations": [
                "Prepared for a later local floor-only test; the exact restored base is being tested first.",
                "The indoor enclosure, cyan border, dark palms and prior reflection behavior remain.",
                "The added center/standard court markings change visible geometry, not scoring rules.",
                "No R5 pale-paint overlay, R7 scene data, global DDS conversion or new lighting is included.",
                "Static validation does not establish game visibility or playable behavior.",
            ],
        }
        (stage / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (stage / "README.txt").write_text(
            "基于仓库历史版本的下一步局部候选：球场标线与水泥颜色\n\n"
            "开发基底：repo Checkpoint 1（fde9489），仍是 700 教学场地。\n"
            "先确认原样恢复包正常，本包只为之后的单独测试准备，尚未通过游戏实测。\n\n"
            "本次仅迁回 R4 球场标线网格、中线/中圈以及 4K 灰水泥颜色贴图。\n"
            "白线与暗色标记使用旧版原 floor 材质，只换颜色贴图。\n"
            "原灯光、曝光、后处理、地板光照、篮筐、碰撞与玩法数据保留；\n"
            "原法线、粗糙度和反光配置保留，因此油亮问题仍待单独处理。\n"
            "室内屋顶、悬挂屏、青色边框和黑树仍在，没有迁入失败的 R7 场景。\n"
            "这不是完成的海边球场，也不是已确认正常的发布版本。\n\n"
            "确认开始这一局部测试后，完全退出游戏，备份当前 700 配套文件，\n"
            "解压最外层 ZIP，将两份原名 IFF 一起用于原来 700 场地的位置。\n"
            "不要解开 IFF，也不要改成 011 或 blacktop。\n"
            "需要观察：人物/篮筐/地板是否可见，中线中圈是否出现，是否能移动和投篮。\n",
            encoding="utf-8",
        )
        files = (*NAMES, "README.txt", "validation.json")
        package_path = stage / PACKAGE_NAME
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for name in files:
                info = zipfile.ZipInfo(name, TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                package.writestr(info, (stage / name).read_bytes())
        with zipfile.ZipFile(package_path) as package:
            check_archive(package)
            if package.namelist() != list(files):
                raise ValueError("Unexpected distribution archive contents")
            for name in files:
                if package.read(name) != (stage / name).read_bytes():
                    raise ValueError("Distribution member differs from staged file: " + name)
        output = {"status": STATUS, "package": str(OUT / PACKAGE_NAME),
                  "package_bytes": package_path.stat().st_size, "files": report["files"],
                  "geometry": geometry}
        for name in (*files, PACKAGE_NAME):
            (stage / name).replace(OUT / name)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
