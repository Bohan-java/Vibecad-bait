"""Internal source-to-native intermediate used by build_current_iff.py.

This intermediate must pass repair_iff.py before being published for game use.
Original visible donor instances are replaced; native basket runtime anchors and
animated rim are retained. No game installation is read or written.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import time
import zipfile
import zlib
import numpy as np
from PIL import Image
from iff_codec import (load_scne,dump_scne,make_static_model,decode_attribute,
                       decode_normals,hide_native_basket_visuals)
import native_textures

ROOT=Path(__file__).resolve().parents[1]
DONOR=ROOT.parent/'洛克公园/arena_blacktop_ext.iff'
TEMPLATE='electrical_doublepanela_metal:electrical_doublepanela_metal_piping_mat'
GLASS='cup_glass_beveragefrosted:cup_glass_mat'

def hash_file(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def clamp_mesh_uv(p,n,uv,indices):
    """Split at texture borders before clamping, preserving world artwork scale.

    A native repeat sampler then sees only safe interior atlas coordinates;
    triangle interpolation across an out-of-range apron cannot squash the art.
    """
    triangles=[]
    for ix in indices.reshape(-1,3):
        polygons=[np.concatenate((p[ix],n[ix],uv[ix]),axis=1)]
        for axis in (6,7):
            for boundary in (0.,1.):
                result=[]
                for poly in polygons:
                    d=poly[:,axis]-boundary
                    if d.min()>=-1e-10 or d.max()<=1e-10:result.append(poly);continue
                    lower=[];upper=[]
                    for i,a in enumerate(poly):
                        b=poly[(i+1)%len(poly)];da=a[axis]-boundary;db=b[axis]-boundary
                        if da<=1e-10:lower.append(a)
                        if da>=-1e-10:upper.append(a)
                        if da*db<-1e-20:
                            x=a+(b-a)*(-da)/(db-da);lower.append(x);upper.append(x)
                    for piece in (lower,upper):
                        if len(piece)>=3:result.append(np.asarray(piece))
                polygons=result
        for poly in polygons:
            for j in range(1,len(poly)-1):triangles.extend((poly[0],poly[j],poly[j+1]))
    data=np.asarray(triangles)
    data[:,6:8]=np.clip(data[:,6:8],1/65536,1-1/65536)
    unique,inverse=np.unique(data,axis=0,return_inverse=True)
    normals=unique[:,3:6];normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-12)
    return unique[:,:3],normals,unique[:,6:8],inverse.astype('<u2')

def skip_runtime_duplicate(part):
    name=part['object'].lower()
    if 'hoops' not in part['tags']:return False
    # The actual animated rim and cloth are drawn by baskets.SCNE / MAIN.
    return (name.startswith('rim.') or name.startswith('rim connector.') or
            name.startswith('rim mounting plate.') or ' net ' in name or
            ' net.' in name or 'net fiber' in name or 'net twist' in name)

def add_material(material,level,extra,folder,texture_reports):
    mid=material['id'];name=f'zgc_r03:material_{mid:03d}'
    albedo=native_textures.albedo_image(material,folder)
    ak,at,ar=native_textures.encode(albedo,extra)
    level['Texture'][ak]=at;texture_reports.append({'source_material':material['name'],'role':'albedo',**ar})
    transparent=material['alpha_mode']!='OPAQUE'
    mat=copy.deepcopy(level['Material'][GLASS if transparent else TEMPLATE])
    metallic=material['metallic']
    if material['metallic_roughness_texture']:
        orm=Image.open(folder/material['metallic_roughness_texture']['image']['file']).convert('RGB')
        metallic*=float(np.median(np.asarray(orm)[:,:,2]))/255.
    par=mat['Parameter'];par.update(AlbedoModulate=[1.,1.,1.,1.],DefaultMetalness=metallic)
    if transparent:
        assert albedo.mode=='RGBA'
        mat['Resource']={'AlbedoMapBC3':{'Pixelmap':ak}}
        par['DefaultRoughness']=material['roughness']
    else:
        nk,nt,nr=native_textures.encode(native_textures.normal_rough_image(material,folder),extra,linear=True)
        level['Texture'][nk]=nt;texture_reports.append({'source_material':material['name'],'role':'neutral_normal_roughness',**nr})
        mat['Resource']={'AlbedoMap':{'Pixelmap':ak},'NormalAndRoughMap':{'Pixelmap':nk}}
        par.update(NormalHeight=0.,EmissiveIntensity=0.,EmissiveTint=[0.,0.,0.],EmissiveDefaultAlbedo=[0.,0.,0.])
    if material['double_sided']:
        for technique in mat['Technique'].values():
            for render_pass in technique.get('Pass',{}).values():render_pass['CULLMODE']='NONE'
    level['Material'][name]=mat
    return name

class MemoryArchive:
    def __init__(self,entries):self.entries=entries;self.NameToInfo=entries
    def read(self,name):return self.entries[name]

def verify_mesh(model,p,n,uv,indices,entries):
    archive=MemoryArchive(entries)
    restored=decode_attribute(archive,model,'POSITION0')[:,:3]
    restored_uv=decode_attribute(archive,model,'TEXCOORD0')[:,:2]
    restored_n=decode_normals(decode_attribute(archive,model,'TANGENTFRAME0'))
    ib=archive.read(model['IndexBuffer']['Binary'])
    assert np.array_equal(np.frombuffer(ib,'<u2'),indices)
    assert zlib.crc32(ib)==model['IndexBufferCrc32']
    pos_error=float(np.linalg.norm(restored-p,axis=1).max())
    uv_error=float(np.abs(restored_uv-uv).max())
    normal_angle=float(np.degrees(np.arccos(np.clip(np.einsum('ij,ij->i',restored_n,n),-1,1))).max())
    assert pos_error<.5 and uv_error<.02 and normal_angle<.3,(pos_error,uv_error,normal_angle)
    return {'position_error_cm':pos_error,'uv_error':uv_error,'normal_angle_deg':normal_angle}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--assets',default=str(ROOT/'.build-staging/iff/assets'))
    parser.add_argument('--output',default=str(ROOT/'.build-staging/source-base/arena_700_int.iff'))
    parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    folder=Path(args.assets).resolve();output=Path(args.output).resolve()
    if not folder.is_relative_to(ROOT) or not output.is_relative_to(ROOT):raise ValueError('Outside project')
    assets=json.loads((folder/'assets.json').read_text(encoding='utf8'))
    extra={};reports=[];mesh_reports=[];skipped=[]
    with zipfile.ZipFile(DONOR) as donor:
        document=load_scne(donor.read('level.SCNE'));level=document['level']
        original_objects=len(level['Object']);original_models=len(level['Model'])
        kept={k:v for k,v in level['Object'].items() if v.get('Type')=='MARKER' and not k.startswith('camera_cull_volume_')}
        assert len(kept)==14
        marker_names=list(kept)
        old_visible=sum(v.get('Type')=='OBJECT' for v in level['Object'].values())
        level['Object']=kept;level['Model']={};level['Animation']={}
        print('Encoding source textures',flush=True)
        used_materials={p['material'] for p in assets['parts'] if not skip_runtime_duplicate(p)}
        names={m['id']:add_material(m,level,extra,folder,reports) for m in assets['materials'] if m['id'] in used_materials}
        print('Encoding native geometry',flush=True)
        for part in assets['parts']:
            if skip_runtime_duplicate(part):skipped.append(part['object']);continue
            source=np.load(folder/part['file']);p=source['position_cm'];n=source['normal'];uv=source['uv'];ix=source['indices']
            mat=assets['materials'][part['material']];tex=mat['base_color_texture']
            clamped=False
            if tex and (tex['sampler'].get('wrapS')==33071 or tex['sampler'].get('wrapT')==33071) and (uv.min()<0 or uv.max()>1):
                p,n,uv,ix=clamp_mesh_uv(p,n,uv,ix);clamped=True
            name='zgc_r03:'+part['key']
            model,obj=make_static_model(name,p,n,uv,ix,names[part['material']],extra)
            level['Model'][name]=model;level['Object'][name]=obj
            mesh_reports.append({'model':name,'source_object':part['object'],'tags':part.get('tags',[]),'material':names[part['material']],
                                 'vertices':len(p),'triangles':len(ix)//3,'clipped_atlas_border':clamped,
                                 **verify_mesh(model,p,n,uv,ix,extra)})
        extra['level.SCNE']=dump_scne(document)
        bd=load_scne(donor.read('baskets.SCNE'))
        bd['baskets'],basket_report=hide_native_basket_visuals(bd['baskets'],donor,extra,keep_rim=True)
        extra['baskets.SCNE']=dump_scne(bd)
        sd=load_scne(donor.read('speedtree.SCNE'))
        for data in sd.values():
            data['Object']={};data['Model']={}
        extra['speedtree.SCNE']=dump_scne(sd)
        # Optional donor effects/crowd changes are kept explicit below after
        # their native SCNE schemas have been inspected.
        report={'revision':'source-intermediate','game_tested':False,'game_target':'Blacktop arena_700_int.iff',
                'source_glb':assets.get('source_glb'),'source_glb_sha256':assets.get('source_glb_sha256'),
                'source_assets_metadata':str(folder/'assets.json'),
                'donor':str(DONOR),'donor_sha256':hash_file(DONOR),
                'old_visible_objects_removed':old_visible,'old_cull_markers_removed':original_objects-old_visible-14,'old_models_removed':original_models,
                'technical_markers_retained':marker_names,'models':mesh_reports,'textures':reports,
                'basket':basket_report,'static_rim_and_net_omitted':sorted(set(skipped)),
                'limitations':['Not launched or tested in NBA 2K26.','Native animated rim and runtime cloth retained; preview static net is omitted.',
                               'New static material tangent normal maps neutral; actual geometry and albedo/roughness are exported.',
                               'Crowd data and lighting runtime are inherited; placement and appearance require in-game checking.',
                               'Native metalness is a scalar sampled from the median of each source metallic map.']}
        stage=ROOT/'.build-staging/iff/native';stage.mkdir(parents=True,exist_ok=True)
        for name,data in extra.items():(stage/name).write_bytes(data)
        report['extra_entry_count']=len(extra)
        if not args.prepare_only:
            output.parent.mkdir(parents=True,exist_ok=True);pending=output.with_suffix('.iff.pending')
            print('Writing single IFF container',flush=True)
            with zipfile.ZipFile(pending,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as target:
                for item in donor.infolist():
                    if item.filename in extra:continue
                    with donor.open(item) as src,target.open(copy.copy(item),'w',force_zip64=item.file_size>=2**31) as dst:
                        shutil.copyfileobj(src,dst,8*1024*1024)
                for name,data in extra.items():target.writestr(name,data,compress_type=zipfile.ZIP_STORED)
            print('Reading complete IFF to check CRC and resource payloads',flush=True)
            with zipfile.ZipFile(pending) as check:
                assert check.testzip() is None
                assert len(check.namelist())==len(set(check.namelist()))
                for name,data in extra.items():assert check.read(name)==data,name
                assert load_scne(check.read('level.SCNE'))==document
                report['archive_entries']=len(check.namelist())
            pending.replace(output)
            report.update(output=str(output),output_bytes=output.stat().st_size,output_sha256=hash_file(output),archive_crc_verified=True)
        (ROOT/'validation/native-source-build.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({k:report.get(k) for k in ('output','output_bytes','output_sha256','archive_crc_verified','extra_entry_count')},ensure_ascii=True),flush=True)

if __name__=='__main__':main()
