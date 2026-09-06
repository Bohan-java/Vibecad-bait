"""Download the specific CC0 texture maps used by revision 3, with checksums."""
from pathlib import Path
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'textures/source/polyhaven'
UA = {'User-Agent': 'Vibecad-bait/1.0 (local asset preparation)'}
ASSETS = {
    'concrete_floor_02': [('Diffuse', '4k'), ('nor_dx', '2k'), ('Rough', '2k')],
    'clean_asphalt': [('Diffuse', '2k'), ('nor_dx', '2k'), ('Rough', '2k')],
    'leafy_grass': [('Diffuse', '2k'), ('nor_dx', '2k'), ('Rough', '2k')],
    'palm_tree_bark': [('Diffuse', '2k'), ('nor_dx', '2k'), ('Rough', '2k')],
    'coast_sand_01': [('Diffuse', '2k'), ('nor_dx', '1k'), ('Rough', '1k')],
}


def read(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
        return r.read()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for asset, maps in ASSETS.items():
        spec = json.loads(read('https://api.polyhaven.com/files/' + asset))
        for kind, resolution in maps:
            entry = spec[kind][resolution]['jpg']
            filename = entry['url'].rsplit('/', 1)[-1]
            path = OUT / filename
            if not path.exists() or hashlib.md5(path.read_bytes()).hexdigest() != entry['md5']:
                path.write_bytes(read(entry['url']))
            raw = path.read_bytes()
            if len(raw) != entry['size'] or hashlib.md5(raw).hexdigest() != entry['md5']:
                raise ValueError('Asset checksum mismatch: ' + filename)
            rows.append({'asset': asset, 'map': kind, 'resolution': resolution,
                         'file': filename, 'url': entry['url'], 'bytes': len(raw),
                         'md5': entry['md5'], 'sha256': hashlib.sha256(raw).hexdigest(),
                         'license': 'CC0-1.0', 'source': 'https://polyhaven.com/a/' + asset})
            print(filename, len(raw), flush=True)
    (OUT / 'manifest.json').write_text(json.dumps(rows, indent=2) + '\n')


if __name__ == '__main__':
    main()
