"""Extend the probe bake by one ring where the bake still adds noticeable light.

Reads bake/output/probe_sh.ndjson and the current package, finds referenced
probes that are not baked yet but sit next to (within NEIGHBOUR_CM of) a baked
probe whose added light is more than THRESHOLD of the base ambient, and writes
them to bake/probes_3_0_2_ring<N>.json for bake_probes.py --probes. Repeat
until it reports 0 so the baked light fades out before the bake set ends.

  python3 bake/extend_probes.py      (from nba2k-arena/zgc-court, normal Python)
"""
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tools'))
from iff_codec import load_scne                                   # noqa: E402
from night_scene import BAKE_GROUND_Y_CM, BAKE_WEIGHTS, _baked_addition, _texture_archive_name, load_baked, strip_scene   # noqa: E402
from patch_scene_current import R13                               # noqa: E402

NEIGHBOUR_CM = 600.0     # grid spacing is 400 cm; includes diagonal neighbours
THRESHOLD = 0.05


def main():
    baked = load_baked()
    with zipfile.ZipFile(HERE.parent / 'output/arena_700_int.iff') as cur, zipfile.ZipFile(R13) as day:
        level = load_scne(cur.read('level.SCNE'))['level']
        strip_scene(level, load_scne(day.read('level.SCNE'))['level'])
        origin = np.asarray(level['Object']['LIGHT_PROBE_GRID_DATA']['Attribute']['GRID_ORIGIN'][:3], float)
        new = []
        for sector, rows in baked.items():
            tex = level['Texture']
            read = lambda suffix: cur.read(_texture_archive_name(tex[sector + suffix]['Binary']))
            count = int(tex[sector + '_TIME_0000_PROBE_DATA']['Height'])
            data = np.frombuffer(read('_TIME_0000_PROBE_DATA'), '<f4').reshape(count, 28).astype(float)
            world = np.frombuffer(read('_PROBE_POSITIONS'), '<f4').reshape(count, 3) + origin
            indices = np.frombuffer(read('_CELL_PROBE_INDICES'), '<u4').reshape(-1, 8)
            states = np.frombuffer(read('_CELL_PROBE_STATES'), np.uint8)
            active = ((states[:, None] >> np.arange(8, dtype=np.uint8)) & 1).astype(bool)
            referenced = np.zeros(count, bool)
            referenced[np.unique(indices[active])] = True
            added, mask = _baked_addition(rows, world, count, BAKE_WEIGHTS)
            ratio = added[:, :3].sum(1) / np.maximum(data[:, :3].sum(1), 1e-9)
            bright = np.flatnonzero(mask & (ratio > THRESHOLD))
            candidates = np.flatnonzero(referenced & ~mask & (world[:, 1] >= BAKE_GROUND_Y_CM))
            for i in candidates:
                if (np.linalg.norm(world[bright] - world[i], axis=1) < NEIGHBOUR_CM).any():
                    x, y, z = (float(v) for v in world[i])
                    new.append({'sector': sector, 'id': int(i), 'world_cm': [round(x, 3), round(y, 3), round(z, 3)],
                                'blender_m': [round(-z / 100, 5), round(-x / 100, 5), round(y / 100, 5)]})
    ring = 1
    while (HERE / f'probes_3_0_2_ring{ring}.json').exists():
        ring += 1
    print(f'{len(new)} probes to add')
    if new:
        path = HERE / f'probes_3_0_2_ring{ring}.json'
        path.write_text(json.dumps({'description': f'Ring {ring} around the baked probes (bake/extend_probes.py).',
                                    'count': len(new), 'probes': new}, indent=0), encoding='utf8')
        print('wrote', path.name)


if __name__ == '__main__':
    main()
