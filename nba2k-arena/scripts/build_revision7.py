"""Build the R6 game-feedback repair using structural and direct byte checks.

Uses Python's standard library and pure existing pixel-format helpers. It does
not invoke the historical build chain or calculate file digests. The original
IFF resources are copied verbatim except the two explicit scene fragments.
"""
from __future__ import annotations

import argparse
from copy import copy, deepcopy
import io
import json
from pathlib import Path
import tempfile
import zipfile

from revision7_runtime_lighting import (
    AMBIENT_BINARY, AUX_SCENE, EXPOSURE_EV100, NATIVE_EFFECT,
    apply_runtime_lighting, check_scope, require_native_uv7, scenery_records,
)

ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / 'output/revision6'
OUT = ROOT / 'output/revision7'
BUILD = ROOT / 'build/revision7'
MAIN_NAME = 'arena_700_int.iff'
FLOOR_NAME = 'arena_700_int_floor.iff'
PACKAGE_NAME = 'venice_court_revision7.zip'
STATUS = 'RUNTIME_REPAIR_CANDIDATE_GAME_UNTESTED'
MODIFIED_MEMBERS = {'level.SCNE', AUX_SCENE}


def parse_fragment(raw):
    raw = raw.strip()
    return json.loads(raw if raw.startswith(b'{') else b'{' + raw + b'}')


def serialize_fragment(document):
    return json.dumps(document, separators=(',', ':'), allow_nan=False).encode()[1:-1]


def input_member(name):
    path = BASE_DIR / name
    if path.is_file():
        return path.read_bytes()
    with zipfile.ZipFile(BASE_DIR / 'venice_court_revision6.zip') as archive:
        require_archive_structure(archive, stored=False)
        return archive.read(name)


def require_archive_structure(archive, *, stored=True):
    names = archive.namelist()
    if not names or len(names) != len(set(names)):
        raise ValueError('Archive has no members or has duplicate member names')
    if any(info.flag_bits & 1 for info in archive.infolist()):
        raise ValueError('Encrypted members are unsupported')
    if stored and any(info.compress_type != zipfile.ZIP_STORED for info in archive.infolist()):
        raise ValueError('Native IFF resources must use ZIP_STORED')


def verify_resource_links(level, built, report):
    names = set(built.namelist())
    effect = level['Effect'][NATIVE_EFFECT]
    shader_count = 0
    for technique in effect['Technique'].values():
        for render_pass in technique['Pass'].values():
            for stage in ('VS', 'PS', 'CS'):
                if stage in render_pass and 'Binary' in render_pass[stage]:
                    if render_pass[stage]['Binary'] not in names:
                        raise ValueError('An original static shader is missing')
                    shader_count += 1
    for name in report['objects']:
        if level['Object'][name]['Target'] not in level['Model']:
            raise ValueError('A scenery instance has no model')
        for key in (name, name + '_linelightvisibility'):
            if level['Texture'][key]['Binary'] not in names:
                raise ValueError('A new instance lighting texture is missing')
    for name in report['materials']:
        material = level['Material'][name]
        if material['Script'] not in names:
            raise ValueError('The original material script is missing')
        for resource in material['Resource'].values():
            key = resource.get('Pixelmap')
            if key and (key not in level['Texture'] or level['Texture'][key]['Binary'] not in names):
                raise ValueError('A generated material texture is missing: ' + str(key))
    return shader_count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ev100', type=float, default=EXPOSURE_EV100,
                        help='Fixed daylight starting point; requires game feedback to calibrate')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    print('Reading the existing R6 candidate; no historical rebuild', flush=True)
    main_raw, floor_raw = input_member(MAIN_NAME), input_member(FLOOR_NAME)
    with zipfile.ZipFile(io.BytesIO(floor_raw)) as floor_archive:
        require_archive_structure(floor_archive)
    with tempfile.TemporaryDirectory(prefix='runtime_repair_', dir=BUILD) as directory:
        stage = Path(directory)
        path, floor = stage / MAIN_NAME, stage / FLOOR_NAME
        with zipfile.ZipFile(io.BytesIO(main_raw)) as base:
            require_archive_structure(base)
            before_doc = parse_fragment(base.read('level.SCNE'))
            before = before_doc['level']
            records = scenery_records(before)
            if tuple(map(len, records)) != (16, 83, 136):
                raise ValueError('This repair expects the R6 scenery set (16 materials, 83 models, 136 objects)')
            require_native_uv7(before, base, records[1])
            floor_before = parse_fragment(base.read(AUX_SCENE))
            after_doc, floor_after = deepcopy(before_doc), deepcopy(floor_before)
            level, extra = after_doc['level'], {}
            report = apply_runtime_lighting(level, floor_after, extra, ev100=args.ev100)
            check_scope(before, level, floor_before, floor_after, report)
            overrides = {'level.SCNE': serialize_fragment(after_doc),
                         AUX_SCENE: serialize_fragment(floor_after)}
            if set(extra) & set(base.namelist()):
                raise ValueError('Refusing to replace an existing binary resource')
            print('Writing repaired static lighting bindings and disabling indoor court lights', flush=True)
            with zipfile.ZipFile(path, 'w') as target:
                target.comment = base.comment
                for info in base.infolist():
                    target.writestr(copy(info), overrides.get(info.filename, base.read(info)))
                for name, raw in sorted(extra.items()):
                    info = zipfile.ZipInfo(name, (2014, 1, 1, 17, 0, 0))
                    info.compress_type = zipfile.ZIP_STORED
                    target.writestr(info, raw)
            print('Checking protected scene records, native shaders, buffers, and paired floor', flush=True)
            with zipfile.ZipFile(path) as built:
                require_archive_structure(built)
                if set(built.namelist()) != set(base.namelist()) | set(extra):
                    raise ValueError('The candidate archive member set changed unexpectedly')
                changed = {name for name in base.namelist() if base.read(name) != built.read(name)}
                if changed != MODIFIED_MEMBERS:
                    raise ValueError('Unexpected changed original members: ' + str(sorted(changed)))
                for name, raw in extra.items():
                    if built.read(name) != raw:
                        raise ValueError('The embedded new texture differs from its generated bytes')
                if parse_fragment(built.read('level.SCNE')) != after_doc:
                    raise ValueError('Scene serialization changed the repair')
                shader_count = verify_resource_links(level, built, report)
                member_count = len(built.namelist())
        floor.write_bytes(floor_raw)
        if floor.read_bytes() != floor_raw:
            raise ValueError('The protected paired floor differs from R6')
        validation = {
            'status': STATUS, 'base_revision': 6,
            'input_game_result': 'REJECTED_WHITE_COURT_AND_BLACK_SCENERY',
            'game_runtime_verified': False, 'game_directory_modified': False,
            'file_digests_computed': False,
            'changed_existing_archive_members': sorted(changed),
            'new_binary_resources': sorted(extra), 'archive_members': member_count,
            'repaired_scenery': dict(zip(('materials', 'models', 'objects'), map(len, records))),
            'native_shader_stage_references_present': shader_count,
            'all_existing_binary_resources_byte_identical': True,
            'all_original_effects_byte_identical': True,
            'all_existing_geometry_buffers_byte_identical': True,
            'all_existing_object_transforms_preserved': True,
            'court_markings_materials_gameplay_and_collision_preserved': True,
            'paired_floor_byte_identical_to_revision6': True,
            'scene_scope_check_passed': True, 'fixed_ev100': args.ev100,
            'scenery_ambient_texture': AMBIENT_BINARY,
            'scenery_and_floor_indoor_linelight_visibility': 0.,
            'limitations': [
                'Runtime descriptor resolution and static technique selection require a new NBA 2K capture.',
                'Fixed EV15 is an initial noon exposure setting, not a measured game calibration.'
                    if args.ev100 == 15. else 'The selected fixed exposure still requires game calibration.',
                'Constant ambient fill is an approximation, not a spatial lighting bake.',
                'The original indoor basket geometry remains; this repair targets lighting only.',
            ],
            'artifacts': {p.name: {'bytes': p.stat().st_size} for p in (path, floor)},
        }
        validation_path, readme = stage / 'validation.json', stage / 'README.txt'
        validation_path.write_text(json.dumps(validation, indent=2) + '\n')
        readme.write_text(
            'Venice court Revision 7 - runtime lighting repair candidate\n'
            'STATUS: GAME UNTESTED. R6 was rejected by actual user screenshots.\n\n'
            '解压本外层 ZIP，将其中同编号的两份 IFF 一起用于 slot 700。\n'
            '替换前保留旧版备份；不要再解开 IFF，也不要混用不同版本。\n'
            '本构建程序不会安装软件、写入游戏目录或启动游戏。\n\n'
            '本次针对游戏实测中的白色过曝和黑色场外物体：\n'
            '1. 关闭四盏残留室内场灯，并清零场地/场外的室内线光可见性。\n'
            '2. 为 136 个场外实例补齐原生静态光照数据、贴图绑定和完整材质通道。\n'
            f'3. 保留原生室外天空和太阳，关闭自动 EV，设定固定 EV100={args.ev100:g}。\n\n'
            '所有原有顶点/索引/着色器二进制、球场涂装、篮筐位置、碰撞和玩法数据保留。\n'
            '曝光值和静态光照的运行时绑定仍需 NBA 2K 实测，不能以网页预览代替。\n'
            '请先完全退出再进入同一场地，检查人物衣服/肤色、深灰地面白线、绿色树冠及场外设施。\n'
            '若仍异常，请保留同一机位截图；这版不是已经验收的最终质量版本。\n'
        )
        package = stage / PACKAGE_NAME
        print('Packing the two matching IFF files for game testing', flush=True)
        with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as packed:
            for p in (path, floor, validation_path, readme):
                info = zipfile.ZipInfo(p.name, (2026, 9, 6, 12, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                packed.writestr(info, p.read_bytes(), compresslevel=9)
        if package.stat().st_size >= 100 * 1024 * 1024:
            raise ValueError('The shipping package exceeds the existing GitHub file-size boundary')
        with zipfile.ZipFile(package) as packed:
            require_archive_structure(packed, stored=False)
            if set(packed.namelist()) != {MAIN_NAME, FLOOR_NAME, 'validation.json', 'README.txt'}:
                raise ValueError('The shipping file set is incomplete')
            for p in (path, floor, validation_path, readme):
                if packed.read(p.name) != p.read_bytes():
                    raise ValueError('The shipping bytes differ from the staged artifact')
        shipping = {'name': package.name, 'bytes': package.stat().st_size}
        report.update(validation=validation, shipping_zip=shipping)
        report_json = json.dumps(report, indent=2) + '\n'
        for p in (path, floor, validation_path, readme, package):
            p.replace(OUT / p.name)
        (BUILD / 'revision_report.json').write_text(report_json)
    print(json.dumps({'status': STATUS, 'repaired_scenery': validation['repaired_scenery'],
                      'fixed_ev100': args.ev100, 'shipping_zip': shipping}, indent=2), flush=True)


if __name__ == '__main__':
    main()
