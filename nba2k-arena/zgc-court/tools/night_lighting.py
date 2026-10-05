"""N1 night base: retune only existing native lighting values in level.SCNE.

No light, object, material, texture or post-effect resource is added or removed.
The donor keeps TIME_OF_DAY disabled with a fixed camera EV100 of 14.8, so this
pass leaves that system and the camera exposure untouched and instead dims the
direct sun into cool moonlight, removes the visible sky/sun disc, and lowers the
baked light-probe ambient.

Unverified assumption: LIGHT_PROBE_GRID_*_EV100 is the exposure the baked probe
data was stored at, so lowering it lowers the absolute ambient. If the game
shows a brighter or washed-out scene instead, that assumption is inverted.
"""
from __future__ import annotations

import copy
import re

REVISION = 'N1'
DAY_PROBE_EV100 = 14.8000002
# Fractions of the donor's daylight values; relative EV steps are log2 ratios.
SUN_SCALE = 1 / 25
PROBE_EV_SHIFT = -2.5
MOONLIGHT_COLOR = [0.55, 0.68, 1.0, 1.0]
SKY_INTENSITY = 0.05
PROBE_KEY = re.compile(r'LIGHT_PROBE_GRID_\d+_\d+_\d+_TIME_0000_EV100')
DAY_SUN = {'Intensity': 110000.0, 'Color': [0.87962234, 0.921581924, 1.0, 1.0]}
DAY_TIME_OF_DAY = {'VC_Enabled': 0, 'VC_SkyIntensity': 1.0, 'VC_SunIntensity': 1500.0, 'VC_EV100': 14.8000002}


def _snapshot(level):
    return {'Light': copy.deepcopy(level['Light']),
            'TIME_OF_DAY': copy.deepcopy(level['Object']['TIME_OF_DAY']),
            'LIGHT_PROBE_GRID_DATA': copy.deepcopy(level['Object']['LIGHT_PROBE_GRID_DATA'])}


def is_night(level):
    return level['Light']['Sun']['Intensity'] < DAY_SUN['Intensity']


def apply_night(level):
    """Mutate level in place; refuses anything but the known daylight donor values."""
    sun = level['Light']['Sun']
    tod = level['Object']['TIME_OF_DAY']['Attribute']
    grid = level['Object']['LIGHT_PROBE_GRID_DATA']['Attribute']
    assert list(level['Light']) == ['Sun'], 'Unexpected native lights; night base expects only the donor sun'
    assert sun['Type'] == 'DIRECTIONAL' and sun['Intensity'] == DAY_SUN['Intensity'] and sun['Color'] == DAY_SUN['Color']
    assert all(tod[k] == v for k, v in DAY_TIME_OF_DAY.items()), 'TIME_OF_DAY is not the daylight donor state'
    probe_keys = [k for k in grid if PROBE_KEY.fullmatch(k)]
    assert probe_keys and all(grid[k] == DAY_PROBE_EV100 for k in probe_keys)
    assert grid['USE_RELIGHTING'] == 0
    before = _snapshot(level)

    sun['Intensity'] = DAY_SUN['Intensity'] * SUN_SCALE
    sun['Color'] = MOONLIGHT_COLOR[:]
    tod['VC_SkyIntensity'] = SKY_INTENSITY
    tod['VC_SunIntensity'] = 0.0
    for key in probe_keys:
        grid[key] = round(DAY_PROBE_EV100 + PROBE_EV_SHIFT, 6)

    after = _snapshot(level)
    return {
        'revision': REVISION,
        'scope': 'level.SCNE values only: Light.Sun intensity/colour, TIME_OF_DAY sky and sun-disc intensity, light-probe EV100 tags.',
        'unchanged': 'Sun direction and shadows, TIME_OF_DAY enable flag and camera EV100, IBL cubemaps, PostEffect.FxTweakables, all geometry, materials and textures.',
        'sun_scale': SUN_SCALE,
        'probe_ev_shift': PROBE_EV_SHIFT,
        'probe_tags_changed': len(probe_keys),
        'assumption': 'Lower probe EV100 tag = dimmer baked ambient. Unverified; a brighter in-game result means it is inverted.',
        'before': before,
        'after': after,
    }
