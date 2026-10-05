"""Evidence-based NBA bench-marker transplant; no package is written here.

The local untouched arena_020 donor supplies the exact 44 engine marker names,
Type, Rotate and ground-height conventions.  Rucker and the shipped R11 package
have none of these markers.  Missing role anchors are a supported explanation
for coincident substitutes, not a proven Blacktop runtime diagnosis.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import re
import zipfile

from iff_codec import load_scne, decode_attribute

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT.parent / 'donor/original/arena_020_int_original.iff'
DONOR = ROOT.parent / '洛克公园/arena_blacktop_ext.iff'
REFERENCE_SCNE_SHA256 = '8aaf539ce26d77f6b1511075b30bb7baa18c3430469b20a408b93303485e15b6'
ROLE_RE = re.compile(r'^NBA(?:HOME|AWAY)(?:PLAYER[1-8]|HEADCOACH|PLAYERDEVCOACH|ASSTCOACH[1-9]|HEADPHYSIO|TRAINER[12])$')
SEAT_Y = 8.60
SPACING = .60
CENTRE_GAP_HALF = .78
# One straight row, two 22-place groups.  The most frequently used head coach,
# first assistants and players stay together; overflow staff occupy the ends.
ORDER = ('HEADCOACH', 'ASSTCOACH1', 'ASSTCOACH2', 'ASSTCOACH3',
         *(f'PLAYER{i}' for i in range(1, 9)), 'PLAYERDEVCOACH',
         *(f'ASSTCOACH{i}' for i in range(4, 10)), 'HEADPHYSIO', 'TRAINER1', 'TRAINER2')


def reference_markers():
    with zipfile.ZipFile(REFERENCE) as archive:
        raw = archive.read('level.SCNE')
    if hashlib.sha256(raw).hexdigest() != REFERENCE_SCNE_SHA256:
        raise RuntimeError('Reference arena changed; re-audit bench marker schema')
    objects = load_scne(raw)['level']['Object']
    markers = {k: v for k, v in objects.items() if ROLE_RE.fullmatch(k)}
    assert len(markers) == 44
    for name, obj in markers.items():
        assert set(obj) == {'Type', 'Rotate', 'Translate'}, name
        assert obj['Type'] == 'MARKER', name
        assert obj['Rotate'] == [0., -1.57079637, 0.], name
        assert obj['Translate'][1] == 0., name
    return markers


def seat_layout():
    rows = []
    for team, sign in (('HOME', -1), ('AWAY', 1)):
        for index, role in enumerate(ORDER):
            x = round(sign * (CENTRE_GAP_HALF + index * SPACING), 6)
            rows.append({'marker': f'NBA{team}{role}', 'team': team,
                         'role': role, 'source_position_m': [x, SEAT_Y, 0.],
                         'game_position_cm': [SEAT_Y * 100., 0., x * 100.]})
    assert len(rows) == len({r['marker'] for r in rows}) == 44
    assert len({tuple(r['game_position_cm']) for r in rows}) == 44
    return rows


def apply_native_markers(level):
    """Mutate only 44 Object entries in an already decoded native level.

    Call before writing level.SCNE during repair_iff.py.  Keep ground Y=0 and
    the donor's existing -pi/2 yaw, which faces from game +X toward the court.
    Blender-to-game is (Y, Z, X)*100, hence this faces source -Y.
    """
    reference = reference_markers()
    before = copy.deepcopy(level['Object'])
    rows = seat_layout()
    for row in rows:
        marker = copy.deepcopy(reference[row['marker']])
        marker['Translate'] = row['game_position_cm']
        level['Object'][row['marker']] = marker
    changed = [k for k, v in before.items() if not ROLE_RE.fullmatch(k) and level['Object'].get(k) != v]
    if changed:
        raise RuntimeError('Non-seating Object unexpectedly changed: ' + str(changed))
    installed = {k: v for k, v in level['Object'].items() if ROLE_RE.fullmatch(k)}
    assert set(installed) == set(reference)
    assert len({tuple(v['Translate']) for v in installed.values()}) == 44
    return {'status': 'native_schema_and_unique_positions_verified', 'game_tested': False,
            'reference': str(REFERENCE), 'reference_scne_sha256': REFERENCE_SCNE_SHA256,
            'original_reference_markers': reference,
            'installed_markers': installed, 'layout': rows,
            'count': 44, 'seat_spacing_m': SPACING, 'seat_source_y_m': SEAT_Y,
            'group_centres_gap_m': CENTRE_GAP_HALF * 2,
            'only_modified_fields': 'Clone existing native role marker schema; change Translate X/Z to this court seating row. Keep ground height and Rotate unchanged.',
            'runtime_limit': 'Blacktop role-marker lookup and seated animation alignment still require one in-game check. No player, coach or crowd population resource is modified.'}


def investigate(current=None):
    current = Path(current) if current else ROOT / 'output/arena_700_int.iff'
    resources = ['crowd.SCNE', 'crowd.CrowdData', 'crowd_aisles_paths.StadiumPath',
                 'crowd_aisles_tunnel_paths.StadiumPath', 'crowd_aisles_vendor_paths.StadiumPath',
                 'crowd_rows_paths.StadiumPath', 'crowd_rows_strafe_only_paths.StadiumPath',
                 'crowd_rows_strafe_paths.StadiumPath', 'crowd_rows_walk_paths.StadiumPath']
    packages = {}
    for label, path in [('rucker_donor', DONOR), ('current', current)]:
        with zipfile.ZipFile(path) as archive:
            level = load_scne(archive.read('level.SCNE'))['level']
            roles = {k: v for k, v in level['Object'].items() if ROLE_RE.fullmatch(k)}
            hashes = {name: {'bytes': len(archive.read(name)),
                            'sha256': hashlib.sha256(archive.read(name)).hexdigest()} for name in resources}
            # Crowd vertex/pixel streams are crowd seats, not named team roles.
            crowd = load_scne(archive.read('crowd.SCNE'))['crowd']
            for descriptor in crowd['Texture'].values():
                name = descriptor['Binary']
                if name not in archive.NameToInfo:
                    name = name.removesuffix('.gz') + '.bin'
                raw = archive.read(name)
                hashes[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            packages[label] = {'path': str(path), 'role_marker_count': len(roles),
                               'role_markers': roles, 'crowd_resources': hashes}
    evidence = {'revision': 'R12', 'packages': packages, 'reference': str(REFERENCE),
                'reference_scne_sha256': REFERENCE_SCNE_SHA256, 'reference_markers': reference_markers(),
                'crowd_resources_identical_to_donor': packages['rucker_donor']['crowd_resources'] == packages['current']['crowd_resources'],
                'finding': 'R11 inherited a park donor that has zero named NBA bench/coach role anchors. Native arena_020 supplies 44 distinct ground-height NBAHOME/NBAAWAY role markers. Missing match anchors are the strongest inspected candidate for fallback overlap; it is not yet a proven runtime cause.',
                'planned_layout': seat_layout(),
                'no_changes_to': ['crowd resources', 'baskets', 'floor', 'lighting', 'game installation'],
                'game_tested': False}
    output = ROOT / 'validation/r12-seating-evidence.json'
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf8')
    return evidence


def audit_archive(path=None, source_labels=None):
    """Validate the actual final IFF roles and native chair vertex locations."""
    import numpy as np
    path = Path(path) if path else ROOT / 'output/arena_700_int.iff'
    labels = source_labels or json.loads((ROOT / 'validation/native-source-build.json').read_text(encoding='utf8'))
    expected = seat_layout()
    originals = reference_markers()
    with zipfile.ZipFile(path) as archive:
        level = load_scne(archive.read('level.SCNE'))['level']
        objects = level['Object']
        identity = np.eye(4)
        half_turn = np.diag([-1., 1., -1., 1.])
        scene_matrices = [np.asarray(obj.get('Matrix', identity.ravel()), dtype=float).reshape(4, 4)
                          for obj in objects.values() if obj.get('Type') == 'OBJECT']
        assert scene_matrices, 'Missing native static scene instances'
        if all(np.allclose(matrix, identity) for matrix in scene_matrices):
            orientation = identity
            rotated = False
        elif all(np.allclose(matrix, half_turn) for matrix in scene_matrices):
            orientation = half_turn
            rotated = True
        else:
            raise AssertionError('Unexpected or mixed native static scene orientation')
        role_names = {k for k in objects if ROLE_RE.fullmatch(k)}
        assert role_names == set(originals), 'Incomplete native bench role set'
        for row in expected:
            actual = objects[row['marker']]
            wanted = copy.deepcopy(originals[row['marker']])
            wanted['Translate'] = (np.array([*row['game_position_cm'], 1.]) @ orientation)[:3].tolist()
            if rotated:
                wanted['Rotate'] = [0., 1.57079637, 0.]
            assert actual == wanted, row['marker']
        parts = [part for part in labels['models'] if part['source_object'].startswith('R12 right bench ')]
        assert {part['source_object'] for part in parts} == {
            'R12 right bench frames', 'R12 right bench pads',
            'R12 right bench feet', 'R12 right bench hardware'}, 'Missing native chair geometry'
        vertices = []
        for part in parts:
            model = level['Model'][part['model']]
            p = decode_attribute(archive, model, 'POSITION0')[:, :3]
            instances = [obj for obj in objects.values()
                         if obj.get('Type') == 'OBJECT' and obj.get('Target') == part['model']]
            assert len(instances) == 1, 'Expected one independent native chair instance'
            matrix = np.asarray(instances[0].get('Matrix', identity.ravel()), dtype=float).reshape(4, 4)
            # Check the actual game instance first, then express its result in
            # the unchanged photographic source coordinate system for bounds.
            world = np.column_stack((p, np.ones(len(p)))) @ matrix
            source_game = (world @ np.linalg.inv(orientation))[:, :3]
            vertices.append(source_game[:, [2, 0, 1]] / 100.)
        vertices = np.vstack(vertices)
        centers = np.array([row['source_position_m'][0] for row in expected])
        nearest = np.argmin(np.abs(vertices[:, 0, None] - centers[None, :]), axis=1)
        chairs = []
        for i, row in enumerate(expected):
            v = vertices[nearest == i]
            assert len(v) > 100, 'Seat has no independently aligned geometry: ' + row['marker']
            mn, mx = v.min(axis=0), v.max(axis=0)
            assert abs((mn[0] + mx[0]) / 2. - centers[i]) < .002
            assert abs((mn[1] + mx[1]) / 2. - SEAT_Y) < .002
            assert -.002 <= mn[2] <= .002 and .89 < mx[2] < .92
            assert mn[1] > 7.62 and mx[1] < 9.17
            chairs.append({'marker': row['marker'], 'vertex_count': len(v),
                           'source_bounds_m': {'min': mn.tolist(), 'max': mx.tolist()}})
    report = {'revision': 'R12.1' if rotated else 'R12', 'status': 'passed', 'game_tested': False,
              'half_court_orientation_degrees': 180 if rotated else 0,
              'chair_bounds_coordinate_system': 'photographic_source_after_actual_instance_transform_and_inverse_orientation',
              'marker_count': len(expected), 'independent_chair_count': len(chairs),
              'native_model_count': len(parts), 'markers_match_local_original_schema': True,
              'all_positions_distinct': True, 'chair_role_alignment_verified': True,
              'chair_geometry': chairs,
              'runtime_limit': 'Offline validation confirms 44 native role anchors and aligned chairs. Blacktop role selection and seated animation height remain unverified until game testing.'}
    (ROOT / 'validation/r12-seating-native-current.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    return report


if __name__ == '__main__':
    result = investigate()
    print(json.dumps({'role_counts': {k: v['role_marker_count'] for k, v in result['packages'].items()},
                      'crowd_identical': result['crowd_resources_identical_to_donor'],
                      'reference_roles': len(result['reference_markers']),
                      'layout_count': len(result['planned_layout'])}, ensure_ascii=False))
