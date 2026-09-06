"""Repair the runtime lighting routes rejected by the user's R6 game captures.

The shipped native shaders and all geometry buffers remain untouched. New
scenery uses the donor's complete static material and per-instance lightmap
convention. No legacy build/audit pipeline is invoked by this module.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import math
import struct

from revision3_floor_lighting import (
    TLD_HEADER, decode_r11g11b10, encode_r11g11b10, subresources,
)

NATIVE_EFFECT = 'layer_base_CLOD.fx#72407e286031da1b'
NATIVE_MATERIAL = 'clutchtime_floor_apron:floor_mat'
BROKEN_EFFECT = 'venice_v3:unbaked_layer_base_CLOD'
LIGHT_PREFIX = ('arena_clutchtime_int_master@arena_triplethreat_int_lighting@'
                'GameObjects@court_line_lights_group@court_line_light_')
INDOOR_LIGHTS = tuple(LIGHT_PREFIX + str(i) for i in range(4))
EXPOSURE_EV100 = 15.0
LIGHTMAP_SIZE = 16
LIGHTMAP_MIPS = 2
AMBIENT_RGB = (.8, .85, .95)  # Same linear fill as the existing paired floor.
DIRECTION_AMBIENT_RGB = (.5, .5, 1.)
AMBIENT_BINARY = 'venice_r7_scenery_ambient.tld'
VISIBILITY_BINARY = 'venice_r7_scenery_no_indoor_lights.tld'
FLOOR_VISIBILITY_BINARY = 'venice_r7_floor_no_indoor_lights.tld'
FLOOR_VISIBILITY_KEY = '__floor00___linelightvisibility'
AUX_SCENE = 'level_floor_lightmaps.SCNE'


def pack_lightmap_userdata(size=LIGHTMAP_SIZE):
    """48-byte native integer-atlas form, not a fabricated resource identifier.

    PS.0b7b9c751b052066 and PS.04f29b4000dbd424 read the same layout:
      +0: float material lightmap multiplier;
      +4: texture descriptor (zero on disk, resolved by the game);
      +16: bit30 integer-atlas flag, bits28..29 layer count, 14-bit extents;
      +20: two 16-bit atlas dimensions; +24: two 16-bit atlas offsets;
      +28: line-light visibility descriptor (also resolved by the game).
    Native Texture keys match Object names; visibility appends its suffix.
    """
    if type(size) is not int or not 0 < size < 16384:
        raise ValueError('Lightmap size must fit the native 14-bit extent')
    raw = bytearray(48)
    struct.pack_into('<f', raw, 0, 1.)
    struct.pack_into('<III', raw, 16,
                     (1 << 30) | (2 << 28) | (size << 14) | size,
                     (size << 16) | size, 0)
    return base64.b64encode(raw).decode('ascii')


def constant_texture(width, height, mips, face_texels, format_name, binary):
    """Native linear, face-major TLD with explicit dimensions and no compression."""
    formats = {'R11G11B10_FLOAT': (26, 4), 'R8_UNORM': (61, 1)}
    format_code, pixel_bytes = formats[format_name]
    if not face_texels or any(len(v) != pixel_bytes for v in face_texels):
        raise ValueError('Texture faces must each contain one encoded texel')
    layout = subresources(width, height, mips, len(face_texels), pixel_bytes)
    payload = b''.join(face_texels[r['face']] * (r['width'] * r['height'])
                       for r in layout)
    header = TLD_HEADER.pack(b'TLD ', 0, 4, format_code, mips, 31,
                             width, height, 1, len(face_texels), len(payload), len(payload))
    if format_name == 'R11G11B10_FLOAT':
        rgb = [decode_r11g11b10(struct.unpack('<I', value)[0]) for value in face_texels]
        extrema = ([min(v[i] for v in rgb) for i in range(3)],
                   [max(v[i] for v in rgb) for i in range(3)])
    else:
        extrema = ([min(v[0] for v in face_texels) / 255., 0., 0.],
                   [max(v[0] for v in face_texels) / 255., 0., 0.])
    spec = {'Width': width, 'Height': height, 'Mips': mips,
            'Format': format_name, 'TexelUsage': 'LINEAR',
            'Min': extrema[0] + [1.], 'Max': extrema[1] + [1.],
            'PixelDataSize': len(payload), 'Binary': binary}
    if len(face_texels) != 1:
        spec['Faces'] = len(face_texels)
    return spec, header + payload


def scenery_records(level):
    materials = {name for name, value in level['Material'].items()
                 if value.get('Effect') == BROKEN_EFFECT}
    models = {name for name, value in level['Model'].items()
              if any(p.get('Material') in materials for p in value.get('Prim', []))}
    objects = {name for name, value in level['Object'].items()
               if value.get('Target') in models}
    return materials, models, objects


def require_native_uv7(level, archive, models):
    """Check the lightmap fetch layout without rewriting any vertex buffer."""
    for name in models:
        model = level['Model'][name]
        uv = model['VertexFormat'].get('TEXCOORD7', {})
        if (uv.get('Format') != 'R16G16_SNORM' or uv.get('Stream') != 2
                or uv.get('ByteOffset') != 16
                or uv.get('Offset') != [0., 0., 0., 0.]
                or uv.get('Scale') != [1., 1., 1., 1.]):
            raise ValueError('Unexpected generated UV7 fetch layout: ' + name)
        stream = model['VertexStream'][2]
        raw = archive.read(stream['Binary'])
        if (stream['Stride'] != 20 or len(raw) != stream['Size']
                or len(raw) % 20 or any(struct.unpack_from('<hh', raw, offset + 16) != (0, 0)
                                       for offset in range(0, len(raw), 20))):
            raise ValueError('Generated UV7 is not the expected zero-filled stream: ' + name)


def apply_runtime_lighting(level, floor_document, extra, *, ev100=EXPOSURE_EV100):
    """Patch a fresh scene copy; the caller validates and publishes atomically.

    EV15 is a fixed noon starting point, not a claimed game-calibrated value.
    The constant ambient layer prevents absent/roof-baked lighting; native sun
    and genuine static GBuffer/shadow techniques still provide direct shading.
    """
    if not math.isfinite(ev100) or not 12. <= ev100 <= 18.:
        raise ValueError('Expected a finite daylight exposure between EV12 and EV18')
    materials, models, objects = scenery_records(level)
    if not materials or not models or not objects:
        raise ValueError('No R6 generated scenery found')
    for name in models:
        if (not name.startswith('venice_v3:') or
                any(p['Material'] not in materials for p in level['Model'][name]['Prim'])):
            raise ValueError('Refusing to change a mixed or non-generated model: ' + name)
    for name in objects:
        obj = level['Object'][name]
        if not name.startswith('venice_v3:') or obj.get('Type') != 'OBJECT' or 'UserData' in obj:
            raise ValueError('Refusing to replace existing instance lighting data: ' + name)
        if name in level['Texture'] or name + '_linelightvisibility' in level['Texture']:
            raise ValueError('A scenery lightmap slot already exists: ' + name)
    source_material = level['Material'][NATIVE_MATERIAL]
    if source_material['Effect'] != NATIVE_EFFECT:
        raise ValueError('The original static material changed')
    for technique in ('HiresLightmap', 'LoresLightmap'):
        native = level['Effect'][NATIVE_EFFECT]['Technique'][technique]
        if not {'GBuffer', 'OnlyDepthCSM', 'Default'} <= native['Pass'].keys():
            raise ValueError('The native static rendering passes are incomplete')
    for name in INDOOR_LIGHTS:
        light = level['Light'][name]
        if light['Type'] != 'AREA' or light['Attribute'].get('VC_IsActive') != 1:
            raise ValueError('The expected active R6 indoor court light changed: ' + name)
    if level['Light']['Sun']['Attribute'].get('VC_IsActive') != 1:
        raise ValueError('R7 expects the R6 native sun to be enabled')
    tod = level['Object']['TIME_OF_DAY']['Attribute']
    if not tod.get('VC_Enabled') or not tod.get('VC_SkyEnabled'):
        raise ValueError('The R6 native sky is not enabled')
    old_floor = floor_document['level_floor_lightmaps']['Texture'][FLOOR_VISIBILITY_KEY]
    if (old_floor['Format'] != 'R8_UNORM' or old_floor.get('Faces', 1) != 1
            or (old_floor['Width'], old_floor['Height'], old_floor['Mips']) != (424, 424, 2)):
        raise ValueError('The existing floor visibility layout changed')

    ambient_texels = [struct.pack('<I', encode_r11g11b10(rgb))
                      for rgb in (AMBIENT_RGB, DIRECTION_AMBIENT_RGB)]
    ambient, ambient_raw = constant_texture(LIGHTMAP_SIZE, LIGHTMAP_SIZE, LIGHTMAP_MIPS,
                                            ambient_texels, 'R11G11B10_FLOAT', AMBIENT_BINARY)
    visibility, visibility_raw = constant_texture(LIGHTMAP_SIZE, LIGHTMAP_SIZE, LIGHTMAP_MIPS,
                                                  [b'\0'], 'R8_UNORM', VISIBILITY_BINARY)
    floor_visibility, floor_raw = constant_texture(424, 424, 2, [b'\0'],
                                                    'R8_UNORM', FLOOR_VISIBILITY_BINARY)
    resources = {AMBIENT_BINARY: ambient_raw, VISIBILITY_BINARY: visibility_raw,
                 FLOOR_VISIBILITY_BINARY: floor_raw}
    if set(resources) & set(extra):
        raise ValueError('R7 texture resource name collision')

    before_lights = {name: deepcopy(level['Light'][name]) for name in INDOOR_LIGHTS}
    before_tod = deepcopy(tod)
    for name in INDOOR_LIGHTS:
        level['Light'][name]['Attribute']['VC_IsActive'] = 0
        level['Light'][name]['Intensity'] = 0.
    tod['VC_AutomaticEV100Enabled'] = 0
    tod['VC_EV100'] = float(ev100)
    for name in materials:
        level['Material'][name]['Effect'] = NATIVE_EFFECT
        level['Material'][name]['Technique'] = deepcopy(source_material['Technique'])
    for name in models:
        # Both native Hires and Lores shaders sample lightmap UV7. Raw UV7=0;
        # center it using only its fetch offset, leaving every buffer untouched.
        level['Model'][name]['VertexFormat']['TEXCOORD7']['Offset'] = [.5, .5, 0., 0.]
    for name in sorted(objects):
        level['Object'][name]['UserData'] = pack_lightmap_userdata()
        level['Texture'][name] = deepcopy(ambient)
        level['Texture'][name + '_linelightvisibility'] = deepcopy(visibility)
    floor_document['level_floor_lightmaps']['Texture'][FLOOR_VISIBILITY_KEY] = floor_visibility
    extra.update(resources)
    return {
        'status': 'RUNTIME_REPAIR_CANDIDATE_GAME_UNTESTED',
        'input_game_feedback': 'R6 rejected: clipped-white floor/players/baskets and black scenery',
        'materials': sorted(materials), 'models': sorted(models), 'objects': sorted(objects),
        'indoor_lights_before': before_lights,
        'indoor_lights_disabled_and_zero_intensity': list(INDOOR_LIGHTS),
        'time_of_day_before': before_tod, 'time_of_day_after': deepcopy(tod),
        'fixed_ev100': ev100, 'native_static_effect': NATIVE_EFFECT,
        'ambient_rgb': list(AMBIENT_RGB), 'ambient_quantized_rgb': list(
            decode_r11g11b10(encode_r11g11b10(AMBIENT_RGB))),
        'direction_ambient_rgb': list(DIRECTION_AMBIENT_RGB),
        'scenery_lightmap_size': LIGHTMAP_SIZE, 'scenery_lightmap_faces': 2,
        'scenery_lightmap_mips': LIGHTMAP_MIPS,
        'scenery_userdata': pack_lightmap_userdata(),
        'indoor_linelight_visibility': 0.,
        'added_binary_resources': {name: len(raw) for name, raw in resources.items()},
        'game_runtime_verified': False, 'game_directory_modified': False,
    }


def check_scope(before, after, floor_before, floor_after, report):
    """Fail closed on changes outside these runtime lighting fields."""
    expected = deepcopy(before)
    for name in report['indoor_lights_disabled_and_zero_intensity']:
        expected['Light'][name]['Intensity'] = 0.
        expected['Light'][name]['Attribute']['VC_IsActive'] = 0
    expected['Object']['TIME_OF_DAY']['Attribute']['VC_AutomaticEV100Enabled'] = 0
    expected['Object']['TIME_OF_DAY']['Attribute']['VC_EV100'] = report['fixed_ev100']
    for name in report['materials']:
        expected['Material'][name]['Effect'] = NATIVE_EFFECT
        expected['Material'][name]['Technique'] = deepcopy(before['Material'][NATIVE_MATERIAL]['Technique'])
    for name in report['models']:
        expected['Model'][name]['VertexFormat']['TEXCOORD7']['Offset'] = [.5, .5, 0., 0.]
    for name in report['objects']:
        expected['Object'][name]['UserData'] = pack_lightmap_userdata()
        for key in (name, name + '_linelightvisibility'):
            expected['Texture'][key] = after['Texture'][key]
    if expected != after:
        raise ValueError('A protected scene field changed outside the R7 lighting scope')
    expected_floor = deepcopy(floor_before)
    expected_floor['level_floor_lightmaps']['Texture'][FLOOR_VISIBILITY_KEY] = (
        floor_after['level_floor_lightmaps']['Texture'][FLOOR_VISIBILITY_KEY])
    if expected_floor != floor_after:
        raise ValueError('A protected auxiliary floor field changed')
