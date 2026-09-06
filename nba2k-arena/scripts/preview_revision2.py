"""Offline geometry QA decoded from the IFF; explicitly NOT a game capture."""
from __future__ import annotations
import io
import json
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from read_game_resource import inflate_vcz
from revision_textures import make_dds

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/revision2'

def positions(archive,model):
    f=model['VertexFormat']['POSITION0'];s=model['VertexStream'][f.get('Stream',0)]
    raw=inflate_vcz(archive.read(s['Binary']))
    assert len(raw)==s['Size']
    n=len(raw)//s['Stride'];fmt=f['Format']
    dtype,components=('<u2',4) if fmt=='R16G16B16A16_UNORM' else ('<f4',3)
    assert fmt in ('R16G16B16A16_UNORM','R32G32B32_FLOAT')
    data=np.ndarray((n,components),dtype,raw,offset=f.get('ByteOffset',0),strides=(s['Stride'],np.dtype(dtype).itemsize)).astype(float)
    if dtype=='<u2':data/=65535.
    data=data*np.array(f.get('Scale',[1]*components))[:components]+np.array(f.get('Offset',[0]*components))[:components]
    return data[:,:3]

def mesh(archive,level,name,matrix=None):
    model=level['Model'][name];pos=positions(archive,model)
    if matrix is not None:
        mat=np.array(matrix).reshape(4,4)
        pos=(np.column_stack((pos,np.ones(len(pos))))@mat)[:,:3]
    inds=np.frombuffer(inflate_vcz(archive.read(model['IndexBuffer']['Binary'])),'<u2')
    result=[];cursor=0;material=None
    for prim in model['Prim']:
        start,count=prim.get('Start',cursor),prim['Count']
        cursor=start+count;material=prim.get('Material',material)
        ix=inds[start:start+count];assert len(ix)==count and len(ix)%3==0 and ix.max()<len(pos)
        m=level['Material'][material]
        slots=m['Resource'];slot='AlbedoMap' if 'AlbedoMap' in slots else 'DetailAlbedoTexture'
        tex=level['Texture'][slots[slot]['Pixelmap']]
        raw=archive.read(tex['Binary'])
        image=Image.open(io.BytesIO(make_dds(raw[32:],tex['Width'],tex['Height'],tex['Format']))).convert('RGB')
        color=np.array(image.resize((1,1))).reshape(3).astype(float)
        # Preserve tiny floor-line overlays in this software-only view.
        tri=pos[ix.reshape(-1,3)].copy()
        if 'floor_line' in material:tri[:,:,1]+=.3
        result.append((tri,color))
    return result

def render(parts,path,eye,center,scale,size=(1600,1100),title='EXPORTED MESH CHECK - NOT A GAME SCREENSHOT'):
    ss=2;w,h=size[0]*ss,size[1]*ss
    target=np.array(center,float);eye=np.array(eye,float)
    view=eye-target;view/=np.linalg.norm(view)
    right=np.cross([0,1,0],view);right/=np.linalg.norm(right)
    up=np.cross(view,right)
    tri=np.concatenate([p[0] for p in parts]);color=np.concatenate([np.tile(p[1],(len(p[0]),1)) for p in parts])
    normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);length=np.linalg.norm(normal,axis=1)
    good=length>1e-8
    tri=tri[good];color=color[good];normal=normal[good]/length[good,None]
    sunlight=np.array([.2,.85,.45]);sunlight/=np.linalg.norm(sunlight)
    shade=.52+.48*np.abs(normal@sunlight)
    colors=np.uint8(np.clip(color*shade[:,None],0,255))
    v=tri-target
    xy=np.stack(((v@right)*scale*ss+w/2,-(v@up)*scale*ss+h*.56),axis=2)
    depth=v@view
    sort_depth=depth.mean(1)
    # The horizontal floor is behind everything else seen from above. Draw it
    # first so triangle-average painter sorting cannot cover its line overlays.
    floor_base=np.max(np.abs(tri[:,:,1]),axis=1)<.001
    sort_depth[floor_base]-=1e9
    order=np.argsort(sort_depth,kind='stable')
    im=Image.new('RGB',(w,h),(185,208,223));draw=ImageDraw.Draw(im)
    for i in order:
        p=xy[i]
        if p[:,0].max()<0 or p[:,0].min()>w or p[:,1].max()<0 or p[:,1].min()>h:continue
        draw.polygon([tuple(x) for x in p],fill=tuple(colors[i]))
    im=im.resize(size,Image.Resampling.LANCZOS)
    draw=ImageDraw.Draw(im);draw.rectangle((0,0,size[0],64),fill=(25,35,40))
    try:font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',21)
    except OSError:font=ImageFont.load_default()
    draw.text((20,20),title,fill='white',font=font)
    im.save(path)

def main():
    with zipfile.ZipFile(ROOT/'output/revision2/arena_700_int.iff') as archive:
        level=json.loads(b'{'+archive.read('level.SCNE')+b'}')['level']
        palms=[n for n in level['Model'] if n.startswith('venice_v2:')]
        stats=[];row=[]
        for i,name in enumerate(palms):
            model=level['Model'][name];pos=positions(archive,model)
            error=float(np.max(np.abs(np.array([pos.min(0),pos.max(0)])-np.array([model['Min'],model['Max']]))))
            assert error<.05,error
            n=len(pos)
            for stream in model['VertexStream']:assert len(archive.read(stream['Binary']))==n*stream['Stride']==stream['Size']
            p=mesh(archive,level,name)
            render(p,OUT/f'palm_model_{i}.png',[1800,800,2000],[0,650,0],.65,size=(850,1100))
            p=[(a+np.array([(i-1)*850,0,0]),b) for a,b in p];row.extend(p)
            stats.append({'name':name,'vertices':n,'triangles':n//3,'quantization_max_error':error})
        render(row,OUT/'palm_models_preview.png',[0,850,4000],[0,670,0],.58,size=(1600,1100))
        parts=mesh(archive,level,level['Object']['__floor00__']['Target'])
        for obj in level['Object'].values():
            if str(obj.get('Target','')).startswith('venice_v2:'):parts.extend(mesh(archive,level,obj['Target'],obj['Matrix']))
        render(parts,OUT/'court_and_palms_layout.png',[5000,5200,6000],[0,0,0],.19,size=(1600,1250),
               title='DONOR COURT + 14 ADDED PALMS ONLY / OTHER DONOR MESHES HIDDEN / NOT IN-GAME')
        (OUT/'mesh_validation.json').write_text(json.dumps(stats,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(stats,indent=2))

if __name__=='__main__':main()
