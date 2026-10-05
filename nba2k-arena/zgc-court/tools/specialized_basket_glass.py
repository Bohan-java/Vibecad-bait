"""Whole native outdoor basket_glass pipeline, including Presentation.

Read-only template + in-memory factory. Keeps the Rucker glass geometry,
four-joint skeleton and runtime object identities; supplies dedicated native
glass shaders instead of the general dual-source asset-glass variant.
"""
from __future__ import annotations
import copy
import hashlib
import io
import struct
from pathlib import Path
import zipfile

from PIL import Image
from iff_codec import load_scne

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT.parent / 'build/high_hoop/reference/arena_blacktop_ext.iff'
TEMPLATE_MATERIAL = 'basket_stanchiond_outdoor:glass_shader'
EFFECT = 'basket_glass.fx#fbbf6988cee09674'
SCRIPT = 'basket_glass.9c3a099189c7c26f.script'
GLASS_MATERIALS = ('basket_stanchiont_outdoor:glass_shader_mat',
                   'basket_stanchiont_outdoor:glasshole_shader_mat')
# R13: the requested less-transparent backboard retains the native neutral
# glass tint. Alpha controls its visible color pass; roughness softens sharp
# reflected detail. Roughness is not a verified reflection-energy control.
GLASS_ALBEDO_RGBA = (66, 66, 66, 36)
# Exact BC1 endpoint values (5/6/5 bits); the native shader reads R only.
GLASS_ROUGHNESS_RGB = (82, 81, 82)


def _binaries(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'Binary' and isinstance(child, str):
                yield child
            else:
                yield from _binaries(child)
    elif isinstance(value, list):
        for child in value:
            yield from _binaries(child)


def _bc7_constant(rgba, side=512):
    """BC7 mode 5: independent 7-bit RGB and exact 8-bit alpha endpoints."""
    word = 0x20  # Six-bit unary mode prefix, rotation=0.
    shift = 8
    for component in rgba[:3]:
        q = int(round(component * 127 / 255))
        for _ in range(2):
            word |= q << shift; shift += 7
    for _ in range(2):
        word |= int(rgba[3]) << shift; shift += 8
    # All interpolation indices are zero because both endpoints are identical.
    block = word.to_bytes(16, 'little')
    mips = side.bit_length()
    # 1x1 and 2x2 levels each still occupy a complete BC block.
    levels = [block * (((max(1, side >> i) + 3) // 4) ** 2) for i in range(mips)]
    header = [124, 0xA1007, side, side, len(levels[0]), 0, mips] + [0] * 11
    header += [32, 4, int.from_bytes(b'DX10', 'little'), 0, 0, 0, 0, 0]
    header += [0x401008, 0, 0, 0, 0]
    return (b'DDS ' + struct.pack('<31I', *header) +
            struct.pack('<5I', 98, 3, 0, 1, 0) + b''.join(levels))


def _verify_dds(raw, expected_rgba, side, mips, block, data_offset):
    cursor = data_offset
    for i in range(mips):
        size = max(1, side >> i)
        length = ((size + 3) // 4) ** 2 * block
        header = bytearray(raw[:data_offset])
        struct.pack_into('<II', header, 12, size, size)
        struct.pack_into('<I', header, 20, length)
        struct.pack_into('<I', header, 28, 1)
        decoded = Image.open(io.BytesIO(bytes(header) + raw[cursor:cursor + length])).convert('RGBA')
        assert decoded.size == (size, size)
        assert decoded.getextrema() == tuple((v, v) for v in expected_rgba)
        cursor += length
    assert cursor == len(raw)


def apply_specialized_glass(baskets, extra, template_path=TEMPLATE_PATH):
    """Replace both plate/hole material definitions with a complete native contract.

    ``baskets`` is the baskets.SCNE inner dictionary. ``extra`` receives exactly
    14 native shader resources, its native script, and two full-mip DDS aliases.
    The caller serializes baskets.SCNE and performs the final package checks.
    """
    with zipfile.ZipFile(template_path) as archive:
        raw = archive.read('baskets.SCNE')
        try:
            document = load_scne(raw)
        except (UnicodeDecodeError, ValueError):
            from native_floor_overlay import BinaryScene
            document = BinaryScene(raw).document
        native = document['baskets']
        template = native['Material'][TEMPLATE_MATERIAL]
        assert template['Effect'] == EFFECT and template['Script'] == SCRIPT
        effect = native['Effect'][EFFECT]
        assert effect['Parameter']['AlphaCutOffForDepth']['Value'] == .9
        assert effect['Parameter']['Opacity']['Value'] == 1.
        assert 'Presentation' in effect['Technique']['Default']['Pass']
        source_glass = next(m for m in native['Model'].values()
                            if any(p.get('Material') == TEMPLATE_MATERIAL for p in m.get('Prim', [])))
        target_glass = next(m for n, m in baskets['Model'].items() if n.endswith(':glass'))
        assert [s['Stride'] for s in source_glass['VertexStream']] == [8, 4, 8]
        assert [s['Stride'] for s in target_glass['VertexStream']] == [8, 4, 8]
        for semantic in ('POSITION0', 'TANGENTFRAME0', 'TEXCOORD0', 'WEIGHTDATA0'):
            a, b = source_glass['VertexFormat'][semantic], target_glass['VertexFormat'][semantic]
            for key in ('Format', 'Stream', 'ByteOffset'):
                assert a.get(key, 0) == b.get(key, 0), (semantic, key)
        assert list(source_glass['Transform'].values()) == list(target_glass['Transform'].values())
        assert source_glass['WeightBits'] == target_glass['WeightBits'] == 16
        dependencies = sorted(set(_binaries(effect)) | {SCRIPT})
        assert len(dependencies) == 15
        for name in dependencies:
            payload = archive.read(name)
            if name in extra and extra[name] != payload:
                raise ValueError('Native shader resource collision: ' + name)
            extra[name] = payload
        if EFFECT in baskets['Effect'] and baskets['Effect'][EFFECT] != effect:
            raise ValueError('Native glass effect identity collision')
        baskets['Effect'][EFFECT] = copy.deepcopy(effect)

    # Native outdoor RGB is constant linear 0.0544802882, which corresponds to
    # sRGB 66/255. The dedicated shader multiplies RGB by sampled alpha itself.
    # Do not premultiply the DDS RGB. R13 raises A from 10/255 to 36/255:
    # more visible glass body without introducing opaque painted pixels.
    albedo_rgba = GLASS_ALBEDO_RGBA
    albedo = _bc7_constant(albedo_rgba)
    _verify_dds(albedo, albedo_rgba, 512, 10, 16, 148)
    # Dedicated shader reads roughness from R; G/B are also filled for clarity.
    from native_textures import encode
    temporary = {}
    _, _, rough_report = encode(Image.new('RGB', (512, 512), GLASS_ROUGHNESS_RGB), temporary, linear=True)
    roughness = temporary[rough_report['dds']]
    roughness_rgba = GLASS_ROUGHNESS_RGB + (255,)
    _verify_dds(roughness, roughness_rgba, 512, 10, 8, 128)
    resources = {}
    textures = []
    for slot, kind, payload, fmt, offset, rgba, linear in (
        ('Albedo', 'albedo', albedo, 'BC7_UNORM', 148, albedo_rgba, False),
        ('RoughnessTexture', 'roughness', roughness, 'BC1_UNORM', 128, roughness_rgba, True),
    ):
        digest = hashlib.sha256(payload).hexdigest()
        stem = f'zgc_r13_glass_{kind}.{digest[:16]}'
        pixelmap = f'zgc_r10:glass_{kind}'
        extra[stem + '.dds'] = payload
        # Native descriptors record actual channel ranges, in linear RGB for
        # color textures. These images contain no painted opaque pixels.
        rgb = [v / 255. for v in rgba[:3]]
        if not linear:
            rgb = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
        lo = rgb + [rgba[3] / 255.]
        hi = lo.copy()
        spec = {'Width': 512, 'Height': 512, 'Mips': 10, 'Format': fmt,
                'Min': lo, 'Max': hi, 'PixelDataSize': len(payload) - offset, 'Binary': stem + '.tld'}
        if linear:
            spec['TexelUsage'] = 'LINEAR'
        baskets['Texture'][pixelmap] = spec
        resources[slot] = {'Pixelmap': pixelmap}
        textures.append({'slot': slot, 'pixelmap': pixelmap, 'dds': stem + '.dds',
                         'format': fmt, 'size': [512, 512], 'mips': 10,
                         'decoded_rgba_all_mips': list(rgba), 'dds_sha256': digest})
    material_changes = []
    for name in GLASS_MATERIALS:
        old = baskets['Material'][name]
        replacement = copy.deepcopy(template)
        replacement['Resource'] = copy.deepcopy(resources)
        baskets['Material'][name] = replacement
        material_changes.append({'material': name, 'old_effect': old['Effect'], 'new_effect': EFFECT})
    return {'revision': 'R13', 'game_tested': False, 'template_archive': str(template_path),
            'template_material': TEMPLATE_MATERIAL, 'effect': EFFECT, 'script': SCRIPT,
            'full_native_dependencies_copied': dependencies, 'material_changes': material_changes,
            'textures': textures, 'native_geometry_skeleton_instances_unchanged': True,
            'native_opacity_preserved': 1., 'native_depth_alpha_cutoff_preserved': .9,
            'material_adjustment': {
                'previous_albedo_rgba': [66, 66, 66, 10],
                'current_albedo_rgba': list(GLASS_ALBEDO_RGBA),
                'previous_roughness_r': 16 / 255.,
                'current_roughness_r': GLASS_ROUGHNESS_RGB[0] / 255.,
                'purpose': 'Less transparent neutral glass; softer reflected detail and less sharp highlights.',
                'reflection_energy_multiplier_changed': False,
                'reason': 'No independent reflectivity-intensity parameter is evidenced in the native basket_glass effect.',
            },
            'blend_contract': 'Shader premultiplies straight Albedo RGB by A; ONE/INVSRCALPHA; explicit Presentation pass',
            'shader_evidence': ['Default and Presentation output Albedo.A directly.',
                                'Translucent multiplies its output by native Opacity.',
                                'ZPrepass discards when Albedo.A is below AlphaCutOffForDepth; no OneOverIoR condition.',
                                'RoughnessTexture uses R.'],
            'limits': ['Actual replay pass selection and visual outcome require game validation.',
                       'Roughness changes reflection sharpness and distribution; it is not proof of reduced total reflected energy.',
                       'The original perforated glass topology is retained; this change replaces its entire render contract.',
                       'The white target remains separate geometry 0.517596 mm in front of the native front glass.']}
