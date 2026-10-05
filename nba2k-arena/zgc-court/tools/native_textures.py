"""Native BC1/BC3 DDS + unsegmented TLD resources with complete mip chains."""
from __future__ import annotations
import hashlib
import io
import math
import struct
import numpy as np
from PIL import Image

TLD_HEADER=struct.Struct('<4sIHBBIHHHHII')

def dds(payload,width,height,alpha,mips=1):
    block=16 if alpha else 8
    flags=0x81007 | (0x20000 if mips>1 else 0)
    top_size=max(1,(width+3)//4)*max(1,(height+3)//4)*block
    header=b'DDS '+struct.pack('<7I',124,flags,height,width,top_size,0,mips)
    header+=bytes(44)+struct.pack('<2I4s5I',32,4,b'DXT5' if alpha else b'DXT1',0,0,0,0,0)
    header+=struct.pack('<5I',0x401008 if mips>1 else 0x1000,0,0,0,0)
    assert len(header)==128
    return header+payload

def encode(image,extra,*,linear=False):
    image=image.convert('RGBA' if image.mode=='RGBA' else 'RGB')
    source_size=image.size
    # A DDS decoder can accept a partial top-level BC block even though the
    # Direct3D runtime rejects that texture resource (E_INVALIDARG). Normalize
    # such images to native-friendly power-of-two dimensions BEFORE encoding.
    # Resampling keeps normalized UVs, artwork placement, and world dimensions.
    if image.width%4 or image.height%4:
        size=tuple(max(4,1<<(v-1).bit_length()) for v in image.size)
        image=image.resize(size,Image.Resampling.LANCZOS)
    assert image.width%4==0 and image.height%4==0
    alpha=image.mode=='RGBA';mip=image;blocks=[];dimensions=[]
    while True:
        padded=mip
        if mip.width%4 or mip.height%4:
            arr=np.asarray(mip)
            arr=np.pad(arr,((0,(-mip.height)%4),(0,(-mip.width)%4),(0,0)),mode='edge')
            padded=Image.fromarray(arr)
        stream=io.BytesIO();padded.save(stream,format='DDS',pixel_format='DXT5' if alpha else 'DXT1')
        payload=stream.getvalue()[128:]
        expected=max(1,math.ceil(mip.width/4))*max(1,math.ceil(mip.height/4))*(16 if alpha else 8)
        assert len(payload)==expected
        # Independently exercise Pillow's BC decoder on each compressed level.
        decoded=Image.open(io.BytesIO(dds(payload,*mip.size,alpha)));decoded.load()
        assert decoded.size==mip.size
        blocks.append(payload);dimensions.append(mip.size)
        if mip.size==(1,1):break
        mip=mip.resize((max(1,mip.width//2),max(1,mip.height//2)),Image.Resampling.LANCZOS)
    payload=b''.join(blocks)
    # The final H fields are depth and array layers, not BC block word size.
    tld=TLD_HEADER.pack(b'TLD ',0,4,77 if alpha else 71,len(blocks),31,image.width,image.height,1,1,len(payload),len(payload))+payload
    # Match every original native DDS: basename.<64-bit-resource-id>.dds.
    # A filesystem-level existence check does not validate the game's shared
    # resource identifier syntax. Keep the id delimited and exactly 16 hex.
    stem='zgc_r03_texture.'+hashlib.sha256(tld).hexdigest()[:16]
    extra[stem+'.tld']=tld;extra[stem+'.dds']=dds(payload,*image.size,alpha,len(blocks))
    spec={'Width':image.width,'Height':image.height,'Mips':len(blocks),'Format':'BC3_UNORM' if alpha else 'BC1_UNORM',
          'Min':[0.,0.,0.,0. if alpha else 1.],'Max':[1.,1.,1.,1.],
          'PixelDataSize':len(payload),'Binary':stem+'.tld'}
    if linear:spec['TexelUsage']='LINEAR'
    source=np.asarray(image).astype(float)
    restored=np.asarray(Image.open(io.BytesIO(extra[stem+'.dds'])).convert(image.mode)).astype(float)
    report={'binary':stem+'.tld','dds':stem+'.dds','size':list(image.size),'mips':len(blocks),
            'source_size':list(source_size),'normalized_uvs_preserved':True,
            'format':spec['Format'],'decoded_mae':float(np.abs(source-restored).mean()),
            'dds_sha256':hashlib.sha256(extra[stem+'.dds']).hexdigest()}
    return 'local/zgc/r03/'+stem,spec,report

def linear_to_srgb(value):
    v=np.clip(np.asarray(value,dtype=float),0,1)
    return np.where(v<=.0031308,v*12.92,1.055*v**(1/2.4)-.055)

def albedo_image(material,folder):
    factor=np.asarray(material['base_color_linear'],float)
    tex=material['base_color_texture']
    if tex:
        im=Image.open(folder/tex['image']['file']).convert('RGBA')
        if not np.allclose(factor,1):
            a=np.asarray(im,dtype=float)/255
            linear=np.where(a[:,:,:3]<=.04045,a[:,:,:3]/12.92,((a[:,:,:3]+.055)/1.055)**2.4)
            a[:,:,:3]=linear_to_srgb(linear*factor[:3]);a[:,:,3]*=factor[3]
            im=Image.fromarray(np.uint8(np.clip(np.rint(a*255),0,255)))
    else:
        color=np.rint(np.r_[linear_to_srgb(factor[:3]),factor[3]]*255).astype(int)
        im=Image.new('RGBA',(4,4),tuple(color))
    if material['alpha_mode']=='OPAQUE':im=im.convert('RGB')
    return im

def normal_rough_image(material,folder):
    # The native simplePBR template uses a neutral tangent normal. Complete
    # arbitrary tangent-frame orientation has not been decoded for this writer.
    rough=material['roughness'];tex=material['metallic_roughness_texture']
    if tex:
        a=np.asarray(Image.open(folder/tex['image']['file']).convert('RGB'))
        r=np.clip(np.rint(a[:,:,1].astype(float)*rough),0,255).astype(np.uint8)
    else:r=np.full((4,4),round(rough*255),np.uint8)
    arr=np.zeros((*r.shape,4),np.uint8);arr[:,:,0:2]=128;arr[:,:,3]=r
    return Image.fromarray(arr)
