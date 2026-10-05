"""Repair only new opaque materials using a native non-lightmapped path.

The evidence is the Rucker trashcan crumpled-paper-cup object: its static
8/4/12 model has no Object.UserData, no Object.Transform, and its material
contains real AssetHires/AssetLores GBuffer shaders in addition to lightmap
variants. This is a format-compatible candidate, not an in-game validation.

Call add_neutral_resources(level, extra) before repair_materials(level, donor).
Transparent materials are deliberately reported as unresolved: every native
static translucent 8/4/12 material available here is lightmap-only. Vehicle
and basket dynamic glass shaders require WEIGHTDATA and are not drop-in.
"""
from __future__ import annotations

import copy

OPAQUE_TEMPLATE = 'cup_coffee_papercrumpled:cup_mat'
OPAQUE_EFFECT = 'asset_CLOD.fx#bc7f3951b8da0d55'
WHITE_PIXELMAP = 'zgc_r04:linear_white_ao'


def add_neutral_resources(level, extra):
    """Add a linear opaque-white AO texture; extra gets native DDS/TLD bytes.

    The original ConeAngleMap is cup_mat_ao.png, a LINEAR scalar AO image.
    White is the conventional no-occlusion endpoint; shader bytecode has not
    been decompiled. This is recorded as an assumption in the repair report.
    Existing grunge addon bindings are retained, not assigned guessed colors.
    """
    from PIL import Image
    import native_textures

    _, texture, report = native_textures.encode(
        Image.new('RGB', (4, 4), (255, 255, 255)), extra, linear=True)
    level['Texture'][WHITE_PIXELMAP] = texture
    return {'pixelmap': WHITE_PIXELMAP, **report}


def _double_sided(material):
    return any(p.get('CULLMODE') == 'NONE'
               for t in material.get('Technique', {}).values()
               for p in t.get('Pass', {}).values())


def _validate_template(level):
    material = level['Material'][OPAQUE_TEMPLATE]
    assert material['Effect'] == OPAQUE_EFFECT
    effect = level['Effect'][OPAQUE_EFFECT]
    assert 'WEIGHTDATA0' not in effect['VertexFormat']
    for name, mask in [('AssetHires', 2), ('AssetLores', 1)]:
        t = effect['Technique'][name]
        assert t['EnableMask'] == mask
        p = t['Pass']['GBuffer']
        assert p['PS']['Binary'] and p['VS']['Binary']
        assert not {'TEXCOORD2', 'TEXCOORD7', 'WEIGHTDATA0'} & set(p['VS']['Input'])
    assert 'AddOn1BlemishIntensity' in effect['Parameter']
    return material


def repair_materials(level, original_donor_level):
    """Mutate zgc_r03 opaque materials only; return a JSON-safe audit report.

    Caller owns packaging and lighting decisions. This function changes no
    geometry, native materials, transforms, exposure, lights, or glass.
    """
    template = _validate_template(original_donor_level)
    if WHITE_PIXELMAP not in level['Texture']:
        raise ValueError('Call add_neutral_resources(level, extra) first')
    changed = []
    unresolved = []
    for name, old in list(level['Material'].items()):
        if not name.startswith('zgc_r03:'):
            continue
        if old.get('Parameter', {}).get('AlphaStyle') == 'TRANSLUCENT':
            unresolved.append(name)
            continue
        old_resources = old['Resource']
        albedo = old_resources['AlbedoMap']['Pixelmap']
        normal_rough = old_resources['NormalAndRoughMap']['Pixelmap']
        mat = copy.deepcopy(template)
        par = mat['Parameter']
        par['AlbedoModulate'] = [1., 1., 1., 1.]
        par['DefaultMetalness'] = float(old.get('Parameter', {}).get('DefaultMetalness', 0.))
        # Native Effect float at offset 156; not an invented script parameter.
        par['AddOn1BlemishIntensity'] = 0.
        # Native Effect float at offset 92; neutral normal texture also retained.
        par['NormalHeight'] = 0.
        mat['Resource']['AlbedoMap'] = {'Pixelmap': albedo}
        mat['Resource']['NormalAndRoughMap'] = {'Pixelmap': normal_rough}
        mat['Resource']['ConeAngleMap'] = {'Pixelmap': WHITE_PIXELMAP}
        # Keep both original addon slots so native descriptor mappings resolve.
        if _double_sided(old):
            for t in mat['Technique'].values():
                for p in t.get('Pass', {}).values():
                    p['CULLMODE'] = 'NONE'
        level['Material'][name] = mat
        changed.append({'material': name, 'old_effect': old['Effect'],
                        'new_effect': mat['Effect'], 'resource_slots': list(mat['Resource'])})
    return {
        'game_verified': False,
        'template': OPAQUE_TEMPLATE,
        'effect': OPAQUE_EFFECT,
        'repaired_opaque_count': len(changed),
        'repaired': changed,
        'unresolved_transparent': unresolved,
        'evidence': [
            'Native cup has 8/4/12 streams and no Object.UserData or Object.Transform.',
            'AssetHires mask 2 and AssetLores mask 1 contain real GBuffer VS/PS.',
            'Their GBuffer VS inputs need no WEIGHTDATA, TEXCOORD2, or TEXCOORD7.',
            'Original opaque simplepbr template only has Lightmap graphics techniques.',
            'Original addon bindings retained; AddOn1BlemishIntensity is a native Effect float.',
        ],
        'remaining_assumptions': [
            'White ConeAngleMap is the neutral AO endpoint, inferred from original AO binding; compiled shader not decompiled.',
            'No native static 8/4/12 non-lightmap transparent template was found in available local donors.',
            'This changes only new opaque material paths and cannot prove or repair a global player-lighting failure.',
        ],
    }
