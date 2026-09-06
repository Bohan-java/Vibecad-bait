"""Read exact local game-manifest ranges; never writes to the game directory."""
import io
import json
import zipfile
import zlib
import ctypes
import struct
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
GAME=Path(r'D:\steam\steamapps\common\NBA 2K26')

def find_entries(needles):
    result={}
    with (GAME/'manifest').open(encoding='utf-8') as f:
        for line in f:
            name,container,offset,size=line.rstrip('\n').split(',')
            if any(n.lower() == name.lower() or name.lower().endswith('/'+n.lower()) for n in needles):
                result[name]=(container,int(offset),int(size))
    return result

def read_entry(entry):
    container,offset,size=entry
    with (GAME/container).open('rb') as f:
        f.seek(offset)
        return f.read(size)

def inflate_vcz(raw):
    if raw[:2]==b'\x1f\x8b' and raw[12:16]==b'VCZ\x00':
        try: return zlib.decompress(raw[16:-8])
        except zlib.error: pass
        expected=struct.unpack_from('<I',raw,len(raw)-4)[0]
        return oodle_decode(raw[16:-8],expected)
    return raw

def oodle_decode(payload,size):
    if not (0<size<2_000_000_000): raise ValueError(f'Unreasonable decompressed size: {size}')
    lib=ctypes.CDLL(str(GAME/'data/oodle/oo2core_9_win64.dll'))
    fn=lib.OodleLZ_Decompress
    fn.restype=ctypes.c_ssize_t
    fn.argtypes=[ctypes.c_void_p,ctypes.c_ssize_t,ctypes.c_void_p,ctypes.c_ssize_t,
                 ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p,ctypes.c_ssize_t,
                 ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ssize_t,ctypes.c_int]
    src=ctypes.create_string_buffer(payload)
    dst=ctypes.create_string_buffer(size)
    actual=fn(src,len(payload),dst,size,1,0,0,None,0,None,None,None,0,3)
    if actual != size: raise ValueError(f'Oodle decode returned {actual}, expected {size}')
    return dst.raw

def main():
    wanted=['levels/arena_020_int_floor.iff','levels/arena_700_int_floor.iff',
            'shared/0f/vertexbuffer.0f3b6fcaf86b59a6.gz']
    for name,entry in find_entries(wanted).items():
        raw=read_entry(entry)
        print('RESOURCE',name,entry,'HEADER',repr(raw[:64]))
        decoded=inflate_vcz(raw)
        out=ROOT/'build/local_game_reference'/name
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes(decoded)
        print('DECODED',len(decoded),repr(decoded[:32]))
        if zipfile.is_zipfile(io.BytesIO(decoded)):
            with zipfile.ZipFile(io.BytesIO(decoded)) as z:
                print('ARCHIVE_ENTRIES',len(z.namelist()),z.namelist()[:12])
                for n in z.namelist():
                    if n.lower().endswith('.scne'):
                        raw=z.read(n).strip()
                        try: d=json.loads(raw if raw.startswith(b'{') else b'{'+raw+b'}')
                        except (UnicodeDecodeError,json.JSONDecodeError):
                            print('BINARY_SCENE',n,repr(raw[:160]))
                            continue
                        for k,s in d.items():
                            print('SCENE',k,'OBJECTS',s.get('Object'))
                            print('MODELS',[(n,m.get('Min'),m.get('Max')) for n,m in s.get('Model',{}).items()])

if __name__=='__main__': main()
