"""N7 night scene: native lightmap emitters plus baked probe light on the court.

Runs after night_lighting.apply_night. No pre-existing model, object or
material changes; everything new lives under zgc_n7:.

Game evidence (2026-10-05/06):
- N4: SPOT/AREA entries added to level.Light are ignored in Blacktop (also at
  100x saturated colour). LIGHT_BRICK_MAP is not rebuilt, and its multi-light
  format is not decoded, so no real-time lights are added here.
- N4: the native lamp emitter material on custom geometry did not glow when it
  only copied the lamp's UserData.
- LDIAG1 (ChatGPT diagnostic): the same material DOES glow with native bloom
  when the object also has a same-name level.Texture entry (the lamp's 64x64
  BC4 lightmap descriptor), the lamp's 48-byte UserData, and an independent
  UV7 chart inside [0, 1]. An identical box without the same-name texture
  stayed dark. The scoreboard shader (N5/N6) renders but looks flat.
- LDIAG1: scaling whole 28-float records of baked light probes around court
  centre brightened the floor, a neutral static board and players, while an
  untouched control area stayed dark.

N7 game result: emitters glow with bloom and the court is lit. User asked to
remove the fence LED strips, make Chilis look open with warm light from inside,
and go for a midnight mood: tall floodlight much dimmer, Chilis and the two
A signs as the main (soft) light sources (N8). N9 adds soft probe bounce on the
fence panels beside the A signs, the Chilis awning/terrace and the boots facade;
the rubber court floor keeps its material (no added reflection). N10: the glowing
flank glazing made the whole wall look cheap; it is removed, the interior planes
are dimmed, and light now spills out of the entry via warm probe gain. N11: replay
uses its own darker exposure, so the interior emitters and the entry spill are
doubled and the spill is shaped as an interior pool plus three doorway pools.
N12: the court still read flat and bright; with night_lighting N3.2 the ambient
drops one more EV, the court base gain falls to 1.6 and the local A sign and
Chilis pools rise (and tighten) so dark areas really fall off.

So N7/N8 give every glowing part a closed, slightly offset copy bound exactly
like the working LDIAG1 box, and lights the court with a smooth probe gain.
Probe gain is scalar: it brightens the existing baked ambient without changing
its colour, direction or visibility data.

Coordinates: custom parts are authored in game cm and drawn with a 180 degree
object matrix, so a model-space point (x, y, z) appears at world (-x, y, -z).
Probe positions and gain regions are WORLD cm.
"""
from __future__ import annotations

import copy
import hashlib
import re

import numpy as np
from PIL import Image

import native_textures
from iff_codec import decode_attribute, decode_normals, make_static_model, resolve_binary, texture_density

REVISION = 'N16'
PREFIX = 'zgc_n16:'
OLD_PREFIXES = ('zgc_n4:', 'zgc_n5:', 'zgc_n6:', 'zgc_probe_emit:', 'zgc_diag_receiver:', 'zgc_n7:', 'zgc_n8:', 'zgc_n9:', 'zgc_n10:', 'zgc_n11:', 'zgc_n12:', 'zgc_n13:', 'zgc_n14:', 'zgc_n15:', PREFIX)
EMITTER_TEMPLATE = 'light_lamppost_genericb:light_mat'
LAMP_OBJECT = ('park_streetball_a_master@park_rucker_ext_shared@GameObjects@'
               'GameObjectGroup_121@light_lamppost_genericb_19:light_lamppost_genericb_low')
LAMP_USERDATA = 'AACAPwAAAAAAAAAAAAAAAEAAEFBAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
ROTATED = [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1]
OFFSET_CM = 0.4

# name: (linear colour, EmissiveIntensity). LDIAG1 purple at 100000 bloomed strongly.
# N11 values include a 0.7 overall darkening (with night_lighting N3.1); the tall
# floodlight is at 1/20 of N7 and the A signs at 20000 x 0.7. Chilis letters are
# deeper orange at lower intensity so the brighter gameplay exposure does not clip
# them to yellow (replay showed the intended orange).
EMITTERS = {
    'flood_lens': ([1.0, 0.93, 0.8], 5250.0),
    'a_sign': ([1.0, 1.0, 1.0], 7000.0),
    'chilis_letters': ([1.0, 0.24, 0.03], 16000.0),
    'chilis_pepper': ([0.35, 1.0, 0.22], 28000.0),
    'warm_strip': ([1.0, 0.8, 0.55], 28000.0),
    'logo_letters': ([1.0, 0.24, 0.03], 16000.0),
    'boots_letters': ([1.0, 0.9, 0.75], 28000.0),
    'interior_back': ([1.0, 0.55, 0.2], 4900.0),
    'interior_timber': ([1.0, 0.5, 0.18], 3500.0),
}

# Existing custom parts that get a glowing skin.
OVERLAYS = {
    'zgc_r03:part-0073': 'flood_lens',       # left tall floodlight lens faces
    'zgc_r03:part-0611': 'a_sign', 'zgc_r03:part-0612': 'a_sign',   # A inner diffuser
    'zgc_r03:part-0619': 'a_sign', 'zgc_r03:part-0620': 'a_sign',   # A diffuser stroke 1
    'zgc_r03:part-0621': 'a_sign', 'zgc_r03:part-0622': 'a_sign',   # A diffuser stroke -1
    'zgc_r03:part-0439': 'chilis_letters',   # court facade channel letters amber acrylic
    'zgc_r03:part-0446': 'chilis_pepper',    # pepper apostrophe acrylic (green in the model)
    'zgc_r03:part-0096': 'warm_strip',       # entry vertical diffuser strips
    'zgc_r03:part-0140': 'warm_strip',       # terrace vertical diffuser strips
    'zgc_r03:part-0079': 'logo_letters',     # alcove logo letters
    'zgc_r03:part-0138': 'logo_letters',     # terrace logo letters
    'zgc_r03:part-0181': 'boots_letters',    # The boots lettering
    'zgc_r03:part-0101': 'interior_back',    # Chilis entry shallow interior warm back plane
    'zgc_r03:part-0102': 'interior_timber',  # Chilis entry shallow interior warm timber planes
}

# Baked court light, WORLD cm. Court is X +-762, Z +-1433; the yellow/black half
# (and the Blacktop half-court end) is +Z. Contributions ADD (no max creases).
# Probes sit ~400 cm apart, so pools use Gaussian falloff (sigma >= ~330 cm):
# neighbouring probes then differ by at most about 2x and the floor shows no
# hard edge or probe-cell outline (N12 smoothstep pools did).
# Midnight look: a faint court base; the two court-side A signs and the Chilis
# entry are the main local light sources.
# Light colours (linear RGB, relative): Chilis ~2700 K, boots ~3500 K, floodlight
# ~4000 K, A signs ~5500 K cool white, against a ~7500 K-looking moonlit ambient.
WARM = (1.0, 0.58, 0.25)
WARM_WHITE = (1.0, 0.82, 0.6)
FLOOD_WHITE = (1.0, 0.9, 0.78)
COOL_WHITE = (0.92, 0.97, 1.0)
CHILIS_SOURCE = [420.0, 180.0, 2180.0]   # just inside the entry
PROBE_GAIN_REGIONS = [
    {'label': 'court_base_south', 'center_cm': [0.0, 150.0, -700.0], 'inner_radius_cm': 600.0, 'outer_radius_cm': 1200.0, 'gain': 1.6},
    {'label': 'court_base_north', 'center_cm': [0.0, 150.0, 700.0], 'inner_radius_cm': 600.0, 'outer_radius_cm': 1200.0, 'gain': 1.6},
    # A signs on the fences at world (906, ~200, 950) and (-906, ~200, 1190).
    {'label': 'a_sign_east', 'center_cm': [800.0, 150.0, 950.0], 'sigma_cm': 320.0, 'gain': 30.0, 'tint': COOL_WHITE, 'source_cm': [906.0, 200.0, 950.0]},
    {'label': 'a_sign_west', 'center_cm': [-800.0, 150.0, 1190.0], 'sigma_cm': 320.0, 'gain': 30.0, 'tint': COOL_WHITE, 'source_cm': [-906.0, 200.0, 1190.0]},
    # The dimmed tall floodlight still drops a faint pool around its base, lit from above.
    {'label': 'flood_pool', 'center_cm': [975.0, 0.0, 420.0], 'sigma_cm': 550.0, 'gain': 2.5, 'tint': FLOOD_WHITE, 'source_cm': [975.0, 1000.0, 420.0]},
]
# Warm spill from inside the Chilis entry. Applied per colour channel assuming
# each record is RGB L0 + pad + eight RGB coefficient triples (the zero fourth
# float fits that); not proven, so the tint stays local. y_fade keeps the probe
# layer at ~4 m (level with the big sign panel) unlit so only the letters glow.
CHILIS_Y_FADE = (200.0, 380.0)
WARM_GAIN_REGIONS = [
    {'label': 'chilis_interior', 'center_cm': [420.0, 120.0, 2200.0], 'sigma_cm': 420.0, 'gain': 24.0, 'tint': WARM, 'y_fade': CHILIS_Y_FADE, 'source_cm': CHILIS_SOURCE},
    {'label': 'chilis_door_west', 'center_cm': [50.0, 50.0, 2030.0], 'sigma_cm': 450.0, 'gain': 10.0, 'tint': WARM, 'y_fade': CHILIS_Y_FADE, 'source_cm': CHILIS_SOURCE},
    {'label': 'chilis_door_mid', 'center_cm': [420.0, 50.0, 2030.0], 'sigma_cm': 450.0, 'gain': 10.0, 'tint': WARM, 'y_fade': CHILIS_Y_FADE, 'source_cm': CHILIS_SOURCE},
    {'label': 'chilis_door_east', 'center_cm': [800.0, 50.0, 2030.0], 'sigma_cm': 450.0, 'gain': 10.0, 'tint': WARM, 'y_fade': CHILIS_Y_FADE, 'source_cm': CHILIS_SOURCE},
    {'label': 'chilis_entry_broad', 'center_cm': [420.0, 50.0, 1900.0], 'sigma_cm': 700.0, 'gain': 5.0, 'tint': WARM, 'y_fade': CHILIS_Y_FADE, 'source_cm': CHILIS_SOURCE},
    {'label': 'chilis_terrace', 'center_cm': [1550.0, 150.0, 2800.0], 'sigma_cm': 400.0, 'gain': 8.0, 'tint': WARM, 'y_fade': CHILIS_Y_FADE, 'source_cm': [1633.0, 250.0, 2800.0]},
    {'label': 'boots_facade', 'center_cm': [1550.0, 150.0, 1442.0], 'sigma_cm': 350.0, 'gain': 6.0, 'tint': WARM_WHITE, 'source_cm': [1610.0, 290.0, 1442.0]},
]
# N14 colour grade: cool moonlit ambient around the scene (practicals stay warm/white
# because their gains are added on top). Full within 25 m of the court, fading
# out by 35 m so the change stays inside probe sector 3_0_2 (west edge 36 m).
COOL_GRADE = {'center_cm': [0.0, 0.0, 500.0], 'inner_radius_cm': 2500.0, 'outer_radius_cm': 3500.0,
              'rgb': (0.70, 0.85, 1.08)}
# Directional baked light (N15). Probe records are 9-coefficient RGB SH: L0 RGB,
# a zero pad, then eight interleaved RGB triples. The N14 in-game diagnostic
# showed triple 0 lighting up-facing surfaces, i.e. the usual real-SH order
# L1 = (Y, Z, X). For each light region with a source, the added L0 light gets
# an L1 lobe pointing from the probe towards the source; DIRECTIONALITY is the
# L1/L0 ratio (0.7 leaves the far side at about 1/8 of the lit side, not black).
DIRECTIONALITY = 0.85
L1_TRIPLE_FOR_AXIS = {1: 1, 2: 2, 0: 3}   # world axis (x=0, y=1, z=2) -> index into RGB_TRIPLES
RGB_TRIPLES = [(0, 1, 2)] + [(4 + 3 * k, 5 + 3 * k, 6 + 3 * k) for k in range(8)]
PROBE_DATA_KEY = re.compile(r'^LIGHT_PROBE_GRID_(\d+)_(\d+)_(\d+)_TIME_0000_PROBE_DATA$')
PROBE_STRIDE = 112


def _planar_uv7(positions):
    """Project onto the two widest axes and fit inside [0.03, 0.97]."""
    span = np.ptp(positions, axis=0)
    a, b = np.argsort(span)[-2:][::-1]
    q = positions[:, [a, b]]
    lo, size = q.min(0), np.maximum(np.ptp(q, axis=0), 1e-6)
    return 0.03 + 0.94 * (q - lo) / size


def _texture_archive_name(binary):
    # Final packages are DDS-only for .tld and .bin-only for .gz references.
    if binary.endswith('.tld'):
        return binary[:-4] + '.dds'
    if binary.endswith('.gz'):
        return binary[:-3] + '.bin'
    return binary


def strip_scene(level, base_level):
    """Remove earlier night-scene/diagnostic content and restore base probe data.

    base_level is the clean R13 day level; only probe-data Texture entries are
    restored from it. Returns archive members that only removed content used.
    """
    from repair_iff import binaries
    old = lambda k: k.startswith(OLD_PREFIXES)
    removed = [level['Model'].pop(n) for n in [k for k in level['Model'] if old(k)]]
    removed += [level['Texture'].pop(n) for n in [k for k in level['Texture'] if old(k)]]
    for section in ('Object', 'Material', 'Light'):
        for name in [k for k in level[section] if old(k)]:
            del level[section][name]
    for key in [k for k in level['Texture'] if PROBE_DATA_KEY.fullmatch(k)]:
        if level['Texture'][key] != base_level['Texture'][key]:
            removed.append(level['Texture'][key])
            level['Texture'][key] = copy.deepcopy(base_level['Texture'][key])
    kept = {_texture_archive_name(b) for section in ('Model', 'Texture') for v in level[section].values() for b in binaries(v)}
    return {_texture_archive_name(b) for v in removed for b in binaries(v)} - kept


def _emitter_material(level, colour, intensity):
    mat = copy.deepcopy(level['Material'][EMITTER_TEMPLATE])
    mat['Parameter'].update(DefaultAlbedo=list(colour), EmissiveDefaultAlbedo=list(colour),
                            EmissiveTint=[1.0, 1.0, 1.0], EmissiveIntensity=float(intensity))
    return mat


def _add_emitter(level, extra, name, positions, normals, uv0, indices, uv7, material):
    """New object bound like the LDIAG1 box: lamp UserData + same-name lightmap + UV7."""
    model, obj = make_static_model(name, positions, normals, uv0, indices, material, extra, uv_lightmap=uv7)
    density = texture_density(positions, uv7, np.asarray(indices).reshape(-1, 3))
    model['Duv7'] = density
    model['Prim'][0]['Duv7'] = density.copy()
    obj.pop('Transform', None)
    obj['Matrix'] = ROTATED.copy()
    obj['UserData'] = LAMP_USERDATA
    level['Texture'][name] = copy.deepcopy(level['Texture'][LAMP_OBJECT])
    level['Model'][name] = model
    level['Object'][name] = obj


def _probe_gain(level, archive, extra):
    """Scale whole probe records near the court; returns an audit."""
    grid = level['Object']['LIGHT_PROBE_GRID_DATA']['Attribute']
    assert grid['VERSION'] == 4 and grid['USE_RELIGHTING'] == 0
    origin = np.asarray(grid['GRID_ORIGIN'][:3], float)
    sectors = []
    for key in sorted(k for k in level['Texture'] if PROBE_DATA_KEY.fullmatch(k)):
        prefix = key[:-len('_TIME_0000_PROBE_DATA')]
        spec = level['Texture'][key]
        count = int(spec['Height'])
        assert spec['Width'] == 7 and spec['Format'] == 'R32G32B32A32_FLOAT' and spec['Dimension'] == 'BYTEADDRESSBUFFER'
        raw = archive.read(_texture_archive_name(spec['Binary']))
        assert len(raw) == count * PROBE_STRIDE == spec['PixelDataSize'], key
        data = np.frombuffer(raw, '<f4').reshape(count, 28)
        assert np.isfinite(data).all() and np.all(data[:, 3] == 0), key
        pos_spec = level['Texture'][prefix + '_PROBE_POSITIONS']
        world = np.frombuffer(archive.read(_texture_archive_name(pos_spec['Binary'])), '<f4').reshape(count, 3) + origin
        idx_spec, state_spec = level['Texture'][prefix + '_CELL_PROBE_INDICES'], level['Texture'][prefix + '_CELL_PROBE_STATES']
        indices = np.frombuffer(archive.read(_texture_archive_name(idx_spec['Binary'])), '<u4').reshape(-1, 8)
        states = np.frombuffer(archive.read(_texture_archive_name(state_spec['Binary'])), np.uint8)
        active = ((states[:, None] >> np.arange(8, dtype=np.uint8)) & 1).astype(bool)
        assert np.all(indices[~active] == 0) and np.all(indices[active] < count), key
        referenced = np.zeros(count, bool)
        referenced[np.unique(indices[active])] = True
        def weight(region):
            d = np.linalg.norm(world - np.asarray(region['center_cm']), axis=1)
            if 'sigma_cm' in region:
                w = np.exp(-0.5 * (d / region['sigma_cm']) ** 2)
                w[w < 0.01] = 0.0
            else:
                t = np.clip((d - region['inner_radius_cm']) / (region['outer_radius_cm'] - region['inner_radius_cm']), 0, 1)
                w = 1 - t * t * (3 - 2 * t)
            if 'y_fade' in region:
                y0, y1 = region['y_fade']
                t = np.clip((world[:, 1] - y0) / (y1 - y0), 0, 1)
                w = w * (1 - t * t * (3 - 2 * t))
            return w
        # Per-float multiplier: white gains on every float, tinted gains per RGB channel; all additive.
        multiplier = np.ones((count, 28))
        cool = weight(COOL_GRADE)
        for triple in RGB_TRIPLES:
            for channel, column in enumerate(triple):
                multiplier[:, column] = 1 + (COOL_GRADE['rgb'][channel] - 1) * cool
        regions = list(PROBE_GAIN_REGIONS) + list(WARM_GAIN_REGIONS)
        weights = [(region['gain'] - 1) * weight(region) for region in regions]
        for region, w in zip(regions, weights):
            tint = region.get('tint', (1.0, 1.0, 1.0))
            for triple in RGB_TRIPLES:
                for channel, column in enumerate(triple):
                    multiplier[:, column] += w * tint[channel]
        multiplier[~referenced] = 1.0
        gain = multiplier.max(axis=1)
        selected = np.flatnonzero(gain > 1.0)
        if not len(selected):
            continue
        changed = data.astype(np.float64).copy()
        changed[selected] *= multiplier[selected]
        # Directional lobes towards each light source, sized from the added L0 light.
        for region, w in zip(regions, weights):
            if 'source_cm' not in region:
                continue
            w = np.where(referenced, w, 0.0)
            to_source = np.asarray(region['source_cm']) - world
            length = np.linalg.norm(to_source, axis=1, keepdims=True)
            direction = np.where(length > 1.0, to_source / np.maximum(length, 1.0), 0.0)
            tint = region.get('tint', (1.0, 1.0, 1.0))
            for channel in range(3):
                added_l0 = w * tint[channel] * data[:, channel]
                for axis, triple in L1_TRIPLE_FOR_AXIS.items():
                    changed[:, RGB_TRIPLES[triple][channel]] += DIRECTIONALITY * added_l0 * direction[:, axis]
        changed = changed.astype('<f4')
        assert np.isfinite(changed).all() and np.all(changed[:, 3] == 0)
        unselected = np.ones(count, bool); unselected[selected] = False
        assert changed[unselected].tobytes() == data[unselected].tobytes()
        new_raw = changed.astype('<f4').tobytes()
        stem = re.sub(r'\.[0-9a-f]{16}\.gz$', '', spec['Binary'])
        member = stem + '.' + hashlib.sha256(new_raw).hexdigest()[:16] + '.bin'
        extra[member] = new_raw
        new_spec = copy.deepcopy(spec)
        new_spec['Binary'] = member[:-4] + '.gz'
        quads = changed.reshape(-1, 4)
        new_spec['Min'], new_spec['Max'] = quads.min(0).astype(float).tolist(), quads.max(0).astype(float).tolist()
        level['Texture'][key] = new_spec
        sectors.append({'texture': key, 'records': count, 'changed_records': len(selected),
                        'gain_max': float(gain[selected].max()), 'member': member})
    return {'method': 'scalar gain of whole 28-float probe records (LDIAG1-verified); warm regions tinted per assumed RGB triple',
            'regions': PROBE_GAIN_REGIONS, 'tinted_regions': WARM_GAIN_REGIONS,
            'cool_grade': COOL_GRADE, 'directionality': DIRECTIONALITY, 'l1_order': 'Y, Z, X (N14 game diagnostic)',
            'sectors': sectors, 'unchanged': 'positions, cell indices/states, visibility atlas, EV100 tags, USE_RELIGHTING'}


def apply_scene(level, archive, extra):
    """Mutate level and fill extra with new buffers. archive reads existing part buffers and probes."""
    assert EMITTER_TEMPLATE in level['Material'] and LAMP_OBJECT in level['Texture']
    assert level['Material'][EMITTER_TEMPLATE]['Effect'] == 'simplepbr_CLOD.fx#5577a34f3013fe36'
    assert not any(k.startswith(OLD_PREFIXES) for s in ('Model', 'Texture', 'Light', 'Material', 'Object') for k in level[s])
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
        moved = p + n * OFFSET_CM
        _add_emitter(level, extra, name, moved, n, uv, ix, _planar_uv7(moved), PREFIX + 'emit_' + key)
        overlays.append({'model': name, 'source': source, 'emitter': key, 'vertices': len(p), 'triangles': len(ix) // 3})
    reflections = _cornice_reflections(level, archive, extra)
    windows = _lit_windows(level, archive, extra)
    probe = _probe_gain(level, archive, extra)
    return {
        'revision': REVISION,
        'emitter_template': EMITTER_TEMPLATE,
        'emitter_binding': {'userdata': LAMP_USERDATA, 'object_name_texture_from': LAMP_OBJECT, 'uv7': 'independent, inside [0.03, 0.97]'},
        'emitters': {k: {'colour_linear': c, 'intensity': i} for k, (c, i) in EMITTERS.items()},
        'overlays': overlays,
        'cornice_reflections': reflections,
        'lit_windows': windows,
        'probe_gain': probe,
        'lights_added': 0,
        'previous_game_results': [
            'N4 and its 100x saturated-colour light diagnostic: added SPOT/AREA lights show nothing in Blacktop.',
            'N5/N6: scoreboard-shader surfaces render but look flat; transparent halo cards look wrong.',
            'LDIAG1: same-name-texture-bound lamp emitter glows with bloom; unbound does not; probe gain lights floor, static board and players.',
            'N7: emitters glow with bloom and the court is lit; fence LED strips unwanted; tall floodlight too bright.'],
        'unchanged': 'All pre-existing models, objects, materials and lights; probe data only scaled inside the gain regions.',
        'unverified': 'Large warm interior/glazing emitters; warm probe tint relies on an assumed RGB record layout.',
    }


# Fake reflections of the Chilis letters on the brushed-metal cornice rails
# (replay shows them via screen-space reflections; live play does not). The
# rails are an X extrusion, so each court-facing profile segment becomes an
# exact quad over the full rail width, offset 0.3 cm. A clone of the native
# textured-emission sconce material (same simplepbr_CLOD lightmap family,
# AlwaysEmit, EmissiveAlbedoMap) carries a blurred letter/pepper strip; the
# albedo is the rail colour so the overlay is invisible where nothing reflects.
CORNICE_PART = 'zgc_r03:part-0105'
LETTER_PARTS = {'zgc_r03:part-0439': (255, 105, 28), 'zgc_r03:part-0446': (120, 255, 80)}
SCONCE_MATERIAL = 'light_lampsconce_swirls:light_lampsconce_swirls_mat'
# rail band -> (EmissiveIntensity, blur sigma cm): nearer rails reflect brighter and sharper.
RAIL_BANDS = {'below': (1600.0, 7.0), 'above_1': (2400.0, 6.0), 'above_2': (1500.0, 8.0), 'above_3': (900.0, 10.0)}


def _world(points):
    return np.c_[-points[:, 0], points[:, 1], -points[:, 2]]


def _reflection_strip(level, archive, x0, x1, sigma_cm, width=1024):
    """Area-weighted letter coverage along world X, Gaussian blurred, coloured."""
    xs = x0 + (np.arange(width) + 0.5) / width * (x1 - x0)
    rgb = np.zeros((width, 3))
    for part, colour in LETTER_PARTS.items():
        model = level['Model'][part]
        p = _world(decode_attribute(archive, model, 'POSITION0')[:, :3].astype(float))
        ix = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])), '<u2').reshape(-1, 3)
        area = 0.5 * np.linalg.norm(np.cross(p[ix[:, 1]] - p[ix[:, 0]], p[ix[:, 2]] - p[ix[:, 0]]), axis=1)
        cx = p[ix].mean(1)[:, 0]
        coverage = np.exp(-0.5 * ((xs[:, None] - cx[None, :]) / sigma_cm) ** 2) @ area
        rgb += coverage[:, None] / max(coverage.max(), 1e-9) * np.asarray(colour, float)[None, :]
    rgb = np.clip(rgb, 0, 255)
    return Image.fromarray(np.repeat(rgb[None, :, :], 8, axis=0).astype(np.uint8), 'RGB')


def _cornice_reflections(level, archive, extra):
    model = level['Model'][CORNICE_PART]
    assert level['Object'][CORNICE_PART]['Matrix'] == ROTATED
    p = _world(decode_attribute(archive, model, 'POSITION0')[:, :3].astype(float))
    n = _world(decode_normals(decode_attribute(archive, model, 'TANGENTFRAME0')))
    ix = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])), '<u2').reshape(-1, 3)
    x0, x1 = float(p[:, 0].min()), float(p[:, 0].max())
    face_n = n[ix].mean(1)
    face_n /= np.linalg.norm(face_n, axis=1, keepdims=True)
    centre = p[ix].mean(1)
    segments = {}
    for tri, fn, c in zip(ix, face_n, centre):
        facing_court = fn[2] < -0.3
        if c[1] > 430 and facing_court and fn[1] <= 0.35:
            band = 'above_1' if c[1] < 446 else ('above_2' if c[1] < 456 else 'above_3')
        elif c[1] < 330 and facing_court and fn[1] >= 0.3:
            band = 'below'
        else:
            continue
        yz = {(round(float(p[v, 1]), 2), round(float(p[v, 2]), 2)) for v in tri}
        if len(yz) != 2:
            continue   # not an X-extruded profile face
        key = tuple(sorted(yz))
        segments.setdefault(band, {}).setdefault(key, []).append(fn)
    assert segments, 'No court-facing cornice faces found'
    base = level['Material'][SCONCE_MATERIAL]
    rail_mat = level['Material'][model['Prim'][0]['Material']]
    _, albedo, _ = native_textures.encode(Image.new('RGB', (8, 8), (178, 180, 181)), extra)
    _, metal, _ = native_textures.encode(Image.new('RGB', (8, 8), (235, 235, 235)), extra, linear=True)
    for name in [k for k in extra if k.endswith('.tld')]:
        extra.pop(name)
    level['Texture'][PREFIX + 'tex_cornice_albedo'] = albedo
    level['Texture'][PREFIX + 'tex_cornice_metal'] = metal
    report = {}
    for band, segs in segments.items():
        intensity, sigma = RAIL_BANDS[band]
        _, strip, _ = native_textures.encode(_reflection_strip(level, archive, x0, x1, sigma), extra)
        for name in [k for k in extra if k.endswith('.tld')]:
            extra.pop(name)
        level['Texture'][PREFIX + 'tex_reflect_' + band] = strip
        mat = copy.deepcopy(base)
        mat['Resource'] = {'AlbedoMap': {'Pixelmap': PREFIX + 'tex_cornice_albedo'},
                           'EmissiveAlbedoMap': {'Pixelmap': PREFIX + 'tex_reflect_' + band},
                           'MetalMap': {'Pixelmap': PREFIX + 'tex_cornice_metal'},
                           'NormalAndRoughMap': copy.deepcopy(rail_mat['Resource']['NormalAndRoughMap'])}
        mat['Parameter'].update(EmissiveIntensity=intensity, EmissiveTint=[1.0, 1.0, 1.0], AlwaysEmit=1)
        level['Material'][PREFIX + 'reflect_' + band] = mat
        positions, normals, uv0, indices = [], [], [], []
        for (a, b), fns in segs.items():
            fn = np.mean(fns, axis=0); fn /= np.linalg.norm(fn)
            quad = [np.array([x0, *a]), np.array([x1, *a]), np.array([x1, *b]), np.array([x0, *b])]
            quad = [q + fn * 0.3 for q in quad]
            start = len(positions)
            positions += quad
            normals += [fn] * 4
            uv0 += [(0.002, 0.5), (0.998, 0.5), (0.998, 0.5), (0.002, 0.5)]
            tri = [(0, 1, 2), (0, 2, 3)]
            if np.dot(np.cross(quad[1] - quad[0], quad[2] - quad[0]), fn) < 0:
                tri = [(0, 2, 1), (0, 3, 2)]
            indices += [start + i for t in tri for i in t]
        positions, normals = np.array(positions), np.array(normals)
        model_p, model_n = _world(positions), _world(normals)   # world -> model is the same flip
        _add_emitter(level, extra, PREFIX + 'cornice-' + band, model_p, model_n, np.array(uv0, float),
                     np.array(indices), _planar_uv7(model_p), PREFIX + 'reflect_' + band)
        report[band] = {'faces': len(segs), 'intensity': intensity, 'blur_sigma_cm': sigma}
    return {'source': CORNICE_PART, 'material_template': SCONCE_MATERIAL, 'world_x_range': [x0, x1], 'bands': report}


# Lit office windows (N16). The on-site night photo shows the surrounding office
# towers with a scattering of lit windows; the skyline and LINK models exist, so
# their glazing gets an offset emissive skin with a per-building window grid.
# All glazing parts of a building share one world-space mapping so windows line
# up across the glass / glass_dark / glass_light panels.
WINDOW_BUILDINGS = {
    'link': (('zgc_r03:part-0008', 'zgc_r03:part-0006'), 5000.0, 400.0, 11),
    'blue_white': (('zgc_r03:part-0315', 'zgc_r03:part-0316', 'zgc_r03:part-0317'), 8000.0, 380.0, 12),
    'curved_green': (('zgc_r03:part-0323', 'zgc_r03:part-0324', 'zgc_r03:part-0325'), 8000.0, 380.0, 13),
    'ifc': (('zgc_r03:part-0396', 'zgc_r03:part-0397', 'zgc_r03:part-0398'), 8000.0, 380.0, 14),
    'new_oriental': (('zgc_r03:part-0406', 'zgc_r03:part-0407', 'zgc_r03:part-0408'), 8000.0, 380.0, 15),
    'new_zhongguan': (('zgc_r03:part-0416', 'zgc_r03:part-0417', 'zgc_r03:part-0418'), 8000.0, 380.0, 16),
    'sinosteel': (('zgc_r03:part-0428',), 8000.0, 380.0, 17),
}
WINDOW_COLS, WINDOW_CELL_CM, WINDOW_SPAN_CM, LIT_FRACTION = 64, 8, 9600.0, 0.2
WINDOW_COLOURS = [(255, 232, 196), (246, 244, 236), (214, 228, 255)]   # warm, neutral, fluorescent


def _window_texture(rows, seed):
    rng = np.random.default_rng(seed)
    cell = WINDOW_CELL_CM
    img = np.zeros((rows * cell, WINDOW_COLS * cell, 3))
    lit = rng.random((rows, WINDOW_COLS)) < LIT_FRACTION
    # Offices light up in runs along a floor, not as isolated random cells.
    for r in range(rows):
        for c in range(1, WINDOW_COLS):
            if lit[r, c - 1] and rng.random() < 0.45:
                lit[r, c] = True
    colour = rng.choice(len(WINDOW_COLOURS), size=(rows, WINDOW_COLS), p=[0.45, 0.3, 0.25])
    level = rng.uniform(0.45, 1.0, size=(rows, WINDOW_COLS))
    for r in range(rows):
        for c in range(WINDOW_COLS):
            if lit[r, c]:
                y0, x0 = (rows - 1 - r) * cell, c * cell
                # glazing in the lower ~65% of each floor; the upper band is the dark spandrel
                img[y0 + 3:y0 + cell - 1, x0 + 1:x0 + cell - 1] = np.asarray(WINDOW_COLOURS[colour[r, c]]) * level[r, c]
    height = 1 << int(np.ceil(np.log2(max(4, rows * cell))))
    out = np.zeros((height, WINDOW_COLS * cell, 3), np.uint8)
    out[height - rows * cell:] = img.astype(np.uint8)
    return Image.fromarray(out, 'RGB'), int(lit.sum()), rows * WINDOW_COLS, height


def _lit_windows(level, archive, extra):
    base = level['Material'][SCONCE_MATERIAL]
    rail_mat = level['Material'][level['Model'][CORNICE_PART]['Prim'][0]['Material']]
    _, glass, _ = native_textures.encode(Image.new('RGB', (8, 8), (38, 46, 58)), extra)
    _, metal, _ = native_textures.encode(Image.new('RGB', (8, 8), (40, 40, 40)), extra, linear=True)
    for name in [k for k in extra if k.endswith('.tld')]:
        extra.pop(name)
    level['Texture'][PREFIX + 'tex_night_glass'] = glass
    level['Texture'][PREFIX + 'tex_glass_metal'] = metal
    report = {}
    for building, (parts, intensity, floor_cm, seed) in WINDOW_BUILDINGS.items():
        decoded = []
        for part in parts:
            model = level['Model'][part]
            assert level['Object'][part]['Matrix'] == ROTATED and len(model['Prim']) == 1, part
            p = decode_attribute(archive, model, 'POSITION0')[:, :3].astype(float)
            n = decode_normals(decode_attribute(archive, model, 'TANGENTFRAME0'))
            ix = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])), '<u2').astype(np.int64)
            decoded.append((part, p, n, ix))
        allw = _world(np.vstack([d[1] for d in decoded]))
        lo, hi = allw.min(0), allw.max(0)
        rows = int(np.ceil((hi[1] - lo[1]) / floor_cm))
        assert max(hi[0] - lo[0], hi[2] - lo[2]) < WINDOW_SPAN_CM and rows <= 64, building
        image, lit, cells, height = _window_texture(rows, seed)
        _, spec, _ = native_textures.encode(image, extra)
        for name in [k for k in extra if k.endswith('.tld')]:
            extra.pop(name)
        level['Texture'][PREFIX + 'tex_windows_' + building] = spec
        mat = copy.deepcopy(base)
        mat['Resource'] = {'AlbedoMap': {'Pixelmap': PREFIX + 'tex_night_glass'},
                           'EmissiveAlbedoMap': {'Pixelmap': PREFIX + 'tex_windows_' + building},
                           'MetalMap': {'Pixelmap': PREFIX + 'tex_glass_metal'},
                           'NormalAndRoughMap': copy.deepcopy(rail_mat['Resource']['NormalAndRoughMap'])}
        mat['Parameter'].update(EmissiveIntensity=intensity, EmissiveTint=[1.0, 1.0, 1.0], AlwaysEmit=1)
        level['Material'][PREFIX + 'windows_' + building] = mat
        v_scale = rows * floor_cm * height / (rows * WINDOW_CELL_CM)
        for part, p, n, ix in decoded:
            w, wn = _world(p), _world(n)
            distance = float(np.linalg.norm((w.min(0) + w.max(0)) / 2))
            offset = max(0.4, distance / 2500.0)   # keep depth separation at skyline distance
            moved = w + wn * offset
            horizontal = np.where(np.abs(wn[:, 0]) > np.abs(wn[:, 2]), moved[:, 2] - lo[2], moved[:, 0] - lo[0])
            u = np.clip(horizontal / WINDOW_SPAN_CM, 0.001, 0.999)
            v = np.clip(1.0 - (moved[:, 1] - lo[1]) / v_scale, 0.001, 0.999)
            model_p, model_n = _world(moved), _world(wn)
            name = PREFIX + 'windows-' + part.split(':')[1]
            _add_emitter(level, extra, name, model_p, model_n, np.c_[u, v], ix, _planar_uv7(model_p), PREFIX + 'windows_' + building)
        report[building] = {'parts': list(parts), 'floors': rows, 'lit_windows': lit, 'cells': cells,
                            'intensity': intensity, 'texture_height': height}
    return report
