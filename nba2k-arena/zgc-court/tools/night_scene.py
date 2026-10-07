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
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

import native_textures
from iff_codec import decode_attribute, decode_normals, make_static_model, resolve_binary, texture_density

REVISION = 'N39'
PREFIX = 'zgc_n16:'
# LDIAG2 surface-lighting test tiles (tools/lightmap_diag2.py); set False for production builds.
LIGHTMAP_DIAG = False
OLD_PREFIXES = ('zgc_n4:', 'zgc_n5:', 'zgc_n6:', 'zgc_probe_emit:', 'zgc_diag_receiver:', 'zgc_n7:', 'zgc_n8:', 'zgc_n9:', 'zgc_n10:', 'zgc_n11:', 'zgc_n12:', 'zgc_n13:', 'zgc_n14:', 'zgc_n15:', PREFIX)
EMITTER_TEMPLATE = 'light_lamppost_genericb:light_mat'
LAMP_OBJECT = ('park_streetball_a_master@park_rucker_ext_shared@GameObjects@'
               'GameObjectGroup_121@light_lamppost_genericb_19:light_lamppost_genericb_low')
LAMP_USERDATA = 'AACAPwAAAAAAAAAAAAAAAEAAEFBAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
ROTATED = [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1]
OFFSET_CM = 1.0   # N29: 0.4 cm skins z-fought at court distance

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
    'gold_script': ([1.0, 0.72, 0.38], 2600.0),
}
# N18: Chili's brand red (was orange), a cooler green pepper, warm-white side strips
# at a third of the old level (they read as cheap white tubes).
EMITTERS.update(chilis_letters=([1.0, 0.075, 0.035], 21000.0), logo_letters=([1.0, 0.075, 0.035], 15000.0),
                chilis_pepper=([0.32, 1.0, 0.14], 24000.0), warm_strip=([1.0, 0.8, 0.56], 9500.0))
# N19: the big letters read as solid red plastic. Glowing acrylic channel letters are
# three-layered: a near-white hot trim at the front edge, a light coral face that
# blooms red, and deep red light leaking out of the side returns.
EMITTERS.update(chilis_letters=([1.0, 0.3, 0.2], 26000.0), warm_strip=([1.0, 0.8, 0.56], 6000.0),
                letter_rim=([1.0, 0.82, 0.72], 32000.0), letter_return=([1.0, 0.06, 0.03], 7000.0))
EMITTERS.update(a_sign=([0.86, 0.94, 1.0], 3500.0))   # N25: the A tubes read as overexposed white tape
# N26 from the night reference photo (public/references/40.jpg): the big letters are orange-red
# neon tubes with a hot core, CAFE&BAR / EST.1975 glow warm white (not dim gold).
EMITTERS.update(chilis_letters=([1.0, 0.3, 0.07], 30000.0), logo_letters=([1.0, 0.3, 0.07], 18000.0),
                letter_rim=([1.0, 0.62, 0.36], 30000.0), letter_return=([1.0, 0.1, 0.02], 6000.0),
                gold_script=([1.0, 0.9, 0.74], 9000.0))

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
    'zgc_r03:part-0438': 'letter_rim',       # court facade channel letters front trim outline
    'zgc_r03:part-0440': 'letter_return',    # court facade channel letters side returns
    'zgc_r03:part-0083': 'gold_script',      # CAFE AND BAR, gold letters on the sign panel
    'zgc_r03:part-0089': 'gold_script',      # EST 1975
}   # N18: the interior back plane / timber planes moved to chilis_storefront (textured)

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
    # N24: 1.6 -> 1.25, the yellow half read evenly lit like dusk; light should come from the practicals.
    {'label': 'court_base_south', 'center_cm': [0.0, 150.0, -700.0], 'inner_radius_cm': 600.0, 'outer_radius_cm': 1200.0, 'gain': 1.25},
    {'label': 'court_base_north', 'center_cm': [0.0, 150.0, 700.0], 'inner_radius_cm': 600.0, 'outer_radius_cm': 1200.0, 'gain': 1.25},
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
              'rgb': (0.58, 0.76, 1.10)}   # N24: deeper blue night so the warm practicals stand out
# Directional baked light (N15). Probe records are 9-coefficient RGB SH: L0 RGB,
# a zero pad, then eight interleaved RGB triples. The N14 in-game diagnostic
# showed triple 0 lighting up-facing surfaces, i.e. the usual real-SH order
# L1 = (Y, Z, X). For each light region with a source, the added L0 light gets
# an L1 lobe pointing from the probe towards the source; DIRECTIONALITY is the
# L1/L0 ratio (0.7 leaves the far side at about 1/8 of the lit side, not black).
DIRECTIONALITY = 0.85
L1_TRIPLE_FOR_AXIS = {1: 1, 2: 2, 0: 3}   # world axis (x=0, y=1, z=2) -> index into RGB_TRIPLES
RGB_TRIPLES = [(0, 1, 2)] + [(4 + 3 * k, 5 + 3 * k, 6 + 3 * k) for k in range(8)]
# N17: Blender/Cycles-baked night light (bake/bake_probes.py, one panorama per
# light group per probe, projected to SH9 in game axes) replaces the hand-placed
# A sign / floodlight / Chilis / boots gain regions: walls, fences and the door
# frame now shadow, and light bounces. Each group is added on top of the
# (cool-graded, court-base) ambient with a weight calibrated so its overall
# level matches the N16 regions it replaces (tools/calibrate_bake.py). Only L0
# and L1 are imported (L2 record order is not proven in game); the added L1 is
# capped at BAKE_L1_MAX * L0, the most an SH irradiance lookup can take without
# going negative on the far side (N16 used 0.85 too).
BAKED_PROBES = Path(__file__).resolve().parent.parent / 'bake' / 'output' / 'probe_sh.ndjson'
BAKE_WEIGHTS = {'a_signs': 106.4, 'chilis': 6.094, 'boots': 36.4, 'floodlight': 18.44}   # tools/calibrate_bake.py
# N22 added fixtures (tools/night_lights.py) have no N16 counterpart to calibrate against; they
# use the Chilis weight, whose level is set by its 2500 W area light, i.e. the same per-watt scale.
BAKE_WEIGHTS.update(festoon=24.0, plaza_lamps=9.0)
# N25: the baked tall floodlight (a 70 degree spot from 10 m) laid one big flat pool over
# half the court and washed out the hierarchy; cut to a third. Festoon x2.3 so its warm
# band actually reaches the floor under the bulbs (source and effect line up).
BAKE_WEIGHTS.update(floodlight=6.0, festoon=55.0)
# N26: the invented N22 plaza lamps are gone (the scene's own posts are lit instead).
BAKE_WEIGHTS.pop('plaza_lamps')
BAKE_WEIGHTS.update(plaza_posts=9.0, vending=9.0)   # festoon x4: at the per-watt scale its warm wash along the fence was invisible
BAKE_WEIGHTS.update(floodlight=0.0)   # N27: the floodlight is a real-time light now
BAKE_WEIGHTS.update(a_signs=40.0)   # N28: the A signs are real-time; the bake stays as a soft fill
BAKE_WEIGHTS.update(floodlight=6.0)   # N29: the floodlight is baked again (N25 level)
BAKE_L1_MAX = 0.85
# The bake covers probes near the lights (plus rings from bake/extend_probes.py);
# its light fades out over BAKE_EDGE_FADE_CM from the nearest referenced probe
# that was not baked, so the edge of the baked set never shows as a step.
# Probes below BAKE_GROUND_Y_CM (the -8 m layer under the court) never see the
# lights and are not baked; they do not count as an edge.
BAKE_EDGE_FADE_CM = (400.0, 1200.0)
BAKE_GROUND_Y_CM = -100.0
# N22 key light. Every added night light is baked (probes + surface maps), so nothing
# casts real-time shadows except the single directional Sun, which the night base dims
# to 1/200 of day. Raised to ~1/70 of day, neutral-cool, and aimed from the tall
# floodlight's side at ~43 degrees, it gives players, the hoop, fence posts and rails
# soft real-time shadows (DPCF penumbra kept). VC_Direction's convention is not
# proven: with Vx != 0 a flipped convention only mirrors the shadows in x; the
# elevation (light from above) is the same either way.
# N22 result: a little brighter, still NO player shadows. At 22:00 the TIME_OF_DAY
# system has its own moon light (VC_MoonLightIntensity 1.5), which is the likely
# night shadow caster. N23 puts the Sun back to the night base (N21 look) and
# raises the TIME_OF_DAY moonlight instead (MOON_KEY).
SUN_KEY = {'Intensity': 550.0, 'Color': [0.45, 0.6, 1.0, 1.0],
           'VC_Direction': [0.195801511, -0.772746921, 0.603758276, 0.0]}
# N23 game result: no player shadows from the moonlight either (no court shows player shadows
# at night), so N24 restores the night base moonlight.
MOON_KEY = {'VC_MoonLightIntensity': 1.5, 'VC_MoonLightColor': [0.300543845, 0.55834043, 1.0, 1.0]}
# RTL diagnostic (docs/realtime-light-research, variant A "append"): one native SPOT,
# full official attribute set, 8 m above centre court, inside the brick-map block
# the research located around centre court. Set False for production builds.
# N23 result: neither variant A (append) nor B (word64 01->02) lit centre court. Off.
RTL_DIAG = False
# Variant B (research section 7/9): the inherited grid has a single set row, word64 = 1
# (only bit 0, the Sun). A copy with byte 256 changed 01 -> 02 tests whether that word is
# the light-set bitmask (bit 1 = the next light, i.e. the appended spot). Unverified
# single-byte perturbation of a copy; the original member stays and strip_scene restores
# the canonical entry on every rebuild.
RTL_BRICK_WORD64 = None
# N26 variant D: the level carries a LIGHTING_MOVEABLE_LIGHTS_SUPPORTED marker, so a movable
# light may take the dynamic path instead of the static LIGHT_BRICK_MAP. Same native spot,
# VC_IsMovable 1, with volumetrics on (the user asked for light shafts in the air; volumetric
# scattering only exists on real-time lights). Diagnostic, set False for production.
# N26 result: the movable spot rendered with a volumetric cone AND dynamic player shadows.
# Diagnostic retired; N27 makes the key lights real-time instead.
RTL_MOVABLE_DIAG = False
# N27 real-time key lights (all VC_IsMovable 1, world cm, aim in world space as in the
# 4 Spotlight_Court_* of the Rucker mod). The tall floodlight becomes the shadow-casting key
# light, so its baked group is dropped (no double light); the lens emitter stays.
# Intensity scale from N26: 3.6e7 at 8 m read as a clear pool, i.e. E ~ I / d^2 ~ 56.
REALTIME_LIGHTS = {
    'floodlight': {'at': (975.0, 1000.0, 420.0), 'aim': (-975.0, -1000.0, -620.0), 'intensity': 1.6e8,
                   'colour': (1.0, 0.9, 0.78), 'cone': 0.62, 'far': 3500.0, 'volumetric': 1.2},
    'chilis_door': {'at': (430.0, 300.0, 1990.0), 'aim': (0.0, -0.85, -0.53), 'intensity': 5.0e6,
                    'colour': (1.0, 0.62, 0.32), 'cone': 0.95, 'far': 1200.0, 'volumetric': 0.0},
}
# N27 game result: floodlight shadow direction right, but shadows read weak (the baked
# probe fill is too strong next to the one real-time light) and the Chili's light is not
# visible. N28: the two A signs become real-time lights too (low, grazing light from the
# side fences -> long player shadows across the court), with their baked group cut to a
# soft fill; the floodlight is stronger; the Chili's light moves to under the awning edge,
# aims out over the court end, and is 6x stronger.
REALTIME_LIGHTS['floodlight']['intensity'] = 2.6e8
REALTIME_LIGHTS['chilis_door'].update(at=(430.0, 255.0, 1975.0), aim=(0.0, -0.45, -0.89), intensity=3.0e7,
                                      cone=1.0, far=1800.0)
REALTIME_LIGHTS.update(
    a_sign_east={'at': (893.0, 205.0, 944.0), 'aim': (-1.0, -0.12, 0.0), 'intensity': 7.0e7,
                 'colour': (0.86, 0.94, 1.0), 'cone': 1.1, 'far': 2600.0, 'volumetric': 0.0},
    a_sign_west={'at': (-893.0, 205.0, 1184.0), 'aim': (1.0, -0.12, 0.0), 'intensity': 7.0e7,
                 'colour': (0.86, 0.94, 1.0), 'cone': 1.1, 'far': 2600.0, 'volumetric': 0.0})
# N28 game result: the Chili's area flickers (already before N28), 4 shadowed lights stutter.
# N29: only the two A signs stay real-time. Floodlight and Chili's go back to baked light.
# The A lights sit 35 cm in from the fence (clear of the chain-link mesh in their shadow
# map) with a narrower cone and a far plane that ends just past the far fence, so each
# shadow pass only draws the court.
for _name in ('floodlight', 'chilis_door'):
    REALTIME_LIGHTS.pop(_name)
REALTIME_LIGHTS['a_sign_east'].update(at=(858.0, 205.0, 944.0), cone=0.95, far=1900.0)
REALTIME_LIGHTS['a_sign_west'].update(at=(-858.0, 205.0, 1184.0), cone=0.95, far=1900.0)
BRICK_KEY = 'LIGHT_BRICK_MAP_GRID_RUNTIME_DATA'
BRICK_SHA256 = '331ee7990a7da5e63a86c8c7b108b7d10d330dd83e4bb227bafc70d1195eb535'
RTL_SPOT = {'Type': 'SPOT', 'Intensity': 3.6e7, 'Color': [0.82, 0.91, 1.0, 1.0], 'Attribute': {
    'VC_AimDirection': [0.0, -1.0, 0.0, 0.0], 'CONEANGLE': 0.52359879, 'PENUMBRAANGLE': 0.34906584,
    'PENUMBRAFALLOFFEXPONENT': 2.0, 'VC_MinDistance': 0.0, 'VC_Decay': 1.0, 'VC_NearPlane': 25.0,
    'VC_FarPlane': 1600.0, 'VC_SizeScale': 1.0, 'VC_BlackLight': 0.0, 'VC_NormalBias': 0.5,
    'VC_CastsShadows': 1, 'VC_FakeLineLightShadows': 0, 'VC_EnableVolumetric': 0, 'VC_CastVolumetricShadow': 0,
    'VC_FalloffExponent': 2.0, 'VC_IsNightOnly': 0, 'VC_IgnoreDynamicCasters': 0, 'VC_VolumetricIntensity': 1.0,
    'vc_ingame_light': 1, 'VC_IsMovable': 0, 'VC_IsActive': 1, 'VC_PresentationLightId': 0,
    'VC_LocatorName': 'zgc_rtl_center_spot'}, 'Translate': [0.0, 800.0, 0.0]}
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


def strip_scene(level, base_level, also_used=frozenset()):
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
    for mat in FOLIAGE_PALETTE:
        level['Material'][mat] = copy.deepcopy(base_level['Material'][mat])
    import ball_skin
    for key in [k for k in level['Texture'] if PROBE_DATA_KEY.fullmatch(k) or k in (BRICK_KEY, ball_skin.KEY)]:
        if level['Texture'][key] != base_level['Texture'][key]:
            removed.append(level['Texture'][key])
            level['Texture'][key] = copy.deepcopy(base_level['Texture'][key])
    kept = {_texture_archive_name(b) for section in ('Model', 'Texture') for v in level[section].values() for b in binaries(v)}
    # only members this tool generated may go: removed entries can also point at native members
    # that other scenes (baskets.SCNE) still use (N36 far hoop copies the basket textures)
    kept |= set(also_used)
    return {n for n in ({_texture_archive_name(b) for v in removed for b in binaries(v)} - kept) if n.startswith('zgc_')}


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


def load_baked(path=BAKED_PROBES):
    """{sector: {record id: (world_cm, {group: 9x3 radiance SH})}} or {} when there is no bake.
    Groups baked later into further probe_sh*.ndjson files (N22 lights) are merged per probe."""
    files = sorted(Path(path).parent.glob('probe_sh*.ndjson'))
    if not Path(path).exists():
        return {}
    baked = {}
    for f in files:
        for line in f.read_text(encoding='utf8').splitlines():
            if line.strip():
                row = json.loads(line)
                world, groups = baked.setdefault(row['sector'], {}).setdefault(row['id'], (row['world_cm'], {}))
                groups.update({g: np.asarray(c, float) for g, c in row['sh_rgb_9x3'].items()})
    groups = {g for rows in baked.values() for _, gs in rows.values() for g in gs}
    for rows in baked.values():
        for rid, (_, gs) in rows.items():
            assert set(gs) == groups, ('probe missing a light group', rid, sorted(groups - set(gs)))
    return baked


# N38: the far half (world z < 0, away from Chili's) read too dark. Its baked light (court
# overlay emission and probe additions) is lifted smoothly to FAR_HALF_GAIN from z -100 to
# z -700; the near half is untouched. No re-bake: the same baked groups, reweighted in space.
FAR_HALF_GAIN = 1.8
FAR_HALF_RAMP_CM = (-100.0, -700.0)


def far_half_gain(z):
    z = np.asarray(z, float)
    t = np.clip((z - FAR_HALF_RAMP_CM[0]) / (FAR_HALF_RAMP_CM[1] - FAR_HALF_RAMP_CM[0]), 0, 1)
    return 1 + (FAR_HALF_GAIN - 1) * t * t * (3 - 2 * t)


# N39 trees: background foliage (three shared materials: dark/mid/light leaves) read as one
# grey-green mass at night. (a) Wider tonal palette so the clumps separate. (b) In the probes
# around the foliage, a cool moonlight from above (lit crown tops) and a faint warm city
# bounce from below, replacing part of the flat ambient: crowns get volume. Near canopies only
# above 2.9 m so players keep their light. No geometry, no lights.
FOLIAGE_PALETTE = {'zgc_r03:material_154': (40, 66, 56),     # dark: deeper, blue-green
                   'zgc_r03:material_156': (72, 104, 62),    # mid
                   'zgc_r03:material_155': (126, 148, 78)}   # light: warm yellow-green
FOLIAGE_ZONES = [   # world cm boxes (lo, hi), soft edge, optional y fade-in (from, to)
    {'lo': (-6300, 100, -7200), 'hi': (5400, 1500, -4700), 'edge': 400.0},
    {'lo': (-7400, 100, -4500), 'hi': (-4800, 1600, 4900), 'edge': 400.0},
    {'lo': (-2150, 290, -3200), 'hi': (2050, 760, 2010), 'edge': 250.0, 'y_in': (290.0, 420.0),
     'not_xz': (-1150.0, 1150.0, -2100.0, 1900.0)},          # never over the fenced court
]
FOLIAGE_AMBIENT_KEEP = 0.8
FOLIAGE_MOON = {'rgb': (0.62, 0.78, 1.0), 'l0': 0.65, 'dir': (0.25, 0.86, -0.44)}
FOLIAGE_BOUNCE = {'rgb': (1.0, 0.6, 0.32), 'l0': 0.22, 'dir': (0.0, -1.0, 0.0)}


def foliage_weight(world):
    w = np.ones(len(world))
    total = np.zeros(len(world))
    for zone in FOLIAGE_ZONES:
        lo, hi, e = np.asarray(zone['lo'], float), np.asarray(zone['hi'], float), zone['edge']
        out = np.maximum(np.maximum(lo - world, world - hi), 0)
        d = np.sqrt((out ** 2).sum(1))
        t = np.clip(1 - d / e, 0, 1)
        wz = t * t * (3 - 2 * t)
        if 'y_in' in zone:
            y0, y1 = zone['y_in']
            ty = np.clip((world[:, 1] - y0) / (y1 - y0), 0, 1)
            wz = wz * ty * ty * (3 - 2 * ty)
        if 'not_xz' in zone:
            x0, x1, z0, z1 = zone['not_xz']
            inside = (world[:, 0] > x0) & (world[:, 0] < x1) & (world[:, 2] > z0) & (world[:, 2] < z1)
            wz = np.where(inside, 0.0, wz)
        total = np.maximum(total, wz)
    return total


def _foliage_light(data, world, referenced):
    """(count, 28) delta: ambient partly replaced by moon-from-above and bounce-from-below."""
    w = foliage_weight(world) * referenced
    delta = np.zeros((len(world), 28))
    if not w.any():
        return delta, w > 0
    l0 = np.stack([data[:, RGB_TRIPLES[0][c]] for c in range(3)], 1)
    lum = l0.mean(1)
    for triple in RGB_TRIPLES:                                   # keep part of the flat ambient
        for c in range(3):
            delta[:, triple[c]] += (FOLIAGE_AMBIENT_KEEP - 1) * w * data[:, triple[c]]
    for light in (FOLIAGE_MOON, FOLIAGE_BOUNCE):
        d = np.asarray(light['dir'], float); d /= np.linalg.norm(d)
        for c in range(3):
            add = w * light['l0'] * lum * light['rgb'][c]
            delta[:, RGB_TRIPLES[0][c]] += add
            for axis, triple in L1_TRIPLE_FOR_AXIS.items():
                delta[:, RGB_TRIPLES[triple][c]] += BAKE_L1_MAX * add * d[axis]
    return delta, w > 0


def apply_foliage_palette(level, extra):
    out = {}
    for mat, srgb in FOLIAGE_PALETTE.items():
        _, spec, _ = native_textures.encode(Image.new('RGB', (8, 8), srgb), extra)
        for name in [k for k in extra if k.endswith('.tld')]:
            extra.pop(name)
        key = PREFIX + 'tex_foliage_' + mat.split('_')[-1]
        level['Texture'][key] = spec
        level['Material'][mat]['Resource']['AlbedoMap'] = {'Pixelmap': key}
        out[mat] = srgb
    return out


def _baked_addition(rows, world, count, weights=None, referenced=None):
    """(count, 28) float64 to add to the probe records, and the mask of baked records."""
    weights = BAKE_WEIGHTS if weights is None else weights
    add = np.zeros((count, 28))
    mask = np.zeros(count, bool)
    for rid, (world_cm, groups) in rows.items():
        assert np.allclose(world[rid], world_cm, atol=1.0), (rid, world[rid], world_cm)
        total = sum(weights[g] * c for g, c in groups.items() if g in weights)   # 9 x 3, standard order, game axes
        total = total * float(far_half_gain(world_cm[2]))
        for channel in range(3):
            l0 = max(total[0, channel], 0.0)
            l1 = total[1:4, channel]
            norm = np.linalg.norm(l1)
            if norm > BAKE_L1_MAX * l0:
                l1 = l1 * (BAKE_L1_MAX * l0 / norm) if norm > 0 else l1
            add[rid, RGB_TRIPLES[0][channel]] = l0
            for k in range(3):   # standard L1 order (y, z, x) is the game's triple order 1..3
                add[rid, RGB_TRIPLES[1 + k][channel]] = l1[k]
        mask[rid] = True
    if referenced is not None and mask.any():
        outside = world[referenced & ~mask & (world[:, 1] >= BAKE_GROUND_Y_CM)]
        inner, outer = BAKE_EDGE_FADE_CM
        for rid in np.flatnonzero(mask):
            d = np.sqrt(((outside - world[rid]) ** 2).sum(1).min()) if len(outside) else np.inf
            t = np.clip((d - inner) / (outer - inner), 0, 1)
            add[rid] *= t * t * (3 - 2 * t)
    return add, mask


def _probe_gain(level, archive, extra, baked=None):
    """Scale whole probe records near the court and add baked night light; returns an audit."""
    baked = load_baked() if baked is None else baked
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
        rows = baked.get(prefix, {})
        if baked:
            regions = [r for r in PROBE_GAIN_REGIONS if 'source_cm' not in r]   # court base only
        else:
            regions = list(PROBE_GAIN_REGIONS) + list(WARM_GAIN_REGIONS)
        weights = [(region['gain'] - 1) * weight(region) for region in regions]
        for region, w in zip(regions, weights):
            tint = region.get('tint', (1.0, 1.0, 1.0))
            for triple in RGB_TRIPLES:
                for channel, column in enumerate(triple):
                    multiplier[:, column] += w * tint[channel]
        multiplier[~referenced] = 1.0
        gain = multiplier.max(axis=1)
        added, baked_mask = _baked_addition(rows, world, count, referenced=referenced)
        baked_mask &= referenced
        foliage, foliage_mask = _foliage_light(data.astype(np.float64), world, referenced)
        selected = np.flatnonzero((gain > 1.0) | baked_mask | foliage_mask)
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
        changed[baked_mask] += added[baked_mask]
        changed[foliage_mask] += foliage[foliage_mask]
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
        sectors.append({'texture': key, 'records': count, 'changed_records': len(selected), 'baked_records': int(baked_mask.sum()),
                        'foliage_records': int(foliage_mask.sum()),
                        'gain_max': float(gain[selected].max()), 'member': member})
    method = ('cool grade + court base gain, plus Blender/Cycles-baked night light (L0 + capped L1)' if baked else
              'scalar gain of whole 28-float probe records (LDIAG1-verified); warm regions tinted per assumed RGB triple')
    return {'method': method,
            'baked': {'file': str(BAKED_PROBES.name), 'weights': BAKE_WEIGHTS, 'l1_max': BAKE_L1_MAX, 'edge_fade_cm': BAKE_EDGE_FADE_CM,
                      'records': sum(len(r) for r in baked.values())} if baked else None,
            'regions': PROBE_GAIN_REGIONS if not baked else [r for r in PROBE_GAIN_REGIONS if 'source_cm' not in r],
            'tinted_regions': WARM_GAIN_REGIONS if not baked else [],
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
    probe['foliage_palette'] = apply_foliage_palette(level, extra)
    import chilis_storefront, court_surface
    def part_geometry(source):
        model = level['Model'][source]
        assert len(model['Prim']) == 1 and level['Object'][source]['Matrix'] == ROTATED, source
        p = decode_attribute(archive, model, 'POSITION0')[:, :3].astype(float) * np.array([-1.0, 1.0, -1.0])
        n = decode_normals(decode_attribute(archive, model, 'TANGENTFRAME0')) * np.array([-1.0, 1.0, -1.0])
        ix = np.frombuffer(archive.read(resolve_binary(archive, model['IndexBuffer']['Binary'])), '<u2').astype(np.int64)
        return p, n, ix
    storefront = chilis_storefront.apply(level, archive, extra, PREFIX, _add_emitter, _emitter_material,
                                         EMITTER_TEMPLATE, SCONCE_MATERIAL, part_geometry)
    surface = court_surface.apply(level, archive, extra, PREFIX, _add_emitter, SCONCE_MATERIAL, LAMP_OBJECT, BAKE_WEIGHTS)
    sun = level['Light']['Sun']
    assert sun['Type'] == 'DIRECTIONAL' and sun['Attribute']['VC_CastsShadows'] == 1
    sun['Intensity'] = SUN_KEY['Intensity']
    sun['Color'] = SUN_KEY['Color'][:]
    sun['Attribute']['VC_Direction'] = SUN_KEY['VC_Direction'][:]
    level['Object']['TIME_OF_DAY']['Attribute'].update(copy.deepcopy(MOON_KEY))
    if RTL_MOVABLE_DIAG:
        spot = copy.deepcopy(RTL_SPOT)
        spot['Attribute'].update(VC_IsMovable=1, VC_EnableVolumetric=1, VC_CastVolumetricShadow=1,
                                 VC_VolumetricIntensity=3.0, VC_LocatorName='zgc_rtl_movable_spot')
        level['Light'][PREFIX + 'rtl_movable_spot'] = spot
    for name, light in REALTIME_LIGHTS.items():
        spot = copy.deepcopy(RTL_SPOT)
        spot.update(Intensity=light['intensity'], Color=list(light['colour']) + [1.0], Translate=list(light['at']))
        aim = np.array(light['aim'], float)
        spot['Attribute'].update(VC_IsMovable=1, VC_AimDirection=[float(v) for v in aim / np.linalg.norm(aim)] + [0.0],
                                 CONEANGLE=light['cone'], VC_FarPlane=light['far'],
                                 VC_EnableVolumetric=int(light['volumetric'] > 0),
                                 VC_CastVolumetricShadow=int(light['volumetric'] > 0),
                                 VC_VolumetricIntensity=light['volumetric'] or 1.0,
                                 VC_LocatorName='zgc_rt_' + name)
        level['Light'][PREFIX + 'rt_' + name] = spot
    if RTL_DIAG:
        level['Light'][PREFIX + 'rtl_center_spot'] = copy.deepcopy(RTL_SPOT)   # appended after Sun
        if RTL_BRICK_WORD64 is not None:
            spec = level['Texture'][BRICK_KEY]
            grid = archive.read(_texture_archive_name(spec['Binary']))
            assert hashlib.sha256(grid).hexdigest() == BRICK_SHA256 and grid[256:260] == bytes([1, 0, 0, 0])
            patched = grid[:256] + bytes([RTL_BRICK_WORD64]) + grid[257:]
            member = 'zgc_rtl_light_brick_diag.' + hashlib.sha256(patched).hexdigest()[:16] + '.bin'
            extra[member] = patched
            spec = copy.deepcopy(spec)
            spec['Binary'] = member[:-4] + '.gz'
            level['Texture'][BRICK_KEY] = spec
    import scene_details, night_lights
    lights = night_lights.apply(level, archive, extra, PREFIX, _add_emitter, _emitter_material, EMITTER_TEMPLATE, SCONCE_MATERIAL)
    per_unit = court_surface.PEAK_EMISSION / surface['emission_scale_linear']
    details = {'chilis_entry_floor': scene_details.entry_floor(level, archive, extra, PREFIX, _add_emitter, SCONCE_MATERIAL,
                                                               part_geometry, BAKE_WEIGHTS, per_unit),
               'boots_windows': scene_details.boots_windows(level, archive, extra, PREFIX, _add_emitter, SCONCE_MATERIAL,
                                                            part_geometry)}
    import ball_skin
    if ball_skin.ENABLED:
        ball = ball_skin.build(level, copy.deepcopy(level['Texture'][ball_skin.KEY]), archive, extra)
        ball.pop('preview')
        details['ball'] = ball
    import baked_surfaces
    details['baked_surfaces'] = baked_surfaces.apply(level, archive, extra, PREFIX, _add_emitter, SCONCE_MATERIAL,
                                                     part_geometry, BAKE_WEIGHTS, per_unit)
    import scene_props
    details['tree_glow'] = scene_props.tree_glow(level, archive, extra, PREFIX, _add_emitter, SCONCE_MATERIAL,
                                                 part_geometry, BAKE_WEIGHTS, per_unit)
    details['props'] = scene_props.props(level, extra, PREFIX, _add_emitter, SCONCE_MATERIAL)
    details['far_court'] = scene_props.far_court(level, extra, PREFIX, _add_emitter, SCONCE_MATERIAL)
    # N37: the far hoop copy is gone. N36 game result: the gameplay basket1 IS drawn at the far
    # end in half- and full-court games, so the copy overlapped it. Nothing goes on the far hoop.
    diag = None
    if LIGHTMAP_DIAG:
        import lightmap_diag2
        diag = lightmap_diag2.add_tiles(level, archive, extra, PREFIX, _add_emitter, EMITTER_TEMPLATE, LAMP_OBJECT, SCONCE_MATERIAL)
    return {
        'revision': REVISION,
        'emitter_template': EMITTER_TEMPLATE,
        'emitter_binding': {'userdata': LAMP_USERDATA, 'object_name_texture_from': LAMP_OBJECT, 'uv7': 'independent, inside [0.03, 0.97]'},
        'emitters': {k: {'colour_linear': c, 'intensity': i} for k, (c, i) in EMITTERS.items()},
        'overlays': overlays,
        'cornice_reflections': reflections,
        'lit_windows': windows,
        'probe_gain': probe,
        'lightmap_diag2': diag,
        'chilis_storefront': storefront,
        'court_surface': surface,
        'details': details,
        'added_lights': lights,
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
    'link': (('zgc_r03:part-0008', 'zgc_r03:part-0006'), 2000.0, 400.0, 11),   # N25: read as white holes above Chilis
    'blue_white': (('zgc_r03:part-0315', 'zgc_r03:part-0316', 'zgc_r03:part-0317'), 4500.0, 380.0, 12),
    'curved_green': (('zgc_r03:part-0323', 'zgc_r03:part-0324', 'zgc_r03:part-0325'), 4500.0, 380.0, 13),
    'ifc': (('zgc_r03:part-0396', 'zgc_r03:part-0397', 'zgc_r03:part-0398'), 4500.0, 380.0, 14),
    'new_oriental': (('zgc_r03:part-0406', 'zgc_r03:part-0407', 'zgc_r03:part-0408'), 4500.0, 380.0, 15),
    'new_zhongguan': (('zgc_r03:part-0416', 'zgc_r03:part-0417', 'zgc_r03:part-0418'), 4500.0, 380.0, 16),
    'sinosteel': (('zgc_r03:part-0428',), 4500.0, 380.0, 17),
}
WINDOW_COLS, WINDOW_CELL_CM, WINDOW_SPAN_CM, LIT_FRACTION = 64, 8, 9600.0, 0.2
WINDOW_COLOURS = [(255, 206, 150), (250, 224, 186), (222, 230, 248)]   # N25 warmer: warm, neutral, fluorescent


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
