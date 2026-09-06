"""Open the audited Clutch Time donor without moving its gameplay skeleton.

This is a render-only, donor-specific pass. A whitelist of inspected OBJECT
targets loses its visible triangles by using a new, same-sized all-zero index
buffer. Thus every LOD is degenerate in every rendering pass, while OBJECTs,
transforms, original vertex/index resources and compiled shaders survive.
No undocumented visibility flag, zero alpha or empty-model convention is used.

Lighting changes use fields already present in the original donor: its dormant
midday TIME_OF_DAY sky and Sun are enabled, and its orange luxury-box spots are
disabled. This does not rebake or validate the existing indoor lightmaps/IBLs.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import zlib


MASTER = 'arena_clutchtime_int_master@'
LAYOUT = MASTER + 'arena_clutchtime_int_shared_layout@GameObjects@'
LIGHTING = MASTER + 'arena_triplethreat_int_lighting@GameObjects@'

# The group and final mesh names below were read from this donor's level.SCNE;
# matching a loose word such as "wall", "light" or "crowd" is never sufficient.
HIDDEN_GROUP_MESHES = {
    'ceiling': frozenset('clutchtime_ceiling_' + x + '_low' for x in ('a', 'b', 'c', 'ribs')),
    'ceiling_panels': frozenset('clutchtime_ceilingpanel_' + x + '_low' for x in 'abcdef'),
    'ceiling_panelslights': frozenset('clutchtime_ceilingpanellight_' + x + '_low' for x in 'abcdefghi'),
    'walls': frozenset('clutchtime_wall_' + x + '_low' for x in ('a', 'b', 'c', 'd', 'e', 'f', 'corner')),
    'scorecube': frozenset('clutchtime_scorecube_' + x + '_low' for x in
                           ('screensupport', 'spiral', 'supportring', 'screen', 'supportpipes')),
    'mural_lights': frozenset(('light_stage_spotlight_low', 'lighting_suspendedtrack_metalb_low')),
    'balcony_lights': frozenset(('light_ceilinga_round_low',)),
    'doors': frozenset(('light_switch_double_low', 'box_electrical_commerciala_low',
                        'electircal_outlet_industrial', 'eletrical_oulet_common',
                        'door_interiorwindowb_rightdbl', 'doorframe_interiorhingeless_double_low',
                        'sign_exit_generic', 'door_interiorwindowb_leftdbl')),
    'balcony': frozenset(('clutchtime_balcony_a_low', 'clutchtime_balcony_b_low',
                          'clutchtime_balcony_c_low', 'clutchtime_balcony_railing_low',
                          'clutchtime_ceiling_balcony_low', 'clutchtime_balcony_column_low')),
    'balcony_chairs': frozenset(('chair_arenacrowd_seatbackcushion_low',)),
    'mural': frozenset(('clutchtime_mural_handrail_low', 'clutchtime_mural_balcony_low',
                        'clutchtime_mural_floor_low')),
    'stands': frozenset(('clutchtime_stair_3step_low', 'clutchtime_stair_4step_low',
                         'clutchtime_stands_tunnel_low', 'clutchtime_crowd_seating_low',
                         'clutchtime_stands_tiers_low')),
    'Prototype_arena_curtains_prototype@Prototype_arena_curtains_prototype_0':
        frozenset(('curtain100x20_arena_straight500c',)),
    'Prototype_arena_curtains_prototype@Prototype_arena':
        frozenset(('curtain100x20_arena_straight500c',)),
    'clutchtimecurtainstunnels1@Prototype_arena_curtains_prototype_1':
        frozenset(('curtain100x20_arena_straight300c', 'curtain100x20_arena_straight400c')),
    'clutchtimecurtainstunnels1@Prototype_arena_curtains_prototype_2':
        frozenset(('curtain100x20_arena_straight300c', 'curtain100x20_arena_straight400c')),
}
EXACT_HIDDEN_OBJECTS = {
    MASTER + 'GameObjects@clutchtime_mural_wall:clutchtime_mural_wall_low': 'mural_enclosure',
    MASTER + 'GameObjects@dorna@clutchtime_court_dornaled:clutchtime_court_dornaled_low': 'court_led_ribbon',
    # This is the inspected 16-vertex exterior apron with a court-shaped hole.
    # Leaving it at y~0.1 would occlude the new promenade and retain baked indoor
    # surface lighting. New world-mapped outdoor paving replaces its rendering.
    MASTER + 'GameObjects@apron@clutchtime_floor_apron:clutchtime_floor_apron_low': 'exterior_apron',
}
EXACT_CROSS_GROUP_TARGETS = {
    # This original donor instance lives under "stands" but references a
    # ceiling-panel mesh. Its exact name/target pair was inspected separately.
    LAYOUT + 'stands@clutchtime_ceilingpanel_f_6:clutchtime_ceilingpanel_f_low':
        (LAYOUT + 'ceiling_panels@clutchtime_ceilingpanel_f:clutchtime_ceilingpanel_f_low', 'ceiling_panels'),
}
STAIR_LIGHT_MATERIAL = 'clutchtime_stair_3step:light_mat'
DORNA_MESHES = frozenset(('clutchtime_court_dorna_low', 'clutchtime_court_dornacorner_low',
                          'clutchtime_court_dornaend_low', 'clutchtime_court_dornaled_low'))


def _scene(raw):
    raw = raw.strip()
    return json.loads(raw if raw.startswith(b'{') else b'{' + raw + b'}')


def _identity(name):
    if not name.startswith(LAYOUT):
        return None, None
    relative = name[len(LAYOUT):]
    if '@' not in relative or ':' not in relative:
        return None, None
    group, leaf = relative.rsplit('@', 1)
    return group, leaf.rsplit(':', 1)[-1]


def _hidden_reason(name, obj):
    if obj.get('Type') != 'OBJECT':
        return None
    if name in EXACT_HIDDEN_OBJECTS:
        return EXACT_HIDDEN_OBJECTS[name] if obj.get('Target') == name else None
    if name in EXACT_CROSS_GROUP_TARGETS:
        target, reason = EXACT_CROSS_GROUP_TARGETS[name]
        return reason if obj.get('Target') == target else None
    dorna_prefix = MASTER + 'GameObjects@dorna@'
    if name.startswith(dorna_prefix) and obj.get('Target', '').startswith(dorna_prefix):
        mesh = name.rsplit(':', 1)[-1]
        if mesh in DORNA_MESHES and obj['Target'].rsplit(':', 1)[-1] == mesh:
            return 'court_dorna_ribbon_and_padding'
    group, mesh = _identity(name)
    target_group, target_mesh = _identity(obj.get('Target', ''))
    allowed = HIDDEN_GROUP_MESHES.get(group, ())
    # Repeated curtain objects point back to the first inspected group/model.
    curtain_target = group in HIDDEN_GROUP_MESHES and group.startswith(
        ('Prototype_arena_curtains_prototype@', 'clutchtimecurtainstunnels1@'))
    compatible_group = target_group == group or (
        curtain_target and target_group in HIDDEN_GROUP_MESHES and
        target_mesh in HIDDEN_GROUP_MESHES[target_group])
    if mesh in allowed and target_mesh == mesh and compatible_group:
        return group
    return None


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _degenerate_model(name, model):
    """Replace all LOD index storage; never collapse the source vertex mesh."""
    buffer = model.get('IndexBuffer', {})
    width = {'R16_UINT': 2, 'R32_UINT': 4}.get(buffer.get('Format'))
    size = buffer.get('Size')
    if width is None or not isinstance(size, int) or size <= 0 or size % width:
        raise ValueError('Unsupported index buffer for audited target: ' + name)
    topology = None
    for prim in model.get('Prim', ()):
        topology = prim.get('Type', topology)
        if topology != 'TRIANGLE_LIST':
            raise ValueError('Refusing non-triangle visibility change: ' + name)
    if not model.get('Prim'):
        raise ValueError('Audited target has no primitive records: ' + name)
    raw = bytes(size)
    binary = 'IndexBuffer.venice_v3_hidden.' + _sha(name.encode())[:16] + '.bin'
    replacement = deepcopy(model)
    replacement['IndexBuffer'] = {'Format': buffer['Format'], 'Size': size, 'Binary': binary}
    replacement['IndexBufferCrc32'] = zlib.crc32(raw) & 0xffffffff
    return replacement, binary, raw


def apply_environment(level, donor_zip, extra):
    """Mutate a working scene/extra-resource dict and return a full audit trail.

    ``donor_zip`` is an open ZipFile for the protected original donor, never an
    output package. All validation and new data are prepared before committing
    changes. Unknown objects, non-OBJECT anchors and non-whitelisted models are
    retained. No file is written by this function.
    """
    donor = _scene(donor_zip.read('level.SCNE'))['level']
    hidden = {}
    for name, obj in donor['Object'].items():
        reason = _hidden_reason(name, obj)
        if reason is None:
            continue
        if level['Object'].get(name) != obj:
            raise ValueError('Audited object differs from donor: ' + name)
        target = obj['Target']
        if target not in donor['Model'] or level['Model'].get(target) != donor['Model'][target]:
            raise ValueError('Audited model differs from donor: ' + target)
        hidden.setdefault(target, []).append((name, reason))
    if not hidden:
        raise ValueError('No audited Clutch Time environment targets found')
    # An unexpected instance sharing an audited model would otherwise vanish.
    allowed_objects = {n for objects in hidden.values() for n, _ in objects}
    for name, obj in level['Object'].items():
        if obj.get('Target') in hidden and name not in allowed_objects:
            raise ValueError('Unknown object shares a hidden model: ' + name)

    replacements, resources, model_report, object_report = {}, {}, [], []
    names_in_archive = set(donor_zip.namelist())
    selections = [(target, target, objects) for target, objects in sorted(hidden.items())]
    for target, original_target, objects in selections:
        original = donor['Model'][original_target]
        replacement, binary, raw = _degenerate_model(target, original)
        if binary in extra or binary in names_in_archive:
            raise ValueError('Environment output resource already exists: ' + binary)
        replacements[target], resources[binary] = replacement, raw
        source_binary = original['IndexBuffer']['Binary']
        model_report.append({
            'target': target, 'original_target': original_target, 'original_model': deepcopy(original),
            'original_index_resource': source_binary,
            'original_resource_preserved': True,
            'original_resource_location': 'donor_archive' if source_binary in names_in_archive else 'external_game_reference',
            'original_resource_sha256': _sha(donor_zip.read(source_binary)) if source_binary in names_in_archive else None,
            'replacement_index_resource': binary, 'replacement_index_sha256': _sha(raw),
            'index_byte_size': len(raw), 'all_lods_zero_area': True,
            'object_names': [name for name, _ in objects],
        })
        for name, reason in objects:
            object_report.append({'name': name, 'reason': reason,
                                  'original_object': deepcopy(donor['Object'][name]),
                                  'replacement_target': target,
                                  'record_preserved_except_target': True,
                                  'transform_preserved': True})

    light_changes = {}
    sun = deepcopy(level['Light'].get('Sun'))
    if not sun or sun.get('Type') != 'DIRECTIONAL' or 'VC_IsActive' not in sun.get('Attribute', {}):
        raise ValueError('Expected native directional Sun was not found')
    sun['Attribute']['VC_IsActive'] = 1
    if 'VC_CastsShadows' not in sun['Attribute']:
        raise ValueError('Expected native Sun shadow field was not found')
    sun['Attribute']['VC_CastsShadows'] = 1
    # Existing direct-down donor orientation is consistent with its noon time.
    light_changes['Sun'] = sun
    box_prefix = LIGHTING + 'luxboxes_seating_group@'
    box_lights = []
    for name, original in donor['Light'].items():
        if not name.startswith(box_prefix):
            continue
        if original.get('Type') != 'SPOT' or '@boxseatrec_light_' not in name:
            continue
        if level['Light'].get(name) != original:
            raise ValueError('Audited box light differs from donor: ' + name)
        changed = deepcopy(original)
        changed['Attribute']['VC_IsActive'] = 0
        light_changes[name] = changed
        box_lights.append(name)
    time_of_day = deepcopy(level['Object'].get('TIME_OF_DAY'))
    if not time_of_day or time_of_day.get('Type') != 'MARKER':
        raise ValueError('Expected native TIME_OF_DAY marker was not found')
    for key in ('VC_Enabled', 'VC_SkyEnabled'):
        if key not in time_of_day.get('Attribute', {}):
            raise ValueError('Missing existing time-of-day field: ' + key)
        time_of_day['Attribute'][key] = 1

    # Disable the existing stair emissive term too, retaining a non-emitting
    # original material should any subsequent visual pass reuse its surface.
    stair = deepcopy(level['Material'].get(STAIR_LIGHT_MATERIAL))
    if not stair or 'AddOn1EmissiveIntensity' not in stair.get('Parameter', {}):
        raise ValueError('Expected stair-light material was not found')
    stair['Parameter']['AddOn1EmissiveIntensity'] = 0.0

    crowd = _scene(donor_zip.read('crowd.SCNE'))['crowd']
    crowd_bounds = {name: {key: deepcopy(model.get(key)) for key in ('Min', 'Max')}
                    for name, model in crowd.get('Model', {}).items()}
    crowd_original = deepcopy(crowd)
    crowd_model = crowd.get('Model', {}).get('crowd_cards')
    if not crowd_model or crowd_model.get('Min', [0, 0, 0])[1] <= 600:
        raise ValueError('Expected exclusively upper-balcony crowd_cards were not found')
    if crowd.get('Object') != {'crowd_cards': {'Type': 'OBJECT', 'Target': 'crowd_cards', 'Transform': 'Root'}}:
        raise ValueError('Unexpected crowd render object layout')
    crowd_replacement, crowd_binary, crowd_raw = _degenerate_model('crowd.SCNE:crowd_cards', crowd_model)
    if crowd_binary in extra or crowd_binary in resources or crowd_binary in names_in_archive:
        raise ValueError('Crowd replacement resource already exists')
    crowd['Model']['crowd_cards'] = crowd_replacement
    resources[crowd_binary] = crowd_raw
    crowd_text = json.dumps({'crowd': crowd}, separators=(',', ':'))[1:-1]
    preserved_seating = []
    for name, obj in donor['Object'].items():
        group, mesh = _identity(name)
        if obj.get('Type') == 'OBJECT' and name not in allowed_objects and (
                group in ('stands', 'balcony_chairs', 'balcony')):
            preserved_seating.append(name)

    report = {
        'method': 'same-size degenerate index buffers for inspected visual targets; every original object, target and transform remains',
        'hidden_object_count': len(object_report), 'hidden_model_count': len(model_report),
        'hidden_categories': dict(sorted(Counter(o['reason'] for o in object_report).items())),
        'hidden_objects': sorted(object_report, key=lambda o: o['name']),
        'hidden_models': model_report,
        'lighting_changes': [{'name': n, 'before': deepcopy(level['Light'][n]), 'after': deepcopy(v)}
                             for n, v in light_changes.items()],
        'time_of_day_before': deepcopy(level['Object']['TIME_OF_DAY']),
        'time_of_day_after': deepcopy(time_of_day),
        'stair_material_change': {'name': STAIR_LIGHT_MATERIAL,
                                  'before': deepcopy(level['Material'][STAIR_LIGHT_MATERIAL]['Parameter']),
                                  'after': deepcopy(stair['Parameter'])},
        'disabled_box_spotlights': len(box_lights),
        'court_area_lights_retained': [n for n, v in donor['Light'].items()
                                      if n.startswith(LIGHTING + 'court_line_lights_group@')],
        'seating_and_support_objects_preserved': sorted(preserved_seating),
        'crowd_model_bounds_preserved': crowd_bounds,
        'crowd_render_change': {
            'scene': 'crowd.SCNE', 'model': 'crowd_cards', 'original_model': crowd_original['Model']['crowd_cards'],
            'replacement_index_resource': crowd_binary, 'replacement_index_sha256': _sha(crowd_raw),
            'all_crowd_scene_objects_and_transforms_unchanged': True,
            'crowd_data_seat_positions_and_stadium_paths_unchanged': True,
            'reason': 'Only supplied crowd_cards lie exclusively in the removed upper luxury-box tiers',
        },
        # UTF-8 text, not bytes: this report remains JSON serializable. The
        # packer must substitute this entry and retain every other donor entry.
        'scene_overrides': {'crowd.SCNE': crowd_text},
        'gameplay_markers_preserved': [n for n, o in donor['Object'].items()
                                       if o.get('Type') == 'MARKER' and n != 'TIME_OF_DAY'],
        'all_original_object_transforms_unchanged': True,
        'game_runtime_verified': False,
        'limitations': [
            'Existing compiled indoor lightmaps and IBL cubemaps are retained; native sky/sun activation is unverified in NBA 2K.',
            'The four original court area lights remain for dynamic player lighting until game validation of the sun is available.',
            'The supplied upper-balcony crowd_cards are hidden with degenerate indices. CrowdData, crowd_seats_vertex and path resources remain unchanged; any additional runtime-generated spectators require game validation.',
            'Every audited donor enclosure, balcony, chair, side bleacher, court-side board and exterior apron is hidden. Only original gameplay floor render geometry remains; the new outdoor scene supplies paving and low metal bleachers.',
            'User-supplied training screenshots show no spectators. Modes that enable dynamically generated crowds have not been validated; no documented crowd-visibility switch was found in the supplied scene markers.',
            'Original collision resources are retained even where enclosing render geometry is hidden; off-court invisible collisions may still exist.',
        ],
    }
    level['Model'].update(replacements)
    extra.update(resources)
    level['Light'].update(light_changes)
    level['Object']['TIME_OF_DAY'] = time_of_day
    level['Material'][STAIR_LIGHT_MATERIAL] = stair
    return report
