"""Night base: retune only existing native lighting values in level.SCNE.

No light, object, material, texture or post-effect resource is added or removed.
Dims the direct sun into cool moonlight, darkens the sky and clouds, lowers the
baked light-probe ambient and, from N3, uses the native TIME_OF_DAY night with
the camera EV100 of 14.8 kept unchanged.

Game evidence (N1, 2026-10-05): lowering LIGHT_PROBE_GRID_*_EV100 by 2.5 EV and
the sun to 1/25 darkened the whole scene from the blown-out day look to an
overcast grey without washing out, so a lower probe tag does lower ambient.
N2 (sun 1/200, probes -6 EV, sky 0.005, clouds off) darkened ground and
buildings, but sky, horizon haze and glass reflections stayed bright: with
TIME_OF_DAY disabled the sky ignores VC_SkyIntensity, and the IBL cubemaps are
pre-lit daylight. N3 therefore switches on the native TIME_OF_DAY at 22:00 with
its night exposure pinned to the existing camera EV100 (so the dimmed probes
keep their N2 brightness), and lets both IBLs relight from their stored
G-buffer cubemaps. Both switches are unverified in game.
N3.1: the user asked for a darker overall exposure; rather than touching the
camera EV100 (tied to the TIME_OF_DAY night state) the probe ambient is lowered
another 0.6 EV and night_scene scales every emitter by 0.7. N3.2: for stronger
contrast the ambient drops one more EV while night_scene raises its local gains.
N3.3: TIME_OF_DAY clouds re-enabled (game: invisible at night). N3.4: clouds off,
night sky raised to a faint city glow. N3.5: deep navy sky as in the on-site photo
(no orange horizon).
Targets are absolute (derived from the donor daylight values), so applying a
newer revision on top of an older night package does not compound.
"""
from __future__ import annotations

import copy
import re

REVISION = 'N3.5'
DAY_PROBE_EV100 = 14.8000002
# Fractions of the donor's daylight values; relative EV steps are log2 ratios.
SUN_SCALE = 1 / 200
PROBE_EV_SHIFT = -7.6
MOONLIGHT_COLOR = [0.45, 0.6, 1.0, 1.0]
SKY_INTENSITY = 0.005
PROBE_KEY = re.compile(r'LIGHT_PROBE_GRID_\d+_\d+_\d+_TIME_0000_EV100')
DAY_SUN = {'Intensity': 110000.0, 'Color': [0.87962234, 0.921581924, 1.0, 1.0]}
DAY_TIME_OF_DAY = {'VC_SkyIntensity': 1.0, 'VC_SunIntensity': 1500.0, 'VC_TimeOfDayCloudsEnabled': 1}
FIXED_TIME_OF_DAY = {'VC_EV100': 14.8000002, 'VC_AutomaticEV100Enabled': 0}
NIGHT_TIME_OF_DAY = {'VC_Enabled': 1, 'VC_CurrentTime': 22.0, 'VC_NightEV100': 14.8000002}
NIGHT_SKY = {'intensity': 20.0, 'zenith': [0.10, 0.12, 0.22, 1.0], 'horizon': [0.22, 0.25, 0.35, 1.0]}
IBL_OBJECTS = ('IBL1', 'park_streetball_a_master@park_rucker_ext_lighting@GameObjects@court_PillIbl')


def _snapshot(level):
    return {'Light': copy.deepcopy(level['Light']),
            'TIME_OF_DAY': copy.deepcopy(level['Object']['TIME_OF_DAY']),
            'LIGHT_PROBE_GRID_DATA': copy.deepcopy(level['Object']['LIGHT_PROBE_GRID_DATA']),
            'IBL': {k: copy.deepcopy(level['Object'][k]) for k in IBL_OBJECTS}}


def is_night(level):
    return level['Light']['Sun']['Intensity'] < DAY_SUN['Intensity']


def apply_night(level):
    """Mutate level in place from the donor daylight state or an earlier night revision."""
    sun = level['Light']['Sun']
    tod = level['Object']['TIME_OF_DAY']['Attribute']
    grid = level['Object']['LIGHT_PROBE_GRID_DATA']['Attribute']
    assert list(level['Light']) == ['Sun'], 'Unexpected native lights; night base expects only the donor sun'
    assert sun['Type'] == 'DIRECTIONAL' and sun['Intensity'] <= DAY_SUN['Intensity']
    assert all(tod[k] == v for k, v in FIXED_TIME_OF_DAY.items()), 'TIME_OF_DAY exposure state changed'
    assert all(k in tod for k in (*DAY_TIME_OF_DAY, *NIGHT_TIME_OF_DAY))
    ibls = [level['Object'][k]['Attribute'] for k in IBL_OBJECTS]
    assert all('VC_IsLitDynamically' in a for a in ibls)
    probe_keys = [k for k in grid if PROBE_KEY.fullmatch(k)]
    assert probe_keys and all(grid[k] <= DAY_PROBE_EV100 for k in probe_keys)
    assert grid['USE_RELIGHTING'] == 0
    before = _snapshot(level)

    sun['Intensity'] = DAY_SUN['Intensity'] * SUN_SCALE
    sun['Color'] = MOONLIGHT_COLOR[:]
    tod['VC_SkyIntensity'] = SKY_INTENSITY
    tod['VC_SunIntensity'] = 0.0
    tod['VC_TimeOfDayCloudsEnabled'] = 0   # N3.3 clouds were invisible at night
    # N3.4: faint city sky glow instead of pure black (dark blue-grey zenith,
    # sodium-orange horizon). Intensity units are unverified; 0.5 rendered black.
    tod.update(VC_NightSkyIntensity=NIGHT_SKY['intensity'], VC_NightSkyColor=NIGHT_SKY['zenith'],
               VC_NightSkyColorHorizon=NIGHT_SKY['horizon'])
    tod.update(NIGHT_TIME_OF_DAY)
    for attributes in ibls:
        attributes['VC_IsLitDynamically'] = 1
    for key in probe_keys:
        grid[key] = round(DAY_PROBE_EV100 + PROBE_EV_SHIFT, 6)

    after = _snapshot(level)
    return {
        'revision': REVISION,
        'scope': 'level.SCNE values only: Light.Sun intensity/colour, TIME_OF_DAY (enabled at 22:00, night EV100 pinned to camera EV100, sky, sun disc, clouds), IBL dynamic relighting switch, light-probe EV100 tags.',
        'unchanged': 'Sun direction, camera EV100, IBL cubemap textures, PostEffect.FxTweakables, all geometry, materials and textures.',
        'sun_scale': SUN_SCALE,
        'probe_ev_shift': PROBE_EV_SHIFT,
        'probe_tags_changed': len(probe_keys),
        'previous_game_results': ['N1 (sun 1/25, probes -2.5 EV, sky 0.05): darker overcast/foggy grey, clouds still visible; not night.',
                                  'N2 (sun 1/200, probes -6 EV, sky 0.005, clouds off): ground and buildings dark; sky, horizon haze and glass reflections still bright.'],
        'before': before,
        'after': after,
    }
