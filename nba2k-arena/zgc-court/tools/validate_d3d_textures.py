"""Validate BC DDS resources using the installed Windows Direct3D 11 runtime.

This creates and immediately releases offscreen resources. It does not open,
read, inject into, or alter the game. No window or swapchain is created.
"""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import struct
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
P=C.c_void_p
U=C.c_uint
class Sample(C.Structure):
    _fields_=[('Count',U),('Quality',U)]
class Desc(C.Structure):
    _fields_=[('Width',U),('Height',U),('MipLevels',U),('ArraySize',U),
              ('Format',U),('SampleDesc',Sample),('Usage',U),('BindFlags',U),
              ('CPUAccessFlags',U),('MiscFlags',U)]
class Subresource(C.Structure):
    _fields_=[('pSysMem',P),('SysMemPitch',U),('SysMemSlicePitch',U)]

def method(obj,index,result,*args):
    table=C.cast(obj,C.POINTER(C.POINTER(P))).contents
    return C.WINFUNCTYPE(result,P,*args)(table[index])

def validate(path):
    device=P();context=P();feature=U()
    create=C.WinDLL('d3d11.dll').D3D11CreateDevice
    create.argtypes=[P,U,P,U,C.POINTER(U),U,U,C.POINTER(P),C.POINTER(U),C.POINTER(P)]
    create.restype=C.c_long
    hr=create(None,1,None,0,None,0,7,C.byref(device),C.byref(feature),C.byref(context))
    if hr<0:raise RuntimeError(f'D3D11CreateDevice HRESULT {hr & 0xffffffff:08x}')
    create_texture=method(device,5,C.c_long,C.POINTER(Desc),C.POINTER(Subresource),C.POINTER(P))
    result={'api':'D3D11 CreateTexture2D with complete DDS mip payloads',
            'feature_level':hex(feature.value),'input':str(path),'textures':[]}
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.startswith(('zgc_r03_','zgc_r10_','floor_line.','floor_line_thin.','floor_line_double.')) or not name.endswith('.dds'):continue
                raw=archive.read(name)
                height,width=struct.unpack_from('<II',raw,12)
                mips=struct.unpack_from('<I',raw,28)[0] or 1
                fourcc=raw[84:88]
                if fourcc==b'DX10':
                    fmt=struct.unpack_from('<I',raw,128)[0]
                    block={98:16,99:16}[fmt]
                    data_offset=148
                else:
                    fmt,block={b'DXT1':(71,8),b'DXT5':(77,16)}[fourcc]
                    data_offset=128
                desc=Desc(width,height,mips,1,fmt,Sample(1,0),0,8,0,0)
                data=C.create_string_buffer(raw)
                subs=(Subresource*mips)();offset=data_offset;w=width;h=height
                for i in range(mips):
                    pitch=max(1,(w+3)//4)*block
                    size=pitch*max(1,(h+3)//4)
                    subs[i]=Subresource(C.addressof(data)+offset,pitch,size)
                    offset+=size;w=max(1,w//2);h=max(1,h//2)
                assert offset==len(raw),(name,offset,len(raw))
                texture=P()
                hr=create_texture(device,C.byref(desc),subs,C.byref(texture))
                result['textures'].append({'binary':name,'width':width,'height':height,
                  'mips':mips,'format':fourcc.decode(),'hresult':f'0x{hr & 0xffffffff:08X}',
                  'success':hr>=0 and bool(texture)})
                if texture:method(texture,2,U)(texture)
    finally:
        method(context,2,U)(context);method(device,2,U)(device)
    result['failed']=[x for x in result['textures'] if not x['success']]
    result['passed_count']=len(result['textures'])-len(result['failed'])
    return result

if __name__=='__main__':
    p=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'output/arena_700_int.iff'
    result=validate(p)
    out=ROOT/'validation/native-d3d-texture-validation.json'
    out.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({'passed':result['passed_count'],'failed':result['failed'],'report':str(out)},indent=2))
