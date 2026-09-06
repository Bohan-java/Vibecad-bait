"""Close the confirmed coastline gaps and simplify the photo-backed grey building.

This final local checkpoint extends the verified R5 candidate. It does not
install software, write to a game directory, or launch NBA 2K.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import zipfile

from build_revision3 import SOURCE, SOURCE_SHA, archive_scene, fragment, validate_scene
from build_revision5 import check_archive, file_sha, sha
from revision3_landscape import IDENTITY

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'output/revision5/arena_700_int.iff'
BASE_PACKAGE = BASE.parent / 'venice_court_revision5.zip'
BASE_SHA = '2fd02c8cfb3d771947cd4fe655db1f64f1ecf51a598bc1a8656ba16e1a670a3d'
FLOOR_NAME = 'arena_700_int_floor.iff'
FLOOR_SHA = '5f23522f783614d1572dca4f904132659f0d9ad4bd266b8148cbaacd333cf2ce'
OUT = ROOT / 'output/revision6'
BUILD = ROOT / 'build/revision6'
STATUS = 'STATIC_VALIDATED_GAME_UNTESTED'
CHANGED_MODELS = {'venice_v3:coast', 'venice_v3:service_building'}
COAST_PREFIX = 'venice_v3:coast_r6_'
BUILDING_PREFIX = 'venice_v3:building_r6_'


def base_member(name):
    path = BASE.parent / name
    if path.is_file():
        return path.read_bytes()
    with zipfile.ZipFile(BASE_PACKAGE) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('Duplicate names in the R5 shipping ZIP')
        return archive.read(name)


def verified_main_input():
    if BASE.is_file():
        if file_sha(BASE) != BASE_SHA:
            raise ValueError('R6 requires the verified R5 main IFF')
        return BASE
    raw = base_member(BASE.name)
    if sha(raw) != BASE_SHA:
        raise ValueError('R5 shipping ZIP contains a different main IFF')
    path = BUILD / 'verified_revision5_input.iff'
    path.write_bytes(raw)
    return path


def verified_environment_report():
    base = json.loads(base_member('validation.json'))
    if base['artifacts'][BASE.name]['sha256'] != BASE_SHA:
        raise ValueError('R5 validation belongs to a different main IFF')
    if base['artifacts'][FLOOR_NAME]['sha256'] != FLOOR_SHA:
        raise ValueError('R5 validation belongs to a different paired floor')
    report = json.loads((ROOT / 'build/revision3/revision_report.json').read_text())
    if report['artifacts'][BASE.name]['sha256'] != base['shared_validator_environment_audit_revision3_sha256']:
        raise ValueError('The R3 environment audit is not the linked R5 base')
    if not report.get('environment', {}).get('hidden_models') or not report['environment'].get('crowd_render_change'):
        raise ValueError('Missing original environment/crowd audit')
    return report


def check_scene_changes(before, level):
    """Enforce the explicit scenery-only boundary independently of generators."""
    if set(level) != set(before):
        raise ValueError('R6 must retain scene categories')
    changed, added = [], []
    for category, records in before.items():
        current = level[category]
        if not isinstance(records, dict):
            if current != records:
                raise ValueError(f'Protected scene category changed: {category}')
            continue
        if not isinstance(current, dict) or set(records) - set(current):
            raise ValueError(f'Protected scene records removed: {category}')
        for name, value in records.items():
            if current[name] != value:
                if category != 'Model' or name not in CHANGED_MODELS:
                    raise ValueError(f'Protected R5 record changed: {category}/{name}')
                changed.append({'category': category, 'name': name})
        for name in sorted(set(current) - set(records)):
            permitted = (category in ('Model', 'Object') and name.startswith(COAST_PREFIX)
                         or category in ('Material', 'Texture') and name.startswith(BUILDING_PREFIX))
            if not permitted:
                raise ValueError(f'Unexpected R6 addition: {category}/{name}')
            if category == 'Object':
                obj = current[name]
                target = obj.get('Target', '')
                expected = {'Type': 'OBJECT', 'Target': target, 'Transform': target, 'Matrix': IDENTITY}
                if (obj != expected or not target.startswith(COAST_PREFIX)
                        or target in before['Model'] or target not in level['Model']):
                    raise ValueError('Only identity instances of new coastal scenery are allowed')
            added.append({'category': category, 'name': name})
    if {item['name'] for item in changed} != CHANGED_MODELS:
        raise ValueError('Expected exactly the coast and grey building Models to change')
    return changed, added


def main():
    if not __debug__:
        raise RuntimeError('Run without -O: the shared validator uses assertions')
    from revision6_building import apply_building
    from revision6_coast import apply_coast
    if file_sha(SOURCE) != SOURCE_SHA:
        raise ValueError('Protected original donor changed')
    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    base = verified_main_input()
    environment = verified_environment_report()
    floor_raw = base_member(FLOOR_NAME)
    if sha(floor_raw) != FLOOR_SHA:
        raise ValueError('Protected paired floor changed')
    extra = {}
    with tempfile.TemporaryDirectory(prefix='revision6_candidate_', dir=BUILD) as directory:
        stage = Path(directory)
        path, floor = stage / BASE.name, stage / FLOOR_NAME
        with zipfile.ZipFile(base) as archive, zipfile.ZipFile(SOURCE) as donor_archive:
            check_archive(archive)
            before = fragment(archive.read('level.SCNE'))['level']
            level = copy.deepcopy(before)
            print('Closing decoded coastal seams and gaps', flush=True)
            coast = apply_coast(level, archive, extra, output_dir=BUILD / 'coast')
            print('Refining the low grey building from the original photographs', flush=True)
            building = apply_building(level, archive, extra, output_dir=BUILD / 'building')
            json.dumps({'coast': coast, 'building': building})
            changed_records, added_records = check_scene_changes(before, level)
            # Content-addressed triangle/UV buffers can legitimately be shared
            # with an older small mesh. Reuse identical members, never append
            # a second ZIP entry or replace a different payload at the same key.
            reused_resources = sorted(set(extra) & set(archive.namelist()))
            for name in reused_resources:
                if extra[name] != archive.read(name):
                    raise ValueError(f'R6 would replace a binary resource: {name}')
                del extra[name]
            if not extra or any(not isinstance(name, str) or not isinstance(raw, bytes) for name, raw in extra.items()):
                raise ValueError('Expected new named binary resources')
            scene = archive_scene(level)
            with zipfile.ZipFile(path, 'w') as target:
                target.comment = archive.comment
                for info in archive.infolist():
                    target.writestr(copy.copy(info), scene if info.filename == 'level.SCNE' else archive.read(info))
                for name, raw in sorted(extra.items()):
                    info = zipfile.ZipInfo(name, (2014, 1, 1, 17, 0, 0))
                    info.compress_type = zipfile.ZIP_STORED
                    target.writestr(info, raw)
            with zipfile.ZipFile(path) as built:
                check_archive(built)
                changed_entries = [name for name in archive.namelist() if archive.read(name) != built.read(name)]
                if changed_entries != ['level.SCNE']:
                    raise ValueError(f'Unexpected changed R5 members: {changed_entries}')
                if set(built.namelist()) != set(archive.namelist()) | set(extra):
                    raise ValueError('Candidate has missing or unexpected archive members')
                for record in added_records:
                    if record['category'] == 'Texture':
                        if level['Texture'][record['name']]['Binary'] not in built.namelist():
                            raise ValueError('A new building texture is not embedded')
                donor = fragment(donor_archive.read('level.SCNE'))['level']
                validation = validate_scene(donor, level, donor_archive, built, environment)
        floor.write_bytes(floor_raw)
        with zipfile.ZipFile(floor) as archive:
            check_archive(archive)
        artifacts = {p.name: {'bytes': p.stat().st_size, 'sha256': file_sha(p)} for p in (path, floor)}
        validation.update(
            status=STATUS, artifacts=artifacts, base_revision5_sha256=BASE_SHA,
            changed_revision5_archive_entries=changed_entries,
            changed_existing_revision5_scene_records=changed_records,
            added_scene_records=added_records,
            all_existing_revision5_records_except_two_scenery_models_preserved=True,
            all_existing_revision5_objects_and_transforms_preserved=True,
            all_existing_revision5_materials_and_textures_preserved=True,
            all_existing_revision5_binary_resources_byte_identical=True,
            paired_floor_byte_identical_to_revision5=True,
            new_binary_resources=len(extra),
            byte_identical_existing_resources_reused=reused_resources,
            shared_validator_environment_audit_revision3_sha256=environment['artifacts'][BASE.name]['sha256'],
            game_runtime_verified=False, game_directory_modified=False,
        )
        validation_path, readme = stage / 'validation.json', stage / 'README.txt'
        validation_path.write_text(json.dumps(validation, indent=2) + '\n')
        readme.write_text(
            'Venice court revision 6 candidate\n'
            'Status: STATIC_VALIDATED_GAME_UNTESTED\n\n'
            'Extract this outer ZIP to obtain the two same-slot IFF files.\n'
            'Target slot: 700. Use both files together; do not extract the IFFs.\n'
            'These preparation scripts never install a MOD or launch a game.\n\n'
            'R6 closes confirmed coastal ground gaps and simplifies the low\n'
            'grey building to the features supported by the five original\n'
            'photographs. Dimensions and unresolvable surface details remain\n'
            'design approximations. All five photographs depict one court.\n\n'
            'R5 court paint and markings, earlier palms/props/terraces, all\n'
            'existing Object transforms, shaders, materials and binary resources\n'
            'are preserved. Original basket, collision and gameplay data remain.\n\n'
            'The decoded inspection preview does not execute NBA 2K shaders.\n'
            'Game loading, native outdoor lighting, palm shading and low-angle\n'
            'floor behavior are unverified. The missing main basket buffers\n'
            'still prevent complete replacement of the indoor donor basket.\n'
        )
        package = stage / 'venice_court_revision6.zip'
        with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as packed:
            for p in (path, floor, validation_path, readme):
                info = zipfile.ZipInfo(p.name, (2026, 9, 6, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                packed.writestr(info, p.read_bytes())
        with zipfile.ZipFile(package) as packed:
            check_archive(packed, require_stored=False)
            if set(packed.namelist()) != {BASE.name, FLOOR_NAME, 'validation.json', 'README.txt'}:
                raise ValueError('Unexpected shipping file set')
            for p in (path, floor, validation_path, readme):
                if sha(packed.read(p.name)) != file_sha(p):
                    raise ValueError(f'Shipping byte verification failed: {p.name}')
        shipping = {'name': package.name, 'bytes': package.stat().st_size, 'sha256': file_sha(package)}
        report = {'status': STATUS, 'base_sha256': BASE_SHA, 'coast': coast, 'building': building,
                  'artifacts': artifacts, 'validation': validation, 'shipping_zip': shipping}
        report_json = json.dumps(report, indent=2) + '\n'
        for p in (path, floor, validation_path, readme, package):
            p.replace(OUT / p.name)
        (BUILD / 'level.SCNE').write_bytes(scene)
        (BUILD / 'revision_report.json').write_text(report_json)
    print(json.dumps({'status': STATUS, 'artifacts': artifacts, 'shipping_zip': shipping}, indent=2), flush=True)


if __name__ == '__main__':
    main()
