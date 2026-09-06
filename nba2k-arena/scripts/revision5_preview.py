"""Inspect the actual R5 archive with full-court and paint detail cameras.

The decoded geometry and albedo come from the IFF. This Three.js viewer does
not reproduce the original NBA 2K shaders, render passes or runtime lighting.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from revision3_preview import build_preview
from revision4_preview import DETAIL_CAMERAS

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iff', type=Path, default=ROOT/'output/revision5/arena_700_int.iff')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'build/revision5/preview')
    parser.add_argument('--three-dir', type=Path)
    args = parser.parse_args()
    report = build_preview(args.iff, args.output_dir, three_dir=args.three_dir)
    path = args.output_dir/'scene.json'
    scene = json.loads(path.read_text())
    scene['cameras'].extend(DETAIL_CAMERAS + [
        {'name': '涂装俯视', 'position': [0, 3650, 1], 'target': [0, 0, 0]},
        {'name': '中圈细节', 'position': [260, 150, 390], 'target': [0, 0, 0]},
        {'name': '罚球区细节', 'position': [0, 1200, 1050], 'target': [0, 0, 1050]},
    ])
    path.write_text(json.dumps(scene, ensure_ascii=False, separators=(',', ':')))
    html = args.output_dir/'index.html'
    html.write_text(html.read_text().replace('球场 V3', '球场 V5').replace('1–4 切换机位', '1–9 切换机位；0 中圈细节'))
    js = args.output_dir/'viewer.js'
    js.write_text(js.read_text().replace("'1234'.includes(e.key)", "'1234567890'.includes(e.key)")
                  .replace('Number(e.key)-1', '(Number(e.key)+9)%10'))
    print(json.dumps({key:value for key,value in report.items() if key != 'issues'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
