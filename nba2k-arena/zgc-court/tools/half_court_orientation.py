"""Put the painted end at the Blacktop half-court end observed in gameplay.

Source photography stays in its existing coordinate system. Only native static
instances and their seating anchors rotate. Native dynamic baskets, court
identities, lighting and all mesh/texture payloads remain untouched.
"""
from __future__ import annotations
import copy

IDENTITY = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
HALF_TURN = [-1,0,0,0, 0,1,0,0, 0,0,-1,0, 0,0,0,1]


def orientation_degrees(level):
    objects = [o for o in level['Object'].values() if o.get('Type') == 'OBJECT']
    assert objects and all(o.get('Target', '').startswith('zgc_r03:') for o in objects)
    matrices = {tuple(o.get('Matrix', IDENTITY)) for o in objects}
    assert len(matrices) == 1, 'Mixed custom world orientations'
    matrix = next(iter(matrices))
    if matrix == tuple(IDENTITY):
        return 0
    assert matrix == tuple(HALF_TURN), 'Unexpected native world transform'
    return 180


def apply_orientation(level):
    from r12_seating import ROLE_RE
    already = orientation_degrees(level) == 180
    before = copy.deepcopy(level)
    static_count = marker_count = 0
    for name, obj in level['Object'].items():
        if obj.get('Type') == 'OBJECT':
            assert 'Transform' not in obj, 'Expected baked static instance'
            obj['Matrix'] = list(HALF_TURN)
            static_count += 1
        elif ROLE_RE.fullmatch(name):
            assert obj['Type'] == 'MARKER'
            if not already:
                x, y, z = obj['Translate']
                assert obj['Rotate'] == [0., -1.57079637, 0.]
                obj['Translate'] = [-x, y, -z]
                obj['Rotate'] = [0., 1.57079637, 0.]
            assert obj['Rotate'] == [0., 1.57079637, 0.]
            marker_count += 1
    assert marker_count == 44
    assert orientation_degrees(level) == 180
    for key in before:
        if key != 'Object':
            assert level[key] == before[key], key
    untouched = [name for name, obj in before['Object'].items()
                 if obj.get('Type') != 'OBJECT' and not ROLE_RE.fullmatch(name)]
    assert all(level['Object'][name] == before['Object'][name] for name in untouched)
    return {'revision': 'R12.1', 'world_yaw_degrees': 180,
            'static_instances_rotated': static_count, 'seating_markers_rotated': marker_count,
            'native_technical_markers_unchanged': len(untouched),
            'painted_half_native_z': 'positive', 'gray_half_native_z': 'negative',
            'painted_rim_center_game_cm': [0., 304.8, 1272.54],
            'reason': 'User confirms Blacktop half-court selects the former gray +Z end. Rotate the photographic scene to that existing end instead of guessing an engine selector.',
            'source_blender_coordinates_unchanged': True,
            'native_baskets_and_gameplay_anchors_unchanged': True,
            'mesh_texture_material_and_lighting_data_unchanged': True,
            'matrix_determinant': 1, 'already_applied': already, 'game_tested': False}


def update_report(report, level, orientation):
    from r12_seating import ROLE_RE
    report['revision'] = 'R12.1'
    report['half_court_orientation'] = orientation
    report['game_tested'] = False
    report['game_visibility'] = 'pending'
    report['source_feedback'] = 'User reports R12 Blacktop half-court selects the gray end; place the yellow/black painted half at that existing end.'
    report['last_game_confirmed'] = {'revision': 'R12', 'visibility': 'half_court_uses_gray_end',
                                   'replay_glass': 'not_confirmed_by_latest_feedback'}
    change = 'Rotate all custom static scene instances 180 degrees and move/turn bench role anchors with their chairs, placing the yellow/black court at the existing Blacktop half-court end. Preserve both native dynamic baskets, meshes, textures, lighting and gameplay anchors.'
    if change not in report['changes']:
        report['changes'].append(change)
    seats = report['bench_seating']
    seats['installed_markers'] = {k: copy.deepcopy(v) for k, v in level['Object'].items() if ROLE_RE.fullmatch(k)}
    for row in seats['layout']:
        row['game_position_cm'] = level['Object'][row['marker']]['Translate'][:]
    seats['world_yaw_degrees'] = 180
    seats['only_modified_fields'] = 'Native role Translate and yaw follow the 180-degree photographic-world rotation; all 44 chairs and anchors stay aligned. Source coordinates in layout remain photographic coordinates.'
