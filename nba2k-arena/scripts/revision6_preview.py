"""Inspect the actual R6 IFF, without changing exported geometry or materials."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from revision3_preview import build_preview

ROOT = Path(__file__).resolve().parents[1]
DETAIL_CAMERAS = [
    {'name': '灰色建筑', 'position': [930, 330, -2310], 'target': [120, 160, -3210]},
    {'name': '北侧远岸', 'position': [0, 850, 2200], 'target': [4300, 98, -15000]},
    {'name': '南侧远岸', 'position': [0, 850, -2200], 'target': [6500, 30, 22500]},
    {'name': '草台与海岸接缝', 'position': [4400, 300, 8150], 'target': [3000, 100, 8000]},
    {'name': '涂装俯视', 'position': [0, 3650, 1], 'target': [0, 0, 0]},
    {'name': '罚球区细节', 'position': [0, 1200, 1050], 'target': [0, 0, 1050]},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iff', type=Path, default=ROOT / 'output/revision6/arena_700_int.iff')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/revision6/preview')
    parser.add_argument('--three-dir', type=Path)
    args = parser.parse_args()
    report = build_preview(args.iff, args.output_dir, three_dir=args.three_dir)
    path = args.output_dir / 'scene.json'
    scene = json.loads(path.read_text())
    scene['cameras'].extend(DETAIL_CAMERAS)
    path.write_text(json.dumps(scene, ensure_ascii=False, separators=(',', ':')))
    html = args.output_dir / 'index.html'
    html.write_text(html.read_text().replace('球场 V3', '球场 V6').replace('1–4 切换机位', '1–9 切换机位；0 罚球区'))
    js = args.output_dir / 'viewer.js'
    js.write_text(js.read_text().replace("'1234'.includes(e.key)", "'1234567890'.includes(e.key)")
                  .replace('Number(e.key)-1', '(Number(e.key)+9)%10'))
    print(json.dumps({key: value for key, value in report.items() if key != 'issues'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
