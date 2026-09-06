"""Close verified R5 coast gaps using native uniform CLOD position grids.

No original object, material, shader, floor or terrace is changed. The original
coast model keeps its exact ocean and a lower sand foundation; simple land tiles
use the R4 terrace lattice. This is geometry repair, not additional scenery.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from revision3_landscape import Mesh, IDENTITY
from revision3_mesh import export_mesh
from scene_primitives import iter_primitives

ROOT=Path(__file__).resolve().parents[1]
COAST='venice_v3:coast'
PREFIX='venice_v3:coast_r6_'


def decode_model(model, read):
    spec=model['VertexFormat']['POSITION0'];stream=model['VertexStream'][spec.get('Stream',0)]
    raw=read(stream['Binary'])
    if len(raw)!=stream['Size']:raise ValueError('Position size mismatch')
    if spec['Format']!='R16G16B16A16_UNORM':raise ValueError('Expected verified uniform CLOD format')
    packed=np.ndarray((len(raw)//stream['Stride'],4),'<u2',raw,
                      offset=spec.get('ByteOffset',0),strides=(stream['Stride'],2))
    p=packed[:,:3].astype(float)/65535*np.array(spec['Scale'][:3])+spec['Offset'][:3]
    ib=model['IndexBuffer'];index=np.frombuffer(read(ib['Binary']),'<u2')
    if len(index)*2!=ib['Size']:raise ValueError('Index size mismatch')
    prims=list(iter_primitives(model,indices=index,vertex_count=len(p)))
    return p,index,prims


def height_at(triangles,x,z):
    p=np.asarray(triangles,float)
    boxes=(p[:,:,0].min(1)<=x)&(p[:,:,0].max(1)>=x)&(p[:,:,2].min(1)<=z)&(p[:,:,2].max(1)>=z)
    p=p[boxes]
    if not len(p):return None
    a,b,c=p[:,0][:,[0,2]],p[:,1][:,[0,2]],p[:,2][:,[0,2]]
    e,f,q=b-a,c-a,np.array([x,z])-a
    det=e[:,0]*f[:,1]-e[:,1]*f[:,0];valid=np.abs(det)>1e-10
    u=np.zeros(len(p));v=np.zeros(len(p))
    u[valid]=(q[valid,0]*f[valid,1]-q[valid,1]*f[valid,0])/det[valid]
    v[valid]=(e[valid,0]*q[valid,1]-e[valid,1]*q[valid,0])/det[valid]
    inside=valid&(u>=-1e-10)&(v>=-1e-10)&(u+v<=1+1e-10)
    if not inside.any():return None
    y=p[:,0,1]+u*(p[:,1,1]-p[:,0,1])+v*(p[:,2,1]-p[:,0,1])
    return float(y[inside].max())


def ray_hits(triangles,origin,aim,limit=80000.):
    p=np.asarray(triangles);o=np.asarray(origin,float);d=np.asarray(aim,float)-o;d/=np.linalg.norm(d)
    e,f=p[:,1]-p[:,0],p[:,2]-p[:,0]
    h=np.cross(d,f);det=(e*h).sum(1);valid=np.abs(det)>1e-9
    inv=np.zeros(len(p));inv[valid]=1/det[valid]
    s=o-p[:,0];u=(s*h).sum(1)*inv;q=np.cross(s,e);v=(q*d).sum(1)*inv;t=(q*f).sum(1)*inv
    mask=valid&(u>=-1e-10)&(v>=-1e-10)&(u+v<=1+1e-10)&(t>0)&(t<=limit)
    return bool(mask.any())


def _export_grid(level,extra,name,mesh,offset,span):
    """Keep the verified exporter, then encode POSITION on one explicit grid.

    The native VS uses one scalar for XYZ: %91=span/65535 and %375..377.
    Input faces already lie on this lattice. Tangent/UV/index generation remains
    the existing exporter's responsibility; only its position packing is replaced.
    """
    faces=np.concatenate([np.asarray(v) for v in mesh.parts.values()]);points=faces.reshape(-1,3)
    offset=np.asarray(offset,float)
    encoded=np.rint((points-offset)/span*65535)
    if (encoded<0).any() or (encoded>65535).any():raise ValueError(f'Grid overflow: {name}')
    decoded=encoded/65535*span+offset
    error=float(np.abs(decoded-points).max())
    if error>1e-7:raise ValueError(f'Input is not on shared native lattice: {name}: {error}')
    report=export_mesh(level,extra,name,mesh.parts,uv_parts=mesh.uv,normal_parts=mesh.normals)
    raw=np.column_stack((encoded.astype('<u2'),np.full(len(points),65535,dtype='<u2'))).astype('<u2').tobytes()
    key='VertexBuffer.'+hashlib.sha256(raw).hexdigest()[:16]+'.bin'
    extra[key]=raw;model=level['Model'][name]
    model['VertexStream'][0]={'Stride':8,'Size':len(raw),'Binary':key}
    model['VertexFormat']['POSITION0']['Scale']=[float(span)]*3+[1.]
    model['VertexFormat']['POSITION0']['Offset']=offset.tolist()+[0.]
    p,index,_=decode_model(model,extra.__getitem__)
    native=p[index].reshape(-1,3,3)
    cross=np.cross(native[:,1]-native[:,0],native[:,2]-native[:,0])
    if (np.linalg.norm(cross,axis=1)<=1e-8).any() or (cross[:,1]<=0).any():
        raise ValueError(f'Invalid exported terrain faces: {name}')
    report.update(native_position_step_cm=span/65535,shared_lattice_max_error_cm=error,
                  all_exported_triangles_upward=True)
    return report,native


def apply_coast(level,archive,extra,*,output_dir=ROOT/'build/revision6/coast'):
    before_objects=copy.deepcopy(level['Object']);old=level['Model'][COAST]
    work=copy.deepcopy(level);created={}
    terrace=level['Model']['venice_v3:grass_terraces'];promenade=level['Model']['venice_v3:promenade']
    tp,ti,_=decode_model(terrace,archive.read);pp,pi,_=decode_model(promenade,archive.read)
    cp,ci,prims=decode_model(old,archive.read)
    old_terrain=np.concatenate((tp[ti].reshape(-1,3,3),pp[pi].reshape(-1,3,3)))
    spec=terrace['VertexFormat']['POSITION0'];span=float(spec['Scale'][0]);anchor=np.array(spec['Offset'][:3])
    if span!=16000. or spec['Scale'][:3]!=[span]*3:raise ValueError('Unexpected R4 terrace lattice')
    q=span/65535
    snap=lambda values:np.rint((np.asarray(values,float)-anchor)/q)*q+anchor
    snap_axis=lambda value,axis:float(np.rint((value-anchor[axis])/q)*q+anchor[axis])
    floor_axis=lambda value,axis:float(np.floor((value-anchor[axis])/q)*q+anchor[axis])
    ceil_axis=lambda value,axis:float(np.ceil((value-anchor[axis])/q)*q+anchor[axis])
    xmin,xmax=float(tp[:,0].min()),float(tp[:,0].max())
    pmin,pmax=float(pp[:,0].min()),float(pp[:,0].max())
    pz=float(pp[:,2].max());py=float(pp[:,1].min())
    edge=tp[np.isclose(tp[:,0],xmax,atol=1e-8,rtol=0)][:,[2,1]]
    pairs={float(z):float(y) for z,y in edge};edge_z=np.array(sorted(pairs));edge_y=np.array([pairs[z] for z in edge_z])
    if edge_z[0]!=-8000 or edge_z[-1]!=8000:raise ValueError('Unexpected native terrace end')
    top=lambda z:float(np.interp(z,edge_z,edge_y))
    ocean_prim=next(p for p in prims if p['Material']=='venice_v3:ocean')
    ocean=cp[ci[ocean_prim['Start']:ocean_prim['Start']+ocean_prim['Count']]].reshape(-1,3,3)
    sea_x=float(ocean[:,:,0].min());sea_y=float(ocean[:,:,1].min());extent=float(ocean[:,:,2].max())
    if not np.all(ocean[:,:,1]==sea_y):raise ValueError('Expected one native sea level')

    # Ocean and its distant, lower sand foundation retain the old coarse grid.
    # The foundation closes the far western finite land edge; it cannot occlude
    # the ocean because it sits one full old grid step below it.
    coarse=Mesh()
    for face in ocean:coarse.tri('ocean',face,face[:,[0,2]]/1800.)
    ospec=old['VertexFormat']['POSITION0'];old_span=float(ospec['Scale'][0]);old_offset=np.array(ospec['Offset'][:3])
    old_q=old_span/65535;foundation_y=sea_y-old_q
    coarse.plane('sand',float(old_offset[0]),sea_x+old_q,-extent,extent,foundation_y,tile=240.)
    work['Model'].pop(COAST)
    reports=[];actual=[]
    r,native=_export_grid(work,created,COAST,coarse,old_offset,old_span);reports.append(r);actual.append(native)

    tiles={}
    def region(material,x0,x1,z0,z1,height,*,zs=()):
        x0,x1=sorted((snap_axis(x0,0),snap_axis(x1,0)));z0,z1=sorted((snap_axis(z0,2),snap_axis(z1,2)))
        if x1-x0<q*.5 or z1-z0<q*.5:return
        xc=[x0,x1]+[anchor[0]+k*span for k in range(-20,21) if x0<anchor[0]+k*span<x1]
        zc=[z0,z1]+[anchor[2]+k*span for k in range(-20,21) if z0<anchor[2]+k*span<z1]
        zc += [snap_axis(z,2) for z in zs if z0<z<z1]
        xc,zc=sorted(set(xc)),sorted(set(zc))
        for left,right in zip(xc[:-1],xc[1:]):
            for a,b in zip(zc[:-1],zc[1:]):
                tile=(int(math.floor(((left+right)/2-anchor[0])/span)),int(math.floor(((a+b)/2-anchor[2])/span)))
                mesh=tiles.setdefault(tile,Mesh())
                points=snap([[left,height(left,a),a],[left,height(left,b),b],
                             [right,height(right,b),b],[right,height(right,a),a]])
                mesh.quad(material,points,points[:,[0,2]]/({'grass':180.,'sand':240.}.get(material,220.)))

    far=ceil_axis(extent,2)
    west=float(cp[:,0].min());back_y=snap_axis(.41123445486300625,1)
    path_x=snap_axis(4500.,0)
    knee_x=floor_axis(sea_x-2*q,0);toe_x=ceil_axis(sea_x+2*q,0)
    knee_y=ceil_axis(sea_y+q,1);toe_y=floor_axis(sea_y-q,1)
    # Preserve the existing near terrain's hole, not a new covering slab.
    region('sand',west,pmin,-far,far,lambda x,z:back_y)
    join0=floor_axis(pz-2*q,2);join1=ceil_axis(pz+2.,2)
    backing_y=floor_axis(min(py,float(tp[:,1].min()))-2*q,1)
    def back_height(x,z):
        t=float(np.clip((abs(z)-join0)/(join1-join0),0,1))
        return backing_y+(back_y-backing_y)*t
    for sign in (-1,1):
        region('sand',pmin,xmin,*sorted((sign*join0,sign*far)),back_height,zs=[sign*join1])
        region('grass',xmin,xmax,*sorted((sign*8000.,sign*far)),lambda x,z:top(z))
    # A sub-centimeter recessed concrete strip closes the old 0.019 cm seam.
    region('concrete',pmax-2*q,xmin+2*q,-pz-2*q,pz+2*q,lambda x,z:backing_y)
    region('concrete',xmax,path_x,-far,far,lambda x,z:top(z),zs=edge_z)
    region('sand',path_x,knee_x,-far,far,
           lambda x,z:top(z)+(knee_y-top(z))*(x-path_x)/(knee_x-path_x),zs=edge_z)
    region('sand',knee_x,toe_x,-far,far,
           lambda x,z:knee_y+(toe_y-knee_y)*(x-knee_x)/(toe_x-knee_x))
    if len(tiles)>63:raise ValueError(f'Unexpected terrain tile count: {len(tiles)}')
    for (ix,iz),mesh in sorted(tiles.items()):
        name=PREFIX+f'land_x{ix:+03d}_z{iz:+03d}'
        offset=anchor+np.array([ix*span,0.,iz*span])
        r,native=_export_grid(work,created,name,mesh,offset,span);reports.append(r);actual.append(native)
        work['Object'][name]={'Type':'OBJECT','Target':name,'Transform':name,'Matrix':IDENTITY.copy()}
    generated=np.concatenate(actual);terrain=np.concatenate((old_terrain,generated))
    coverage=[]
    for sign in (-1,1):
        for x,z,minimum in ((4300,15000,99),(6500,22500,20),(3000,30000,99),
                            (3000,8000.3,99),(-3000,6500.5,-2),(1100.09,5500,-2)):
            y=height_at(terrain,x,sign*z)
            coverage.append({'xz_cm':[x,sign*z],'height_cm':y,'minimum_expected_height_cm':minimum})
            if y is None or y<minimum:raise ValueError(f'Repaired surface missing: {coverage[-1]}')
    near_points=0
    for z in np.r_[np.linspace(-7999,7999,49),[-6499,-5500,-5051,5051,5500,6499]]:
        for x in np.linspace(1101,4099,25):
            old_y=height_at(old_terrain,float(x),float(z));new_y=height_at(terrain,float(x),float(z))
            if old_y is None or new_y is None or abs(old_y-new_y)>1e-7:raise ValueError('Near terrace changed or became occluded')
            near_points+=1
    aims=[[4300,98,-15000],[6500,30,-22500],[3000,98,-30000],[-35000,-38,-60000]]
    rays=[{'aim_cm':p,'hit':ray_hits(terrain,[0,850,2200],p)} for p in aims]
    if not all(r['hit'] for r in rays):raise ValueError(f'Ground is still open from the principal view: {rays}')
    # Old ocean is retained exactly; toe extends below it, never as a coplanar cover.
    ocean_after=actual[0][:len(ocean)]
    if not np.allclose(ocean_after,ocean,atol=1e-8,rtol=0):raise ValueError('Native ocean vertices changed')
    if not (toe_x>sea_x and toe_y<sea_y and knee_x<sea_x):raise ValueError('Beach toe does not cross below sea')
    if {k:work['Object'][k] for k in before_objects}!=before_objects:raise ValueError('Old object changed')
    for key,raw in created.items():
        if key in extra and extra[key]!=raw:raise ValueError('Resource collision')
    # Commit only the authorized scene records after geometry validation.
    changed=[COAST]+[n for n in work['Model'] if n.startswith(PREFIX)]
    for name in changed:level['Model'][name]=work['Model'][name]
    for name in work['Object']:
        if name.startswith(PREFIX):level['Object'][name]=work['Object'][name]
    for key,raw in created.items():
        extra[key]=raw
    report={'changed_existing_models':[COAST],'new_models':changed[1:],'new_objects':changed[1:],
            'old_objects_preserved':True,'old_materials_and_game_fields_preserved':True,
            'models':reports,'tile_count':len(tiles),'native_grid_span_cm':span,'native_grid_step_cm':q,
            'uniform_scale_shader_evidence':'VS.3e4e8775aa14fa50: %91 and %375..380 use one XYZ scale',
            'coverage':coverage,'near_terrace_points_unchanged':near_points,'main_view_terrain_rays':rays,
            'native_ocean_preserved':True,'ocean_left_x_cm':sea_x,'ocean_level_y_cm':sea_y,
            'toe_x_cm':toe_x,'toe_y_cm':toe_y,'toe_submergence_cm':sea_y-toe_y,
            'foundation_y_cm':foundation_y,'foundation_below_ocean_cm':sea_y-foundation_y,
            'land_extent_abs_z_cm':far,'original_coast_position_step_cm':old_q,
            'new_binary_resources':sorted(created),'game_runtime_verified':False}
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'coast_report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report
