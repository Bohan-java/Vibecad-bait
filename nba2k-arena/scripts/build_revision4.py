"""Refine photo-supported site geometry in the verified revision 3 candidate.

No existing texture is rebaked or downscaled. Published revision 3 and donor
archives remain untouched; the candidate preserves original gameplay objects.
The output is a separate candidate, not an installation or runtime acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import zipfile

from build_revision3 import SOURCE, SOURCE_SHA, archive_scene, fragment, validate_scene
from revision4_fixtures import apply_fixtures
from revision4_props import apply_props
from revision4_terraces import apply_terraces

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'output/revision3/arena_700_int.iff'
BASE_SHA = '9bdb9f341d40cbdc22d0285ce456fca8234ee32bec1854011213ea78c9f5cc99'
FLOOR_SHA = '5f23522f783614d1572dca4f904132659f0d9ad4bd266b8148cbaacd333cf2ce'
OUT = ROOT / 'output/revision4'
BUILD = ROOT / 'build/revision4'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if sha(SOURCE.read_bytes()) != SOURCE_SHA:
        raise ValueError('Protected original donor changed')
    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    base = BASE
    if not base.is_file():
        # A fresh checkout carries the lossless shipping ZIP, not a duplicate IFF.
        with zipfile.ZipFile(ROOT / 'output/revision3/venice_court_revision3.zip') as shipping:
            raw = shipping.read(BASE.name)
        if sha(raw) != BASE_SHA:
            raise ValueError('Revision 3 package does not contain the expected IFF')
        base = BUILD / 'verified_revision3_input.iff'
        base.write_bytes(raw)
    if sha(base.read_bytes()) != BASE_SHA:
        raise ValueError('Revision 4 requires the published revision 3 candidate')
    previous = json.loads((ROOT / 'build/revision3/revision_report.json').read_text())
    if previous['artifacts'][BASE.name]['sha256'] != BASE_SHA:
        raise ValueError('Revision 3 audit belongs to another build')
    extra = {}
    with zipfile.ZipFile(base) as archive, zipfile.ZipFile(SOURCE) as donor_archive:
        before = fragment(archive.read('level.SCNE'))['level']
        level = copy.deepcopy(before)
        fixtures = apply_fixtures(level, extra)
        props = apply_props(level, extra)
        terraces = apply_terraces(level, extra, output_dir=BUILD / 'terraces')
        refinements = {'venice_v3:bins', 'venice_v3:bleachers', 'venice_v3:grass_terraces'}
        changed_records = []
        # Only these generated prototypes and the misplaced generated bin group
        # may change. Native objects, sky and existing materials stay identical.
        for category, records in before.items():
            if isinstance(records, dict):
                for name, value in records.items():
                    if level[category].get(name) != value:
                        bin_move = category == 'Object' and name == 'venice_v3:bins_2'
                        if bin_move:
                            expected = copy.deepcopy(value)
                            if expected['Matrix'][12:15] != [1110, 0, 2650]:
                                raise ValueError('Unexpected base placement for generated bin group')
                            expected['Matrix'][12] = 940
                            if level[category][name] != expected:
                                raise ValueError('Bin relocation changed more than its intended x position')
                        elif category != 'Model' or name not in refinements:
                            raise ValueError(f'Protected scene record changed: {category}/{name}')
                        changed_records.append({'category': category, 'name': name})
            elif level[category] != records:
                raise ValueError(f'Existing scene category changed: {category}')
        expected_changes = {('Model', name) for name in refinements} | {('Object', 'venice_v3:bins_2')}
        if {(entry['category'], entry['name']) for entry in changed_records} != expected_changes:
            raise ValueError('Expected decorative refinements were not all applied')
        if set(extra) & set(archive.namelist()):
            raise ValueError('Fixture resources would replace an existing archive member')
        scene = archive_scene(level)
        path = OUT / BASE.name
        temporary = path.with_suffix('.iff.tmp')
        with zipfile.ZipFile(temporary, 'w') as target:
            for info in archive.infolist():
                target.writestr(copy.copy(info), scene if info.filename == 'level.SCNE' else archive.read(info))
            for name, raw in sorted(extra.items()):
                info = zipfile.ZipInfo(name, (2014, 1, 1, 17, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                target.writestr(info, raw)
        with zipfile.ZipFile(temporary) as built:
            if built.testzip() is not None:
                raise ValueError('Output archive CRC failed')
            changed = [name for name in archive.namelist() if archive.read(name) != built.read(name)]
            if changed != ['level.SCNE']:
                raise ValueError(f'Unexpected revision 3 resource change: {changed}')
            if any(info.compress_type != zipfile.ZIP_STORED for info in built.infolist()):
                raise ValueError('Native IFF must preserve stored archive members')
            donor = fragment(donor_archive.read('level.SCNE'))['level']
            validation = validate_scene(donor, level, donor_archive, built, previous)
        temporary.replace(path)
    with zipfile.ZipFile(ROOT / 'output/revision3/venice_court_revision3.zip') as base_package:
        floor_raw = base_package.read('arena_700_int_floor.iff')
    if sha(floor_raw) != FLOOR_SHA:
        raise ValueError('Protected same-slot floor override changed')
    floor = OUT / 'arena_700_int_floor.iff'
    floor.write_bytes(floor_raw)
    artifacts = {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
                 for p in (path, floor)}
    validation.update(status='STATIC_VALIDATED_GAME_UNTESTED', artifacts=artifacts,
                      base_revision3_sha256=BASE_SHA,
                      changed_revision3_archive_entries=changed,
                      changed_existing_revision3_scene_records=changed_records,
                      existing_revision3_materials_preserved=True,
                      original_donor_object_transforms_preserved=True,
                      added_fixture_instances=len(fixtures['placements']),
                      added_fixture_triangles_per_prototype=fixtures['model']['triangles'],
                      texture_resolution_and_payloads_unchanged=True,
                      game_directory_modified=False, game_runtime_verified=False)
    report = {'status': validation['status'], 'base_sha256': BASE_SHA,
              'fixtures': fixtures, 'props': props, 'terraces': terraces,
              'artifacts': artifacts, 'validation': validation}
    (BUILD / 'revision_report.json').write_text(json.dumps(report, indent=2) + '\n')
    (OUT / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n')
    (OUT / 'README.txt').write_text(
        'Venice court revision 4 candidate\n\n'
        'Extract the two same-slot IFF files together. Target slot: 700.\n'
        'Do not extract the contents of the IFF files. Preserve your existing\n'
        'MOD files before manually using this candidate. Nothing is installed\n'
        'or launched by these preparation scripts.\n\n'
        'This version adds three double-headed coastal lamps, refines bin\n'
        'rims/liners and bleacher bracing, and rounds terrace ends while\n'
        'closing missing ground beyond them. All five photos describe one\n'
        'continuous court. Existing binary resources, native sky settings,\n'
        'court and palms remain unchanged. New prop textures are additional.\n'
        'Original baskets, animation resources and collisions are preserved.\n'
        'Static validation passed. NBA 2K runtime appearance is unverified.\n')
    package = OUT / 'venice_court_revision4.zip'
    with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        for p in (path, floor, OUT / 'validation.json', OUT / 'README.txt'):
            info = zipfile.ZipInfo(p.name, (2026, 9, 6, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, p.read_bytes())
    with zipfile.ZipFile(package) as packed:
        if packed.testzip() is not None:
            raise ValueError('Shipping ZIP CRC failed')
        for name, spec in artifacts.items():
            if sha(packed.read(name)) != spec['sha256']:
                raise ValueError(f'Shipping ZIP byte verification failed: {name}')
    print(json.dumps({'status': validation['status'], 'artifacts': artifacts,
                      'shipping_zip': {'bytes': package.stat().st_size,
                                       'sha256': sha(package.read_bytes())}}, indent=2), flush=True)


if __name__ == '__main__':
    main()
