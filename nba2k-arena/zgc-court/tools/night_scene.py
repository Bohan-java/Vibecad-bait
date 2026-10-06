"""N4 night scene: emissive overlays, fence LED strips and native lights.

Runs after night_lighting.apply_night. Nothing existing is modified: every
glowing surface is a NEW static model (namespace zgc_n4:) drawn 0.4 cm in front
of an existing custom part along its vertex normals, or a new thin LED box on
the fence panels. Emitters clone the native Rucker lamp emitter material
(simplepbr_CLOD, no textures, same 8/4/12 vertex layout as the custom models)
and copy the native lamp object's UserData. That material only has lightmap
techniques; emission is expected to add on top of a dark lightmapped diffuse.
Lights reuse the native SPOT / line-AREA schema of the indoor donor
arena_020_int_original.iff.

Coordinates: custom models are authored in game cm and drawn with a 180 degree
object matrix, so a model-space point (x, y, z) appears at world (-x, y, -z).
Lights live in world space. All intensities are first guesses at the fixed
camera EV100 14.8 and must be tuned from game screenshots.
"""
from __future__ import annotations

import copy

import numpy as np

from iff_codec import decode_attribute, decode_normals, make_static_model, resolve_binary

REVISION = 'N4'
PREFIX = 'zgc_n4:'
EMITTER_TEMPLATE = 'light_lamppost_genericb:light_mat'
LAMP_USERDATA = 'AACAPwAAAAAAAAAAAAAAAEAAEFBAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
ROTATED = [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1]
OFFSET_CM = 0.4

# name: (colour, intensity)
EMITTERS = {
    'flood_lens': ([1.0, 0.97, 0.9], 150000.0),
    'a_sign': ([1.0, 1.0, 1.0], 60000.0),
    'chilis_letters': ([1.0, 0.35, 0.08], 40000.0),
    'chilis_pepper': ([1.0, 0.12, 0.06], 40000.0),
    'warm_strip': ([1.0, 0.85, 0.65], 30000.0),
    'logo_letters': ([1.0, 0.4, 0.1], 30000.0),
    'boots_letters': ([1.0, 0.9, 0.75], 25000.0),
    'fence_led': ([0.85, 0.92, 1.0], 50000.0),
}

# Existing custom parts that get a glowing skin, by source object description.
OVERLAYS = {
    'zgc_r03:part-0073': 'flood_lens',       # left tall floodlight lens faces
    'zgc_r03:part-0611': 'a_sign', 'zgc_r03:part-0612': 'a_sign',   # A inner diffuser
    'zgc_r03:part-0619': 'a_sign', 'zgc_r03:part-0620': 'a_sign',   # A diffuser stroke 1
    'zgc_r03:part-0621': 'a_sign', 'zgc_r03:part-0622': 'a_sign',   # A diffuser stroke -1
    'zgc_r03:part-0439': 'chilis_letters',   # court facade channel letters amber acrylic
    'zgc_r03:part-0446': 'chilis_pepper',    # pepper apostrophe acrylic
    'zgc_r03:part-0096': 'warm_strip',       # entry vertical diffuser strips
    'zgc_r03:part-0140': 'warm_strip',       # terrace vertical diffuser strips
    'zgc_r03:part-0079': 'logo_letters',     # alcove logo letters
    'zgc_r03:part-0138': 'logo_letters',     # terrace logo letters
    'zgc_r03:part-0181': 'boots_letters',    # The boots lettering
}

# Fence LED strips on top of the NBA ATELIER base panels, model space boxes.
FENCE_STRIPS = {
    'fence_led_end': ((-914.0, 67.0, -1609.5), (914.0, 69.0, -1606.5)),
    'fence_led_north': ((915.5, 67.0, -1605.0), (918.5, 69.0, -483.0)),
    'fence_led_south': ((-918.5, 67.0, -1605.0), (-915.5, 69.0, -283.0)),
}


def world(p):
    return [-p[0], p[1], -p[2]]


def _unit(v):
    v = np.asarray(v, float)
    return (v / np.linalg.norm(v)).tolist()


def spot(name, position, target, colour, intensity, cone_deg, shadows):
    return {'Type': 'SPOT', 'Intensity': float(intensity), 'Color': [*colour, 1.0], 'Attribute': {
        'VC_AimDirection': [*_unit(np.subtract(target, position)), 0.0],
        'CONEANGLE': float(np.radians(cone_deg)), 'PENUMBRAANGLE': float(np.radians(cone_deg * 0.4)),
        'PENUMBRAFALLOFFEXPONENT': 2.0, 'VC_MinDistance': 0.0, 'VC_Decay': 1.0,
        'VC_NearPlane': 25.0, 'VC_FarPlane': 4000.0, 'VC_SizeScale': 1.0, 'VC_BlackLight': 0.0,
        'VC_NormalBias': 0.5, 'VC_CastsShadows': int(shadows), 'VC_FakeLineLightShadows': 0,
        'VC_EnableVolumetric': 0, 'VC_CastVolumetricShadow': 0, 'VC_FalloffExponent': 2.0,
        'VC_IsNightOnly': 0, 'VC_IgnoreDynamicCasters': 0, 'VC_VolumetricIntensity': 1.0,
        'vc_ingame_light': 1, 'VC_IsMovable': 0, 'VC_IsActive': 1, 'VC_PresentationLightId': 0,
        'VC_LocatorName': name}, 'Translate': [float(x) for x in position]}


def line(name, end1, end2, colour, intensity, radius):
    mid = (np.add(end1, end2) / 2).tolist()
    return {'Type': 'AREA', 'Intensity': float(intensity), 'Color': [*colour, 1.0], 'Attribute': {
        'VC_AreaLightType': 1, 'EndPoint1': [*map(float, end1), 0.0], 'EndPoint2': [*map(float, end2), 0.0],
        'VC_BlackLight': 0.0, 'Radius': float(radius), 'Direction': [0.0, -1.0, 0.0, 0.0], 'HasDirection': 0,
        'Alpha': 0.610865235, 'Beta': 0.959931076, 'PenumbraFalloffExponent': 3.0, 'VC_CastsShadows': 0,
        'vc_ingame_light': 1, 'VC_IsMovable': 0, 'VC_IsActive': 1, 'AreaRadius': 2.0,
        'VC_LocatorName': name}, 'Translate': [float(x) for x in mid]}


def lights():
    # Left tall floodlight heads: model x -989..-966, y 955..1055, z -467..-373.
    upper, lower = world((-975.0, 1035.0, -420.0)), world((-975.0, 975.0, -420.0))
    cool, warm = [1.0, 0.95, 0.86], [1.0, 0.62, 0.32]
    led = EMITTERS['fence_led'][0]
    result = {
        'flood_upper': spot('zgc_n4_flood_upper', upper, world((80.0, 0.0, -950.0)), cool, 4.0e6, 70, True),
        'flood_lower': spot('zgc_n4_flood_lower', lower, world((80.0, 0.0, 250.0)), cool, 4.0e6, 70, False),
        # Hidden high fill from the opposite side so the far half is not black.
        'fill_left': spot('zgc_n4_fill_left', (-1800.0, 1400.0, 700.0), (300.0, 0.0, 700.0), [0.82, 0.88, 1.0],
                          1.2e6, 75, False),
        'chilis_spill': spot('zgc_n4_chilis_spill', world((-420.0, 450.0, -2050.0)), world((-420.0, 0.0, -1700.0)),
                             warm, 3.0e5, 80, False),
    }
    for key, (lo, hi) in FENCE_STRIPS.items():
        y = hi[1] + 6.0
        if key == 'fence_led_end':
            a, b = (lo[0], y, (lo[2] + hi[2]) / 2), (hi[0], y, (lo[2] + hi[2]) / 2)
        else:
            x = (lo[0] + hi[0]) / 2
            a, b = (x, y, lo[2]), (x, y, hi[2])
        result[key] = line('zgc_n4_' + key, world(a), world(b), led, 1.5e5, 500.0)
    return {PREFIX + k: v for k, v in result.items()}


def _box(lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    faces = []
    for axis in range(3):
        for sign in (-1, 1):
            n = np.zeros(3); n[axis] = sign
            u, v = [a for a in range(3) if a != axis]
            quad = []
            for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                p = np.where(sign > 0, hi, lo).astype(float).copy()
                p[u] = (lo[u], hi[u])[du]
                p[v] = (lo[v], hi[v])[dv]
                quad.append(p)
            faces.append((quad, n))
    positions, normals, uv, indices = [], [], [], []
    for quad, n in faces:
        base = len(positions)
        positions += quad
        normals += [n] * 4
        uv += [(0, 0), (1, 0), (1, 1), (0, 1)]
        tri = [(0, 1, 2), (0, 2, 3)]
        # Keep counter-clockwise winding seen from the outward normal.
        if np.dot(np.cross(quad[1] - quad[0], quad[2] - quad[0]), n) < 0:
            tri = [(0, 2, 1), (0, 3, 2)]
        indices += [base + i for t in tri for i in t]
    return np.array(positions), np.array(normals), np.array(uv, float), np.array(indices)


def _emitter_material(level, colour, intensity):
    mat = copy.deepcopy(level['Material'][EMITTER_TEMPLATE])
    mat['Parameter'].update(DefaultAlbedo=list(colour), EmissiveDefaultAlbedo=list(colour),
                            EmissiveTint=[1.0, 1.0, 1.0], EmissiveIntensity=float(intensity))
    return mat


def _add(level, extra, name, positions, normals, uv, indices, material):
    model, obj = make_static_model(name, positions, normals, uv, indices, material, extra)
    obj.pop('Transform', None)
    obj['Matrix'] = ROTATED.copy()
    obj['UserData'] = LAMP_USERDATA
    level['Model'][name] = model
    level['Object'][name] = obj


def strip_scene(level):
    """Remove earlier zgc_n4 content; return binaries only it referenced."""
    from repair_iff import binaries
    removed = {n: level['Model'].pop(n) for n in [k for k in level['Model'] if k.startswith(PREFIX)]}
    for section in ('Object', 'Material', 'Light'):
        for name in [k for k in level[section] if k.startswith(PREFIX)]:
            del level[section][name]
    kept = {b for m in level['Model'].values() for b in binaries(m)}
    return {b for m in removed.values() for b in binaries(m)} - kept


def apply_scene(level, archive, extra):
    """Mutate level and fill extra with new buffers. archive reads existing part buffers."""
    assert EMITTER_TEMPLATE in level['Material'] and not any(k.startswith(PREFIX) for k in level['Model'])
    assert not any(k.startswith(PREFIX) for k in level['Light'])
    for key, (colour, intensity) in EMITTERS.items():
        level['Material'][PREFIX + 'emit_' + key] = _emitter_material(level, colour, intensity)
    overlays = []
    for source, key in OVERLAYS.items():
        model = level['Model'][source]
        assert len(model['Prim']) == 1 and level['Object'][source]['Matrix'] == ROTATED, source
        p = decode_attribute(archive, model, 'POSITION0')[:, :3].astype(float)
        n = decode_normals(decode_attribute(archive, model, 'TANGENTFRAME0'))
        uv = decode_attribute(archive, model, 'TEXCOORD0')[:, :2]
        ix = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])), '<u2').astype(np.int64)
        name = PREFIX + 'glow-' + source.split(':')[1]
        _add(level, extra, name, p + n * OFFSET_CM, n, uv, ix, PREFIX + 'emit_' + key)
        overlays.append({'model': name, 'source': source, 'emitter': key, 'vertices': len(p), 'triangles': len(ix) // 3})
    for key, (lo, hi) in FENCE_STRIPS.items():
        _add(level, extra, PREFIX + key, *_box(lo, hi), PREFIX + 'emit_fence_led')
    new_lights = lights()
    level['Light'].update(new_lights)
    return {
        'revision': REVISION,
        'emitters': {k: {'colour': c, 'intensity': i} for k, (c, i) in EMITTERS.items()},
        'emitter_template': EMITTER_TEMPLATE,
        'overlays': overlays,
        'fence_strips': {k: {'min': lo, 'max': hi} for k, (lo, hi) in FENCE_STRIPS.items()},
        'lights': {k: {'type': v['Type'], 'intensity': v['Intensity'], 'translate': v['Translate']} for k, v in new_lights.items()},
        'unchanged': 'All pre-existing models, objects, materials, textures and lights; new content only under zgc_n4:.',
        'unverified': 'Emissive output of a lightmap-only native material on custom static geometry, and native light intensity units at EV100 14.8.',
    }
