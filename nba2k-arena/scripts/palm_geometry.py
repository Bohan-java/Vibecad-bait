"""Decorative fan palms using the donor's existing CLOD vertex/material layout."""
from __future__ import annotations
import copy
import hashlib
import math
import zlib
import numpy as np

IDENTITY=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]

def norm(v):
    v=np.asarray(v,float)
    return v/max(np.linalg.norm(v),1e-10)

def tangent_samples(level,archive):
    samples=[]
    for name,m in level['Model'].items():
        vf=m.get('VertexFormat',{})
        if vf.get('POSITION0',{}).get('Format')!='R16G16B16A16_UNORM':continue
        if 'TANGENTFRAME0' not in vf:continue
        streams=m.get('VertexStream',[])
        ts=vf['TANGENTFRAME0'].get('Stream',0)
        needed=[streams[0]['Binary'],streams[ts]['Binary'],m['IndexBuffer']['Binary']]
        if any(f not in archive.namelist() for f in needed):continue
        pbytes=archive.read(needed[0]);n=len(pbytes)//streams[0]['Stride']
        ps=vf['POSITION0']
        p=np.ndarray((n,4),'<u2',pbytes,strides=(streams[0]['Stride'],2)).astype(float)/65535
        p=p*np.array(ps.get('Scale',[1]*4))+np.array(ps.get('Offset',[0]*4))
        nb=archive.read(needed[1])
        frames=np.ndarray((n,),'<u4',nb,offset=vf['TANGENTFRAME0'].get('ByteOffset',0),strides=(streams[ts]['Stride'],))
        ib=np.frombuffer(archive.read(needed[2]),'<u2')
        for prim in m.get('Prim',[]):
            inds=ib[prim.get('Start',0):prim.get('Start',0)+prim.get('Count',0)]
            for a,b,c in inds.reshape(-1,3)[::max(1,len(inds)//180)]:
                if max(a,b,c)>=n:continue
                cross=np.cross(p[b,:3]-p[a,:3],p[c,:3]-p[a,:3])
                if np.linalg.norm(cross)<1e-5:continue
                samples.append((norm(cross),int(frames[a])))
        if len(samples)>1000:break
    assert samples
    return np.array([s[0] for s in samples]),np.array([s[1] for s in samples],dtype='<u4')

def generate_palm(seed,height):
    rng=np.random.default_rng(seed)
    triangles={name:[] for name in ('palm_trunk','palm_leaf','palm_leaf_light','palm_leaf_dark','palm_dead')}
    def tri(mat,a,b,c,double=False):
        a,b,c=np.array(a,float),np.array(b,float),np.array(c,float)
        if np.linalg.norm(np.cross(b-a,c-a))<1e-6:return
        triangles[mat].append([a,b,c])
        if double:triangles[mat].append([c,b,a])
    bend=rng.uniform(-40,55,size=2)
    def center(t):return np.array([bend[0]*t*t,height*t,bend[1]*t*t])
    # Tapered ringed trunk; rings belong only to the added decorative mesh.
    segments=40;sides=12
    for ring in range(segments):
        t0,t1=ring/segments,(ring+1)/segments
        c0,c1=center(t0),center(t1)
        r0=(19-8*t0)*(1+0.11*(ring%2))
        r1=(19-8*t1)*(1+0.11*((ring+1)%2))
        for side in range(sides):
            angles=[side/sides*math.tau,(side+1)/sides*math.tau]
            a,b=[c0+np.array([r0*math.cos(q),0,r0*math.sin(q)]) for q in angles]
            c,d=[c1+np.array([r1*math.cos(q),0,r1*math.sin(q)]) for q in angles]
            # Match the donor's outward, counter-clockwise face orientation.
            tri('palm_trunk',a,d,b);tri('palm_trunk',a,c,d)
    crown=center(1)
    # Washingtonia-style fans: radial pleats and split blade tips, not broad
    # billboard rectangles. Both faces are explicit triangles.
    for leaf in range(36):
        azimuth=leaf*2.399963+rng.uniform(-.18,.18)
        outward=np.array([math.cos(azimuth),0,math.sin(azimuth)])
        side=np.array([-math.sin(azimuth),0,math.cos(azimuth)])
        tier=leaf%3
        reach=rng.uniform(65,140)
        rise={0:155,1:40,2:-65}[tier]+rng.uniform(-45,45)
        base=crown+np.array([0,rng.uniform(-35,25),0])
        hub=base+outward*reach+np.array([0,rise,0])
        material=('palm_leaf','palm_leaf_light','palm_leaf_dark')[leaf%3]
        # Slender petiole connects every fan to the crown.
        strip=side*2.2
        tri(material,base-strip,base+strip,hub+strip,True)
        tri(material,base-strip,hub+strip,hub-strip,True)
        axis=norm(outward+np.array([0,{0:1.3,1:.2,2:-1.2}[tier],0]))
        radius=rng.uniform(95,145)
        angle_span=2.20
        blade_segments=24
        pleat_normal=norm(np.cross(side,axis))
        for j in range(blade_segments):
            q0=-angle_span/2+j*angle_span/blade_segments
            q1=-angle_span/2+(j+1)*angle_span/blade_segments
            qm=(q0+q1)/2
            def point(q,r,fold=0):return hub+radius*r*(axis*math.cos(q)+side*math.sin(q))+pleat_normal*fold
            left=point(q0,.73)
            right=point(q1,.73)
            tip=point(qm,rng.uniform(.9,1.09),(-1 if j%2 else 1)*6)
            ridge=point(qm,.5,6)
            mat=material if j%4 else 'palm_leaf_dark'
            tri(mat,hub,left,ridge,True)
            tri(mat,hub,ridge,right,True)
            tri(mat,left,tip,ridge,True)
            tri(mat,ridge,tip,right,True)
    # Small dead-leaf skirt immediately below the crown, as in the photos.
    for leaf in range(14):
        angle=leaf/14*math.tau
        axis=np.array([math.cos(angle),0,math.sin(angle)])
        side=np.array([-math.sin(angle),0,math.cos(angle)])
        base=crown+axis*15
        end=base+axis*rng.uniform(35,72)+np.array([0,-rng.uniform(90,185),0])
        mid=(base+end)/2+axis*22
        tri('palm_dead',base,mid-side*15,end,True)
        tri('palm_dead',base,end,mid+side*15,True)
    return triangles

def add_palms(level,archive,texture_set,extra):
    template=next(m for n,m in level['Model'].items() if 'floor_apron:' in n)
    normals,frames=tangent_samples(level,archive)
    # Reuse the actual donor shader and resource slots for every new material.
    for label in ('palm_trunk','palm_leaf','palm_leaf_light','palm_leaf_dark','palm_dead'):
        mat=copy.deepcopy(level['Material']['clutchtime_floor_apron:floor_mat'])
        mat['Resource']['AlbedoMap']['Pixelmap']=texture_set[label][0]
        mat['Resource']['NormalAndRoughMap']['Pixelmap']=texture_set['surface_normal_rough'][0]
        mat['Parameter']['AlbedoModulate']=[1.,1.,1.,1.]
        mat['Parameter']['NormalHeight']=0.
        level['Material']['venice_v2:'+label]=mat
    models=[]
    for variant,height in enumerate((1040.,1220.,920.)):
        model_name=f'venice_v2:palm_model_{variant}'
        parts=generate_palm(950+variant,height)
        position=[];primitive_specs=[]
        for material,tris in parts.items():
            start=len(position)
            position.extend(np.asarray(tris).reshape(-1,3).tolist())
            primitive_specs.append((material,start,len(position)-start))
        pos=np.array(position)
        n=len(pos);assert n<65536
        tri=pos.reshape(-1,3,3)
        face_normals=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
        face_normals/=np.linalg.norm(face_normals,axis=1)[:,None]
        selected=[]
        for batch in np.array_split(face_normals,20):
            selected.extend(frames[np.argmax(batch@normals.T,axis=1)].tolist())
        selected=np.repeat(np.array(selected,dtype='<u4'),3)
        minimum=pos.min(0);maximum=pos.max(0);center=(minimum+maximum)/2
        span=float((maximum-minimum).max())
        offset=center-span/2
        radius=float(np.linalg.norm(pos-center,axis=1).max())
        quant=np.column_stack([np.clip(np.round((pos-offset)/span*65535),0,65535).astype('<u2'),np.full(n,65535,dtype='<u2')])
        uv=np.tile(np.array([[0,0],[32767,0],[0,32767]],dtype='<i2'),(n//3,1))
        attrs=np.zeros((n,20),dtype=np.uint8)
        attrs[:,:4]=selected.view(np.uint8).reshape(n,4)
        attrs[:,4:8]=uv.view(np.uint8).reshape(n,4)
        attrs[:,8:12]=uv.view(np.uint8).reshape(n,4)
        def resource(prefix,raw):
            name=f'{prefix}.{hashlib.sha256(raw).hexdigest()[:16]}.bin'
            extra[name]=raw
            return name
        vb=[quant.astype('<u2').tobytes(),uv.tobytes(),attrs.tobytes()]
        ib=np.arange(n,dtype='<u2').tobytes()
        vf=copy.deepcopy(template['VertexFormat'])
        vf['POSITION0']['Offset']=offset.tolist()+[0.]
        vf['POSITION0']['Scale']=[span,span,span,1.]
        for k,f in vf.items():
            if k.startswith('TEXCOORD'):
                f['Offset']=[0.,0.,0.,0.];f['Scale']=[1.,1.,1.,1.]
        prims=[]
        for material,start,count in primitive_specs:
            sub=pos[start:start+count]
            prims.append({'Material':'venice_v2:'+material,'Mesh':model_name+'_'+material,
                'Type':'TRIANGLE_LIST','BlendIndexRange':[0,0],'Start':start,'Count':count,
                'Radius':radius,'Center':center.tolist(),'Min':sub.min(0).tolist(),'Max':sub.max(0).tolist(),
                'LodList':[{'Start':start,'Count':count}]})
        model={'Clod':{'DataBuildMode':'2K21_FAST','Flag_ContinuousIndexBuffers':1,
             'Lods':{'Lod0':{'NumMaskBits':0,'NumVertices':n,'NumIndices':n,'NumTris':n//3}}},
             'Radius':radius,'Center':center.tolist(),'Min':minimum.tolist(),'Max':maximum.tolist(),
             'BlendIndexOffset':1,'BlendIndexRange':[0,0],'Transform':{model_name:None},
             'Prim':prims,'VertexFormat':vf,'IndexBuffer':{'Format':'R16_UINT','Size':len(ib),'Binary':resource('IndexBuffer',ib)},
             'IndexBufferCrc32':zlib.crc32(ib),
             'VertexStream':[{'Stride':stride,'Size':len(raw),'Binary':resource('VertexBuffer',raw)} for stride,raw in zip((8,4,20),vb)]}
        level['Model'][model_name]=model;models.append(model_name)
    floor=level['Model'][level['Object']['__floor00__']['Target']]
    x_limit=max(abs(floor['Min'][0]),abs(floor['Max'][0]))
    z_limit=max(abs(floor['Min'][2]),abs(floor['Max'][2]))
    points=[]
    for side in (-1,1):
        # Place every trunk on the existing ground-level apron, outside the
        # court, before the first seating row. Baseline balconies have stacked
        # levels; avoid planting into those balconies or their seating.
        for i,z in enumerate((-1650.,-1100.,-550.,0.,550.,1100.,1650.)):
            points.append((side*(x_limit+470.),0.,z,(i+(side==1))%3))
    placements=[]
    for i,(x,y,z,variant) in enumerate(points):
        model_name=models[variant]
        matrix=IDENTITY.copy();matrix[12:15]=[x,y,z]
        object_name=f'venice_v2:palm_{i:02d}'
        level['Object'][object_name]={'Type':'OBJECT','Target':model_name,'Transform':model_name,'Matrix':matrix}
        placements.append({'object':object_name,'model':model_name,'position':[x,y,z],
            'collision_added':False,'court_bounds_source':'donor __floor00__'})
    return placements
