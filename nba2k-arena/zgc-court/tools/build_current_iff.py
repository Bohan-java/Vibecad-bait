"""Rebuild the latest native candidate from the current published source GLB.

An intermediate with legacy material bindings stays in staging and is repaired
before the one deliverable is published. No game installation is accessed.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def run(name,*args):
    subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools'/name),*map(str,args)],cwd=ROOT,check=True)

def main():
    manifest=json.loads((ROOT/'public/manifest.json').read_text(encoding='utf8'))
    build=json.loads((ROOT/'public/builds'/manifest['build_id']/'build.json').read_text(encoding='utf8'))
    expected=next(x['sha256'] for x in build['inputs'] if x['path']=='source/scene.blend')
    actual=hashlib.sha256((ROOT/'source/scene.blend').read_bytes()).hexdigest()
    if actual!=expected:raise RuntimeError('Saved Blender source has changed. Wait for the preview export to finish before packaging.')
    assets=ROOT/'.build-staging/current-native/assets'
    base=ROOT/'.build-staging/current-native/source-base.iff'
    run('export_game_assets.py','--output',assets)
    run('build_source_iff.py','--assets',assets,'--output',base)
    run('repair_iff.py','--input',base,'--output',ROOT/'output/arena_700_int.iff')
    run('finalize_current_iff.py')
    run('export_native_preview.py')
    print('Latest repaired candidate written. Run the project cleanup after final verification.')

if __name__=='__main__':main()
