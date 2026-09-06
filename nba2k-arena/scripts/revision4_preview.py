"""Inspect the actual revision 4 archive using the existing local Three.js runtime.

This adds photo-relevant detail cameras to the strict archive decoder. It does
not synthesize missing basket resources or claim to reproduce NBA 2K lighting.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from revision3_preview import build_preview

ROOT = Path(__file__).resolve().parents[1]
DETAIL_CAMERAS = [
    {'name': '路灯', 'position': [2510, 560, 1070], 'target': [2900, 475, 750]},
    {'name': '桶组', 'position': [-1050, 152, 2090], 'target': [-1222, 68, 1870]},
    {'name': '看台', 'position': [-2230, 175, 40], 'target': [-1760, 115, 710]},
    {'name': '草台端部', 'position': [800, 450, 6000], 'target': [2080, 60, 4540]},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iff', type=Path, default=ROOT / 'output/revision4/arena_700_int.iff')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/revision4/preview')
    parser.add_argument('--three-dir', type=Path)
    args = parser.parse_args()
    report = build_preview(args.iff, args.output_dir, three_dir=args.three_dir)
    scene_path = args.output_dir / 'scene.json'
    scene = json.loads(scene_path.read_text())
    scene['cameras'].extend(DETAIL_CAMERAS)
    scene_path.write_text(json.dumps(scene, ensure_ascii=False, separators=(',', ':')))
    html = args.output_dir / 'index.html'
    html.write_text(html.read_text().replace('球场 V3', '球场 V4').replace('1–4 切换机位', '1–8 切换机位'))
    js = args.output_dir / 'viewer.js'
    js.write_text(js.read_text().replace("'1234'.includes(e.key)", "'12345678'.includes(e.key)"))
    print(json.dumps({key: value for key, value in report.items() if key != 'issues'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
