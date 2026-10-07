"""Calibrate night_scene.BAKE_WEIGHTS: scale each baked light group so its added
probe light matches, in a least-squares sense over the baked probes, the light
the N16 hand-placed regions it replaces added (the level the user had approved
in game). Only probes up to FIT_MAX_Y_CM (player height) are fitted: N16
faded the Chilis light out above 2-3.8 m on purpose, while the bake (rightly)
still lights the probe layer at ~4 m, which nothing but the ball reaches.
Prints the weights and a per-group comparison; changes nothing.

  python3 tools/calibrate_bake.py
"""
from pathlib import Path
import zipfile

import numpy as np

from iff_codec import load_scne
from night_scene import (PROBE_DATA_KEY, PROBE_GAIN_REGIONS, WARM_GAIN_REGIONS, RGB_TRIPLES,
                         _texture_archive_name, load_baked, strip_scene)
from patch_scene_current import R13

ROOT = Path(__file__).resolve().parents[1]
GROUP_OF_REGION = {'a_sign_east': 'a_signs', 'a_sign_west': 'a_signs', 'flood_pool': 'floodlight',
                   'boots_facade': 'boots'}   # every chilis_* region -> chilis
FIT_MAX_Y_CM = 250.0


def weight(region, world):
    d = np.linalg.norm(world - np.asarray(region['center_cm']), axis=1)
    w = np.exp(-0.5 * (d / region['sigma_cm']) ** 2)
    w[w < 0.01] = 0.0
    if 'y_fade' in region:
        y0, y1 = region['y_fade']
        t = np.clip((world[:, 1] - y0) / (y1 - y0), 0, 1)
        w = w * (1 - t * t * (3 - 2 * t))
    return w


def main():
    baked = load_baked()
    assert baked, 'No bake results'
    with zipfile.ZipFile(ROOT / 'output/arena_700_int.iff') as current, zipfile.ZipFile(R13) as day:
        level = load_scne(current.read('level.SCNE'))['level']
        strip_scene(level, load_scne(day.read('level.SCNE'))['level'])
        grid = level['Object']['LIGHT_PROBE_GRID_DATA']['Attribute']
        origin = np.asarray(grid['GRID_ORIGIN'][:3], float)
        for sector, rows in baked.items():
            key = sector + '_TIME_0000_PROBE_DATA'
            assert PROBE_DATA_KEY.fullmatch(key)
            spec = level['Texture'][key]
            count = int(spec['Height'])
            data = np.frombuffer(current.read(_texture_archive_name(spec['Binary'])), '<f4').reshape(count, 28).astype(float)
            pos = level['Texture'][sector + '_PROBE_POSITIONS']
            world = np.frombuffer(current.read(_texture_archive_name(pos['Binary'])), '<f4').reshape(count, 3) + origin
            ids = np.array([i for i in sorted(rows) if world[i, 1] <= FIT_MAX_Y_CM])
            groups = sorted(next(iter(rows.values()))[1])
            target = {g: np.zeros((len(ids), 3)) for g in groups}
            for region in [r for r in PROBE_GAIN_REGIONS if 'source_cm' in r] + list(WARM_GAIN_REGIONS):
                group = GROUP_OF_REGION.get(region['label'], 'chilis')
                w = (region['gain'] - 1) * weight(region, world[ids])
                tint = np.asarray(region.get('tint', (1, 1, 1)))
                target[group] += w[:, None] * tint[None, :] * data[ids][:, list(RGB_TRIPLES[0])]
            print(f'{sector}: {len(rows)} baked probes, {len(ids)} at player height fitted')
            for g in groups:
                b = np.array([rows[i][1][g][0] for i in ids])   # baked L0 RGB
                t = target[g]
                k = float((b * t).sum() / max((b * b).sum(), 1e-30))
                fit = k * b
                peak_t, peak_b = t.sum(1).max(), fit.sum(1).max()
                spread_t = (t.sum(1) > 0.1 * peak_t).sum()
                spread_b = (fit.sum(1) > 0.1 * peak_b).sum()
                print(f"  {g:10s} weight {k:10.4g}  N16 peak {peak_t:.4g} vs baked {peak_b:.4g}; "
                      f"probes above 10% of peak: N16 {spread_t}, baked {spread_b}")


if __name__ == '__main__':
    main()
