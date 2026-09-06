"""Add light-grey court paint to the SHA-verified revision 4 candidate.

Only the existing floor Model may change; new Material/Texture records and
content-addressed resources are appended. Existing R4, paired floor, donor
binaries and gameplay records remain untouched. This never installs a MOD.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from build_revision3 import SOURCE, SOURCE_SHA, archive_scene, fragment, validate_scene
from revision5_court_paint import apply_paint


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'output/revision4/arena_700_int.iff'
BASE_PACKAGE = ROOT / 'output/revision4/venice_court_revision4.zip'
BASE_SHA = 'a080b341e194a8f670ad0d26e524e64dbd6ac6d88e51173e32be54d803ea96bd'
FLOOR_NAME = 'arena_700_int_floor.iff'
FLOOR_SHA = '5f23522f783614d1572dca4f904132659f0d9ad4bd266b8148cbaacd333cf2ce'
OUT = ROOT / 'output/revision5'
BUILD = ROOT / 'build/revision5'
STATUS = 'STATIC_VALIDATED_GAME_UNTESTED'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verified_main_input():
    if BASE.is_file():
        if file_sha(BASE) != BASE_SHA:
            raise ValueError('Revision 5 requires the verified revision 4 IFF')
        return BASE
    # Fresh checkouts carry the lossless shipping ZIP instead of a duplicate
    # >100 MB IFF. Extract only the verified container into this build directory.
    with zipfile.ZipFile(BASE_PACKAGE) as package:
        if len(package.namelist()) != len(set(package.namelist())):
            raise ValueError('Revision 4 shipping ZIP has duplicate names')
        raw = package.read(BASE.name)
    if sha(raw) != BASE_SHA:
        raise ValueError('Revision 4 shipping ZIP contains a different main IFF')
    path = BUILD / 'verified_revision4_input.iff'
    path.write_bytes(raw)
    return path


def verified_base_audits():
    path = ROOT / 'output/revision4/validation.json'
    if path.is_file():
        base = json.loads(path.read_text())
    else:
        with zipfile.ZipFile(BASE_PACKAGE) as package:
            base = json.loads(package.read('validation.json'))
    if base['artifacts'][BASE.name]['sha256'] != BASE_SHA:
        raise ValueError('Revision 4 validation belongs to a different main IFF')
    if base['artifacts'][FLOOR_NAME]['sha256'] != FLOOR_SHA:
        raise ValueError('Revision 4 validation belongs to a different paired floor')
    # validate_scene has no fixed R3 Object/MARKER count, but it requires the
    # original environment audit to verify hidden LODs and crowd-card indices.
    # R4's report does not contain that table. Supply the explicitly linked R3
    # report instead of skipping or weakening those checks.
    previous = json.loads((ROOT / 'build/revision3/revision_report.json').read_text())
    if previous['artifacts'][BASE.name]['sha256'] != base['base_revision3_sha256']:
        raise ValueError('Revision 3 environment audit is not the base of this R4')
    if not previous.get('environment', {}).get('hidden_models'):
        raise ValueError('Missing original hidden-model environment audit')
    if not previous['environment'].get('crowd_render_change'):
        raise ValueError('Missing original crowd render audit')
    return base, previous


def verified_paired_floor():
    path = BASE.parent / FLOOR_NAME
    if path.is_file():
        raw = path.read_bytes()
    else:
        with zipfile.ZipFile(BASE_PACKAGE) as package:
            raw = package.read(FLOOR_NAME)
    if sha(raw) != FLOOR_SHA:
        raise ValueError('Protected R4 same-slot floor override changed')
    return raw


def check_scene_changes(before, level):
    """Only one existing floor Model changes; add only Material/Texture keys."""
    if set(level) != set(before):
        raise ValueError('Paint must not add or remove scene categories')
    floor_name = before['Object']['__floor00__']['Target']
    if floor_name not in before['Model']:
        raise ValueError('Original floor Object does not resolve to a Model')
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
                if category != 'Model' or name != floor_name:
                    raise ValueError(f'Protected R4 scene record changed: {category}/{name}')
                changed.append({'category': category, 'name': name})
        for name in sorted(set(current) - set(records)):
            if category not in ('Material', 'Texture'):
                raise ValueError(f'Paint added an unexpected scene record: {category}/{name}')
            added.append({'category': category, 'name': name})
    if changed != [{'category': 'Model', 'name': floor_name}]:
        raise ValueError('Expected exactly the existing floor Model to change')
    return floor_name, changed, added


def check_archive(archive, *, require_stored=True):
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError('Archive contains duplicate member names')
    if require_stored and any(info.compress_type != zipfile.ZIP_STORED for info in archive.infolist()):
        raise ValueError('Native IFF members must remain ZIP_STORED')
    if archive.testzip() is not None:
        raise ValueError('Archive CRC validation failed')


def main():
    if not __debug__:
        raise RuntimeError('Run without -O: the shared native validator uses assertions')
    if file_sha(SOURCE) != SOURCE_SHA:
        raise ValueError('Protected original donor changed')
    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    base = verified_main_input()
    base_validation, environment_report = verified_base_audits()
    floor_raw = verified_paired_floor()
    extra = {}
    # Validate the entire candidate and its shipping ZIP before replacing any
    # previous R5 outputs. R3/R4 files are read-only throughout this process.
    with tempfile.TemporaryDirectory(prefix='revision5_candidate_', dir=BUILD) as directory:
        stage = Path(directory)
        path, floor = stage / BASE.name, stage / FLOOR_NAME
        with zipfile.ZipFile(base) as archive, zipfile.ZipFile(SOURCE) as donor_archive:
            check_archive(archive)
            before = fragment(archive.read('level.SCNE'))['level']
            level = copy.deepcopy(before)
            print('Adding native light-grey center/key paint to verified R4', flush=True)
            # The paint module validates old VB/IB/Prim prefixes and all other
            # floor Model fields, including quantized geometry and overlap.
            paint = apply_paint(level, archive, extra, output_dir=BUILD / 'paint')
            json.dumps(paint)  # Fail before packaging if its audit is not JSON.
            floor_name, changed_records, added_records = check_scene_changes(before, level)
            if set(extra) & set(archive.namelist()):
                raise ValueError('Paint resources would replace an existing R4 archive member')
            if not extra or any(not isinstance(name, str) or not isinstance(raw, bytes)
                                for name, raw in extra.items()):
                raise ValueError('Expected additional named binary paint resources')
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
                changed = [name for name in archive.namelist() if archive.read(name) != built.read(name)]
                if changed != ['level.SCNE']:
                    raise ValueError(f'Unexpected changed R4 archive members: {changed}')
                if set(built.namelist()) != set(archive.namelist()) | set(extra):
                    raise ValueError('Output archive has missing or unexpected members')
                for item in added_records:
                    if item['category'] == 'Texture':
                        binary = level['Texture'][item['name']]['Binary']
                        if binary not in built.namelist():
                            raise ValueError(f'New paint texture is not embedded: {binary}')
                donor = fragment(donor_archive.read('level.SCNE'))['level']
                validation = validate_scene(donor, level, donor_archive, built, environment_report)
        floor.write_bytes(floor_raw)
        with zipfile.ZipFile(floor) as paired:
            check_archive(paired)
        artifacts = {p.name: {'bytes': p.stat().st_size, 'sha256': file_sha(p)} for p in (path, floor)}
        validation.update(
            status=STATUS, artifacts=artifacts, base_revision4_sha256=BASE_SHA,
            changed_revision4_archive_entries=changed,
            changed_existing_revision4_scene_records=changed_records,
            added_scene_records=added_records, modified_floor_model=floor_name,
            all_existing_revision4_records_except_floor_model_preserved=True,
            all_existing_revision4_materials_and_textures_preserved=True,
            all_existing_revision4_objects_and_transforms_preserved=True,
            all_existing_revision4_binary_resources_byte_identical=True,
            paired_floor_byte_identical_to_revision4=True,
            original_donor_binary_resources_and_gameplay_preserved=True,
            shared_validator_environment_audit_revision3_sha256=base_validation['base_revision3_sha256'],
            new_binary_resources=len(extra), game_directory_modified=False, game_runtime_verified=False,
        )
        validation_path, readme = stage / 'validation.json', stage / 'README.txt'
        validation_path.write_text(json.dumps(validation, indent=2) + '\n')
        readme.write_text(
            'Venice court revision 5 candidate\n'
            'Status: STATIC_VALIDATED_GAME_UNTESTED (GAME_UNTESTED)\n\n'
            'Extract this outer ZIP to obtain the two same-slot IFF files.\n'
            'Target slot: 700. Use both IFF files from this package together.\n'
            'Do not extract the contents of the IFF files. These preparation\n'
            'scripts do not install a MOD, modify the game folder or launch it.\n\n'
            'Revision 5 adds light-grey paint inside the center circle and\n'
            'the lane rectangles joined to their free-throw semicircles.\n'
            'Existing white lines, the 16 ft lanes and 6 ft circle radii stay\n'
            'unchanged. The five original photos show one court; its paint\n'
            'pattern is adapted to the existing court dimensions.\n\n'
            'All revision 4 work is retained: open coastal scenery, palms,\n'
            'double-headed lamps, refined bins and silver bleachers, curved\n'
            'terrace ends and surrounding ground. Existing textures are not\n'
            'rebaked or downscaled. The paired floor IFF is byte-identical\n'
            'to revision 4. Original baskets, animations, collisions and\n'
            'gameplay objects remain preserved.\n\n'
            'Static validation passed. NBA 2K loading, exposure, paint color\n'
            'and runtime appearance remain unverified. This is a candidate.\n'
        )
        package = stage / 'venice_court_revision5.zip'
        with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for p in (path, floor, validation_path, readme):
                info = zipfile.ZipInfo(p.name, (2026, 9, 6, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                target.writestr(info, p.read_bytes())
        with zipfile.ZipFile(package) as packed:
            check_archive(packed, require_stored=False)
            if set(packed.namelist()) != {BASE.name, FLOOR_NAME, 'validation.json', 'README.txt'}:
                raise ValueError('Shipping ZIP has an unexpected file set')
            for p in (path, floor, validation_path, readme):
                if sha(packed.read(p.name)) != file_sha(p):
                    raise ValueError(f'Shipping ZIP byte verification failed: {p.name}')
        shipping = {'name': package.name, 'bytes': package.stat().st_size, 'sha256': file_sha(package)}
        report = {'status': STATUS, 'base_sha256': BASE_SHA, 'paint': paint,
                  'artifacts': artifacts, 'validation': validation, 'shipping_zip': shipping}
        report_json = json.dumps(report, indent=2) + '\n'
        for p in (path, floor, validation_path, readme, package):
            p.replace(OUT / p.name)
        (BUILD / 'level.SCNE').write_bytes(scene)
        (BUILD / 'revision_report.json').write_text(report_json)
    print(json.dumps({'status': STATUS, 'base_sha256': BASE_SHA,
                      'artifacts': artifacts, 'shipping_zip': shipping}, indent=2), flush=True)


if __name__ == '__main__':
    main()
