"""Read-only inspection of the supplied donor and local arena reference packages."""
import json
import zipfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODS = Path(r'D:\steam\steamapps\common\NBA 2K26\mods\levels')

def read_scene(z, name):
    raw = z.read(name).strip()
    return json.loads(raw if raw.startswith(b'{') else b'{' + raw + b'}')

def main():
    with zipfile.ZipFile(ROOT / 'donor/original/arena_020_int_original.iff') as z:
        level = read_scene(z, 'level.SCNE')['level']
        for k, m in level['Model'].items() if '--full' in sys.argv else []:
            streams = m.get('VertexStream', [])
            print('MODEL', k, 'BOUNDS', m.get('Min'), m.get('Max'))
            print('  BUFFERS', [(s, s.get('Binary') in z.namelist()) for s in streams])
            print('  PRIMS', [(p.get('Mesh'), p.get('Material'), p.get('Count')) for p in m.get('Prim',[])])
        print('FLOOR_OBJECTS', [(k, v) for k,v in level['Object'].items() if 'floor' in k.lower() or 'floor' in str(v.get('Target','')).lower()])
        for k,m in level['Material'].items():
            if k.startswith('floor_') or 'mural1' in k:
                print('MATERIAL', k, json.dumps({s:v for s,v in m.items() if s in ('Effect','Resource','Parameter')}, ensure_ascii=False))
        for k,v in level['Texture'].items():
            if k.startswith(('BaseMaterial','DetailNormal')):
                print('FLOOR_TEXTURE', k, json.dumps(v))
        print('SPEEDTREE', read_scene(z,'speedtree.SCNE'))
    for file in ('arena_029_int_floor.iff','arena_011_int_floor.iff','arena_blacktop_ext.iff'):
        path=MODS/file
        if not path.exists(): continue
        if not zipfile.is_zipfile(path):
            with path.open('rb') as f: print('NOT_ZIP',file,repr(f.read(150)))
            continue
        with zipfile.ZipFile(path) as z:
            print('PACKAGE',file,'ENTRIES',len(z.infolist()))
            print('SCENES',[(i.filename,i.file_size) for i in z.infolist() if i.filename.lower().endswith('.scne')])
            if file=='arena_029_int_floor.iff':
                print('EMPTY_FLOOR_CONTENT',[(i.filename,repr(z.read(i))) for i in z.infolist()])
            elif file=='arena_011_int_floor.iff':
                for n in z.namelist():
                    if n.lower().endswith('.scne'):
                        doc=read_scene(z,n)
                        print('FLOOR_ROOTS',list(doc))
                        for k,s in doc.items():
                            print('SECTIONS',{a:len(b) if isinstance(b,(dict,list)) else str(b) for a,b in s.items()})
                            print('OBJECTS',s.get('Object'))
            else:
                for n in z.namelist():
                    if n.lower().endswith('.scne'):
                        try: doc=read_scene(z,n)
                        except Exception as e: print('SCENE_ERROR',n,str(e));continue
                        for k,s in doc.items():
                            if not isinstance(s,dict):continue
                            print('BLACKTOP_SCENE',n,k,{a:len(b) if isinstance(b,(dict,list)) else str(b) for a,b in s.items()})
                            for section in ('Model','Object','Texture'):
                                matched=[(a,b) for a,b in s.get(section,{}).items() if any(word in a.lower() for word in ('palm','tree','beach','sky'))]
                                print('BLACKTOP',section,'MATCH_COUNT',len(matched))
                                for a,b in matched[:25]:
                                    print(a,json.dumps(b)[:1800])

if __name__=='__main__': main()
