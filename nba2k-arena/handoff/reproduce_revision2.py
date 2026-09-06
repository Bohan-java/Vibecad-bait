"""Reproduce the archived rejected V2 using only bundled minimal caches.

This handoff adapter does not modify the preserved mod-building source files.
It writes only project output/build/docs, never a game directory or network.
"""
from pathlib import Path
import argparse
import hashlib
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
VCZ=ROOT/'handoff/cache/VertexBuffer.0f3b6fcaf86b59a6.original_vcz.gz'
DECODED=ROOT/'handoff/cache/VertexBuffer.0f3b6fcaf86b59a6.decoded.bin'
FLOOR=ROOT/'build/local_game_reference/levels/arena_700_int_floor.iff'

def inflate_cached(raw):
    if raw==VCZ.read_bytes():return DECODED.read_bytes()
    if raw[:2]==b'\x1f\x8b':raise ValueError('Uncached compressed resource: original local game decoder is required')
    return raw

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--build',action='store_true',help='Rebuild the archived, rejected revision; overwrites project V2 output only')
    parser.add_argument('--preview',action='store_true',help='Decode packaged meshes into offline QA images, not gameplay captures')
    args=parser.parse_args()
    if not args.build and not args.preview:parser.error('Choose --build and/or --preview')
    if args.build:
        import build_revision2 as build
        lookup={'shared/0f/vertexbuffer.0f3b6fcaf86b59a6.gz':VCZ,
                'levels/arena_700_int_floor.iff':FLOOR}
        build.find_entries=lambda needles:{k:v for k,v in lookup.items() if k in needles}
        build.read_entry=lambda entry:entry.read_bytes()
        build.inflate_vcz=inflate_cached
        build.main()
        expected={'arena_700_int.iff':'5d74fdab31ee29e0fe888af10c7370efc329ecc76ceb72c2f1d3eb6aa92bd499',
                  'arena_700_int_floor.iff':'5f23522f783614d1572dca4f904132659f0d9ad4bd266b8148cbaacd333cf2ce'}
        for name,sha in expected.items():
            actual=hashlib.sha256((ROOT/'output/revision2'/name).read_bytes()).hexdigest()
            print('Exact archived output match:',name,actual==sha,actual)
    if args.preview:
        import preview_revision2 as preview
        preview.inflate_vcz=inflate_cached
        preview.main()

if __name__=='__main__':main()
