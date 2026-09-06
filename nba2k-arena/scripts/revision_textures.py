"""Offline texture construction and independent DDS decoder verification."""
from __future__ import annotations
import hashlib
import io
import struct
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from tld_texture import TLD_HEADER

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/revision2/textures'

def make_dds(payload,w,h,fmt):
    fourcc=b'DXT1' if fmt=='BC1_UNORM' else b'DXT5'
    header=b'DDS '+struct.pack('<7I',124,0x81007,h,w,max(1,(w+3)//4)*(8 if fourcc==b'DXT1' else 16),0,0)
    header+=bytes(44)+struct.pack('<2I4s5I',32,4,fourcc,0,0,0,0,0)+struct.pack('<5I',0x1000,0,0,0,0)
    assert len(header)==128
    return header+payload

def encode_texture(name,image,linear=False):
    OUT.mkdir(parents=True,exist_ok=True)
    image=image.convert('RGBA' if image.mode=='RGBA' else 'RGB')
    alpha=image.mode=='RGBA'
    fmt='BC3_UNORM' if alpha else 'BC1_UNORM'
    codec='DXT5' if alpha else 'DXT1'
    mip=image
    payloads=[]
    dimensions=[]
    while True:
        stream=io.BytesIO()
        padded=mip
        if mip.width<4 or mip.height<4:
            a=np.asarray(mip)
            a=np.pad(a,((0,max(0,4-mip.height)),(0,max(0,4-mip.width)),(0,0)),mode='edge')
            padded=Image.fromarray(a)
        padded.save(stream,format='DDS',pixel_format=codec)
        block=stream.getvalue()[128:]
        expected=max(1,(mip.width+3)//4)*max(1,(mip.height+3)//4)*(16 if alpha else 8)
        assert len(block)==expected,(name,len(block),expected)
        payloads.append(block)
        dimensions.append(mip.size)
        if mip.size==(1,1): break
        mip=mip.resize((max(1,mip.width//2),max(1,mip.height//2)),Image.Resampling.LANCZOS)
    payload=b''.join(payloads)
    raw=TLD_HEADER.pack(b'TLD ',0,4,77 if alpha else 71,len(payloads),31,image.width,image.height,1,2 if alpha else 1,len(payload),len(payload))+payload
    binary=f'venice_v2_{name}.{hashlib.sha256(raw).hexdigest()[:16]}.tld'
    (OUT/binary).write_bytes(raw)
    image.save(OUT/f'{name}_source.png')
    dds=make_dds(payloads[0],image.width,image.height,fmt)
    (OUT/f'{name}.dds').write_bytes(dds)
    decoded=Image.open(io.BytesIO(dds)).convert(image.mode)
    decoded.save(OUT/f'{name}_decoded.png')
    # Every level is independently decoded by Pillow's native BC decoder.
    for data,(w,h) in zip(payloads,dimensions):
        check=Image.open(io.BytesIO(make_dds(data,w,h,fmt)))
        check.load()
        assert check.size==(w,h)
    spec={'Width':image.width,'Height':image.height,'Mips':len(payloads),
          'Format':fmt,'Min':[0.,0.,0.,0. if alpha else 1.],
          'Max':[1.,1.,1.,1.],'PixelDataSize':len(payload),'Binary':binary}
    if linear: spec['TexelUsage']='LINEAR'
    return f'local/venice_v2/{name}',spec,raw

def tile(kind,size=512):
    rng=np.random.default_rng({'asphalt':200,'concrete':201,'grass':202}[kind])
    base={'asphalt':[90,97,100],'concrete':[165,164,151],'grass':[65,88,36]}[kind]
    y,x=np.mgrid[:size,:size]
    broad=2*np.sin(2*np.pi*x/size*3)+1.5*np.sin(2*np.pi*(x+y)/size*5)
    noise=rng.normal(0,3 if kind!='grass' else 9,(size,size))
    a=np.array(base)[None,None,:]+(noise+broad)[:,:,None]
    return Image.fromarray(np.uint8(np.clip(a,0,255)))

def palm_cutout():
    # Source #2: one tall unobstructed palm. Selection restricts everything
    # below the crown to its trunk, excluding building/court/people entirely.
    src=Image.open(ROOT/'textures/source/references/arena_reference_02.png').convert('RGB')
    box=(95,94,176,335)
    a=np.asarray(src.crop(box)).astype(np.float32)
    r,g,b=a[:,:,0],a[:,:,1],a[:,:,2]
    sky=(b-r>15)&(b-g>8)&(b>90)
    alpha=np.where(sky,0,255).astype(np.uint8)
    h,w=alpha.shape
    yy,xx=np.mgrid[:h,:w]
    # Follow the actual narrow trunk, including where it crosses the gray
    # building. A broad rectangular corridor retains building pixels.
    trunk_center=44.-5.*(yy-83)/158.
    alpha[(yy>83)&(np.abs(xx-trunk_center)>2.5)]=0
    rgba=np.dstack((a.astype(np.uint8),alpha))
    return Image.fromarray(rgba)

def panorama():
    width,height=2048,512
    y=np.arange(height)/height
    colors=np.array([68,127,194])[None,:]*(1-y[:,None])+np.array([150,181,202])[None,:]*y[:,None]
    canvas=Image.fromarray(np.uint8(np.repeat(colors[:,None,:],width,axis=1))).convert('RGBA')
    draw=ImageDraw.Draw(canvas)
    horizon=443
    draw.rectangle((0,horizon,width,468),fill=(133,159,169))
    draw.rectangle((0,468,width,height),fill=(73,94,46))
    palm=palm_cutout()
    rng=np.random.default_rng(904)
    for x in [90,180,335,500,560,740,940,1020,1180,1300,1395,1580,1740,1860,2000]:
        h=int(rng.integers(220,390));w=round(palm.width*h/palm.height)
        p=palm.resize((w,h),Image.Resampling.LANCZOS)
        canvas.alpha_composite(p,(x-w//2,478-h))
    OUT.mkdir(parents=True,exist_ok=True)
    canvas.convert('RGB').save(OUT/'palm_panorama_source.png')
    return canvas.convert('RGB')

def create_set():
    images={k:(tile(k),False) for k in ('asphalt','concrete','grass')}
    images.update({
        'sky':(Image.new('RGB',(4,4),(75,137,202)),False),
        'aluminum':(Image.new('RGB',(4,4),(158,162,160)),False),
        'dark_metal':(Image.new('RGB',(4,4),(44,48,49)),False),
        'line_white':(Image.new('RGB',(4,4),(228,228,216)),False),
        'no_logo':(Image.new('RGBA',(4,4),(255,255,255,0)),False),
        'matte_base':(Image.new('RGBA',(4,4),(220,0,0,255)),True),
        'floor_normal_rough_cone':(Image.new('RGBA',(4,4),(128,128,215,255)),True),
        'surface_normal_rough':(Image.new('RGBA',(4,4),(128,128,0,215)),True),
        'palm_trunk':(Image.new('RGB',(4,4),(117,111,92)),False),
        'palm_leaf':(Image.new('RGB',(4,4),(70,98,40)),False),
        'palm_leaf_light':(Image.new('RGB',(4,4),(111,130,63)),False),
        'palm_leaf_dark':(Image.new('RGB',(4,4),(39,67,30)),False),
        'palm_dead':(Image.new('RGB',(4,4),(94,77,45)),False),
    })
    pano=panorama()
    for i in range(5):
        left=round(i*pano.width/5);right=round((i+1)*pano.width/5)
        images[f'palm_backdrop_{i+1}']=(pano.crop((left,0,right,pano.height)).resize((512,512),Image.Resampling.LANCZOS),False)
    result={}
    for name,(img,linear) in images.items():
        result[name]=encode_texture(name,img,linear)
    return result
