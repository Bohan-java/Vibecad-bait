"""R11 native-package audit; model names identify resources, never replace them.

--capture-baseline records the still-published R10 package before replacement.
All streams, index buffers, object transforms, native material contracts and DDS
payloads of non-Chilis custom models must remain equal after export. Resource IDs
and model sequence numbers are normalized; actual bytes are not normalized.
No full-package CRC/hash rerun is needed: the build owns those checks.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'build/high_hoop/deps'))
from iff_codec import load_scne,resolve_binary,decode_attribute
from audit_fence_iff_current import decode_active, material_audit

BASELINE=ROOT/'validation/chilis-protected-native-baseline.json'

def jhash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf8')).hexdigest()

def read_json(path):return json.loads(path.read_text(encoding='utf8'))

class NativeSnapshot:
    def __init__(self, archive, labels):
        self.archive=archive
        self.level=load_scne(archive.read('level.SCNE'))['level']
        self.labels=labels
        self.hashes={};self.textures={};self.materials={}

    def bhash(self,binary):
        if binary not in self.hashes:
            resolved=resolve_binary(self.archive,binary)
            self.hashes[binary]=hashlib.sha256(self.archive.read(resolved)).hexdigest()
        return self.hashes[binary]

    def texture(self,name):
        if name in self.textures:return self.textures[name]
        if name not in self.level.get('Texture',{}):return {'external_pixelmap':name}
        data=copy.deepcopy(self.level['Texture'][name]);binary=data.get('Binary')
        if binary:
            dds=str(PurePosixPath(binary).with_suffix('.dds'))
            chosen=dds if dds in self.archive.NameToInfo else binary
            data['Binary']={'payload_sha256':self.bhash(chosen)}
        self.textures[name]=data
        return data

    def material(self,name):
        if name in self.materials:return self.materials[name]
        data=copy.deepcopy(self.level['Material'][name])
        for slot,resource in data.get('Resource',{}).items():
            if 'Pixelmap' in resource:resource['Pixelmap']=self.texture(resource['Pixelmap'])
        # Effect names stay unchanged unless their real contract changes.
        effect=data.get('Effect')
        if effect in self.level.get('Effect',{}):data['Effect']=self.level['Effect'][effect]
        script=data.get('Script')
        if script in self.archive.NameToInfo:data['Script']={'payload_sha256':self.bhash(script)}
        self.materials[name]={'canonical_sha256':jhash(data),'contract':data}
        return self.materials[name]

    def model(self,name,obj):
        data=copy.deepcopy(self.level['Model'][name])
        for stream in data.get('VertexStream',[]):
            stream['Binary']={'payload_sha256':self.bhash(stream['Binary'])}
        data['IndexBuffer']['Binary']={'payload_sha256':self.bhash(data['IndexBuffer']['Binary'])}
        if 'MatrixWeightsBuffer' in data:
            data['MatrixWeightsBuffer']['Binary']={'payload_sha256':self.bhash(data['MatrixWeightsBuffer']['Binary'])}
        if 'Transform' in data:
            data['Transform']={('$MODEL' if k==name else k):v for k,v in data['Transform'].items()}
        for prim in data.get('Prim',[]):
            if 'Mesh' in prim:prim['Mesh']=prim['Mesh'].replace(name,'$MODEL')
            if 'Material' in prim:prim['Material']=self.material(prim['Material'])['canonical_sha256']
        normalized_obj=copy.deepcopy(obj);normalized_obj['Target']='$MODEL'
        return {'canonical_sha256':jhash({'model':data,'object':normalized_obj}),
                'model_contract_sha256':jhash(data),'object_contract_sha256':jhash(normalized_obj),
                'vertex_streams':data.get('VertexStream',[]),'vertex_format':data.get('VertexFormat',{}),
                'index_buffer':data.get('IndexBuffer',{}),
                'material_contract_sha256':[p['Material'] for p in data['Prim'] if 'Material' in p]}

    def protected(self):
        rows={};excluded=[]
        for object_name,obj in self.level['Object'].items():
            model=obj.get('Target')
            if obj.get('Type')!='OBJECT' or model not in self.labels:continue
            label=self.labels[model]
            if 'chilis' in label.casefold():excluded.append(label);continue
            row=self.model(model,obj)
            rows.setdefault(label,[]).append(row)
        for label,parts in rows.items():parts.sort(key=lambda r:r['canonical_sha256'])
        return rows,sorted(set(excluded))

    def basket_snapshot(self):
        scoped=NativeSnapshot(self.archive,{})
        scoped.level=load_scne(self.archive.read('baskets.SCNE'))['baskets']
        scoped.hashes=self.hashes
        rows={}
        for object_name,obj in scoped.level['Object'].items():
            target=obj.get('Target')
            if obj.get('Type')=='OBJECT' and target in scoped.level['Model']:
                rows[object_name]=scoped.model(target,obj)
        assert rows
        return rows

def run_baseline(path,manifest,label_doc):
    assert manifest['revision']=='R10','Baseline must be published R10, before overwrite'
    assert not BASELINE.exists(),'Existing baseline must not be silently replaced'
    with zipfile.ZipFile(path) as archive:
        snapshot=NativeSnapshot(archive,{r['model']:r['source_object'] for r in label_doc['models']})
        rows,excluded=snapshot.protected()
        basket_raw=archive.read('baskets.SCNE')
        basket=load_scne(basket_raw)['baskets']
        basket_binaries={}
        for m in basket.get('Model',{}).values():
            for s in m.get('VertexStream',[]):basket_binaries[s['Binary']]=snapshot.bhash(s['Binary'])
            if 'IndexBuffer' in m:basket_binaries[m['IndexBuffer']['Binary']]=snapshot.bhash(m['IndexBuffer']['Binary'])
        result={'revision':'R10','status':'captured','archive':str(path),'archive_size':path.stat().st_size,
                'published_build_sha256':manifest['output_sha256'],'full_archive_hash_recomputed':False,
                'source_glb_sha256':manifest['source_glb_sha256'],
                'method':'Native VB/IB bytes, complete vertex format, normalized Model/Object/Material/Texture contracts and actual DDS bytes. Model sequence IDs normalized only.',
                'protected_source_object_count':len(rows),'protected_active_model_count':sum(map(len,rows.values())),
                'excluded_chilis_source_objects':excluded,'models_by_source_object':rows,
                'basket_scne_sha256':hashlib.sha256(basket_raw).hexdigest(),'basket_binary_sha256':basket_binaries,
                'basket_models_by_instance':snapshot.basket_snapshot()}
        BASELINE.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'status':'captured','report':str(BASELINE),'objects':len(rows),'models':sum(map(len,rows.values())),'excluded_chilis':len(excluded)}))

def triangles_world(archive,model,obj):
    p=decode_attribute(archive,model,'POSITION0')[:,:3]
    matrix=np.asarray(obj.get('Matrix',np.eye(4).reshape(-1)),dtype=float).reshape(4,4)
    p=(np.column_stack((p,np.ones(len(p))))@matrix)[:,:3][:,[2,0,1]]/100
    ib=model['IndexBuffer'];raw=archive.read(resolve_binary(archive,ib['Binary']))
    ix=np.frombuffer(raw,{'R16_UINT':'<u2','R32_UINT':'<u4'}[ib['Format']])
    ts=[]
    for prim in model['Prim']:
        draw=(prim.get('LodList') or [prim])[0]
        tri=ix[draw['Start']:draw['Start']+draw['Count']].reshape(-1,3)
        ts.append(p[tri])
    return np.concatenate(ts)

def audit_construction(snapshot,source):
    assert source['revision']=='R11' and source['status']=='passed'
    assert source['parameters']['terrace_side']==-1
    assert source['parameters']['terrace_side_confirmed'] is True,'Expected human-confirmed left return'
    assert source['unexpected_changes']==[] and source['lights_world_exposure_preserved'] is True
    furniture=source['furniture'];assert furniture.get('objects'),'Furniture must be included'
    expected=set(source['new_building_objects'])|set(furniture['objects'])
    expected={n for n in expected if n.startswith('R11 Chilis ')}
    removed=set(source['removed_old_building_objects'])|set(furniture['deleted_old_objects'])
    all_labels=set();by_label={};clouds={};tris={};materials={}
    for object_name,obj in snapshot.level['Object'].items():
        target=obj.get('Target')
        if obj.get('Type')!='OBJECT' or target not in snapshot.labels:continue
        label=snapshot.labels[target];all_labels.add(label)
        if label not in expected:continue
        model=snapshot.level['Model'][target]
        p,row=decode_active(snapshot.archive,model,obj)
        row.update(model=target,object=object_name,label=label)
        by_label.setdefault(label,[]).append(row);clouds.setdefault(label,[]).append(p)
        tris.setdefault(label,[]).append(triangles_world(snapshot.archive,model,obj))
        for material in row['materials']:
            if material not in materials:materials[material]=material_audit(snapshot.archive,snapshot.level,material)
    missing=sorted(expected-set(by_label));stale=sorted(removed&all_labels)
    assert not missing,('New building/furniture models missing',missing)
    assert not stale,('Old mixed facade or furniture still active',stale)
    clouds={k:np.concatenate(v) for k,v in clouds.items()}
    normals={};faces={}
    for face in ('entry','terrace'):
        f=source['facade_frames'][face];origin=np.asarray(f['origin']);out=np.asarray(f['outward_normal']);tangent=np.asarray(f['tangent'])
        label=('R11 Chilis building entry slender black window and double door frames' if face=='entry' else
               'R11 Chilis building terrace slender ivory weather screen mullions')
        ts=np.concatenate(tris[label]);cross=np.cross(ts[:,1]-ts[:,0],ts[:,2]-ts[:,0]);area=np.linalg.norm(cross,axis=1)
        valid=area>1e-10;norm=cross[valid]/area[valid,None];dots=norm@out
        # Both are volumetric frame members; front and rear faces are expected.
        # The transparent viewing portions intentionally have no opaque sheet.
        assert len(dots)>5 and np.isfinite(norm).all() and np.count_nonzero(dots>.8)>5
        p=clouds[label];local=np.column_stack(((p-origin)@tangent,(p-origin)@out,p[:,2]))
        faces[face]={'world_origin':origin.tolist(),'outward_normal':out.tolist(),'tangent':tangent.tolist(),
                     'native_component':label,'actual_component_bounds_m':[p.min(0).tolist(),p.max(0).tolist()],
                     'actual_component_local_u_depth_height_bounds_m':[local.min(0).tolist(),local.max(0).tolist()]}
        normals[face]={'native_triangles':len(dots),'minimum_outward_dot':float(dots.min()),
                       'area_weighted_outward_dot':float(np.average(dots,weights=area[valid])),
                       'outward_frame_triangles':int(np.count_nonzero(dots>.8)),
                       'finite_non_degenerate_frame_normals':True}
    assert np.asarray(faces['terrace']['world_origin'])[1]<-14.,'Terrace not at confirmed left return'
    assert abs(float(np.dot(faces['entry']['outward_normal'],faces['terrace']['outward_normal'])))<.35,'Two distinct facade directions lost'
    # The clear terrace bays intentionally use open geometry and real edge seams.
    # Probe actual native triangles at five bay centres to reject an accidental
    # opaque replacement sheet; this does not claim optical glass simulation.
    f=source['facade_frames']['terrace'];origin=np.asarray(f['origin']);out=np.asarray(f['outward_normal']);tangent=np.asarray(f['tangent'])
    all_tri=np.concatenate([np.concatenate(t) for t in tris.values()]);rel=all_tri-origin
    tu=rel@tangent;td=rel@out;tz=all_tri[:,:,2]
    screen_probes=[];width=source['parameters']['terrace_width']
    for i in range(5):
        u=-width/2+.26+(width-.52)*(i+.5)/5;z=1.60
        x0=tu[:,0];x1=tu[:,1];x2=tu[:,2];y0=tz[:,0];y1=tz[:,1];y2=tz[:,2]
        den=(y1-y2)*(x0-x2)+(x2-x1)*(y0-y2);ok=np.abs(den)>1e-12
        a=np.zeros(len(den));b=np.zeros(len(den))
        a[ok]=((y1[ok]-y2[ok])*(u-x2[ok])+(x2[ok]-x1[ok])*(z-y2[ok]))/den[ok]
        b[ok]=((y2[ok]-y0[ok])*(u-x2[ok])+(x0[ok]-x2[ok])*(z-y2[ok]))/den[ok];c=1-a-b
        inside=ok&(a>=-1e-9)&(b>=-1e-9)&(c>=-1e-9)
        depth=a*td[:,0]+b*td[:,1]+c*td[:,2]
        sheet=inside&(depth>-.10)&(depth<.15)
        assert not np.any(sheet),('Opaque native triangle covers terrace clear bay',i)
        screen_probes.append({'bay':i+1,'local_u_m':u,'height_m':z,'opaque_triangles_in_screen_depth_band':int(sheet.sum())})
    # Real projected door leaf geometry, independently decoded from final IFF.
    frame=source['facade_frames']['entry'];origin=np.asarray(frame['origin']);tangent=np.asarray(frame['tangent']);out=np.asarray(frame['outward_normal'])
    p=clouds['R11 Chilis building entry clear window and door perimeter seams'];u=(p-origin)@tangent;depth=(p-origin)@out
    pane=(np.abs(u)<1.30)&(p[:,2]>.14)&(p[:,2]<2.78)&(depth<-.015)
    door_sides={}
    for side in (-1,1):
        points=p[pane&(u*side>0)]
        assert len(points)>=6,('Missing double-door glass edge representation',side)
        uu=(points-origin)@tangent
        assert np.ptp(uu)>.80,'Door pane too narrow or collapsed'
        door_sides[str(side)]={'vertices':len(points),'local_u_bounds':[float(uu.min()),float(uu.max())],
                               'bounds_blender_m':[points.min(0).tolist(),points.max(0).tolist()]}
    # Three separated banks of nine pitched blades are real native geometry.
    blades=clouds['R11 Chilis building roof louvre pitched blades'];banks=[]
    f=source['facade_frames']['terrace'];blade_u=(blades-np.asarray(f['origin']))@np.asarray(f['tangent'])
    for center in (-1.57,0,1.57):
        points=blades[np.abs(blade_u-center)<.68]
        assert len(points)>20 and np.ptp(points[:,2])>.49,'Roof louvre bank missing'
        banks.append({'terrace_local_u_center_m':center,'vertices':len(points),'bounds_blender_m':[points.min(0).tolist(),points.max(0).tolist()]})
    assert sum(b['vertices'] for b in banks)==len(blades),'Unexpected extra louvre bank'
    # Conservative clear strip between facade objects and existing baseline fence.
    allp=np.concatenate(list(clouds.values()));low_height=(allp[:,2]>.04)&(allp[:,2]<2.2)&(np.abs(allp[:,1])<9.17)
    nearest=float(allp[low_height,0].max());fence_x=-16.08
    clearance=fence_x-nearest
    assert clearance>1.20,('New objects obstruct court-side access strip',clearance)
    entry_probes=[]
    rel=all_tri-origin;tu=rel@tangent;td=rel@out;tz=all_tri[:,:,2]
    for u in (-.64,.64):
        z=1.5;x0=tu[:,0];x1=tu[:,1];x2=tu[:,2];y0=tz[:,0];y1=tz[:,1];y2=tz[:,2]
        den=(y1-y2)*(x0-x2)+(x2-x1)*(y0-y2);ok=np.abs(den)>1e-12
        a=np.zeros(len(den));b=np.zeros(len(den))
        a[ok]=((y1[ok]-y2[ok])*(u-x2[ok])+(x2[ok]-x1[ok])*(z-y2[ok]))/den[ok]
        b[ok]=((y2[ok]-y0[ok])*(u-x2[ok])+(x0[ok]-x2[ok])*(z-y2[ok]))/den[ok];c=1-a-b
        inside=ok&(a>=-1e-9)&(b>=-1e-9)&(c>=-1e-9);depth=a*td[:,0]+b*td[:,1]+c*td[:,2]
        sheet=inside&(depth>-.1)&(depth<.15)
        assert not np.any(sheet),('Opaque native sheet covers entry door',u)
        entry_probes.append({'door_local_u_m':u,'height_m':z,'opaque_triangles_in_glass_depth_band':int(sheet.sum())})
    return {'expected_source_components':len(expected),'actual_native_models':sum(map(len,by_label.values())),
            'missing_new_components':missing,'old_replaced_components_still_active':stale,
            'components':by_label,'native_materials':materials,'facade_frames_and_bounds':faces,
            'actual_frame_winding_normals':normals,'double_door_glass_edge_geometry':door_sides,'roof_louvre_banks':banks,
            'two_clear_door_openings':entry_probes,
            'five_clear_weather_screen_bays':{'native_triangle_probes':screen_probes,
                                             'method':'Physically open clear portions with edge seams; no optical transparent sheet or unverified static alpha material.'},
            'court_side_walkway':{'baseline_fence_x_m':fence_x,'nearest_new_vertex_x_m':nearest,
                                 'conservative_clear_strip_m':clearance,'checked_height_interval_m':[.04,2.2],
                                 'method':'New-component native vertex bounds in the existing court-facing fence span. Not a full accessibility survey.'},
            'furniture_anchors_from_source_for_comparison_only':furniture.get('anchors'),
            'site_relationship':'User confirmed left return / negative Y; metric angle and dimensions remain photographic inference.',
            'source_preservation_audit':{'protected_objects':source['protected_objects'],'unexpected_changes':source['unexpected_changes'],
                                        'lights_world_exposure_preserved':source['lights_world_exposure_preserved']}}

def run_final(path,manifest,label_doc,source_report):
    assert manifest['revision']=='R11','Await R11 final publication'
    baseline=read_json(BASELINE)
    labels={r['model']:r['source_object'] for r in label_doc['models']}
    with zipfile.ZipFile(path) as archive:
        snapshot=NativeSnapshot(archive,labels);rows,excluded=snapshot.protected()
        old=baseline['models_by_source_object']
        missing=sorted(set(old)-set(rows));new=sorted(set(rows)-set(old));changed=[]
        for label in sorted(set(old)&set(rows)):
            if [r['canonical_sha256'] for r in old[label]]!=[r['canonical_sha256'] for r in rows[label]]:changed.append(label)
        assert not missing,('Missing protected source objects',missing)
        metadata_only=[]
        if changed:
            evidence=read_json(ROOT/'validation/chilis-protected-metadata-deltas.json')
            assert evidence['status']=='passed' and evidence['old_source_glb_sha256']==baseline['source_glb_sha256']
            explanations={r['source_object']:r for r in evidence['models']}
            assert set(changed)==set(explanations),'Unexplained native model differences'
            for label in changed:
                proof=explanations[label]
                assert proof['baseline_full_model_contract_reproduced_exactly']
                assert len(old[label])==len(rows[label])==1
                assert proof['baseline_canonical_sha256']==old[label][0]['canonical_sha256']
                assert proof['current_canonical_sha256']==rows[label][0]['canonical_sha256']
                # Every actual stream, vertex format, index descriptor, material
                # and object contract remains exact; only recoverable Duv hints
                # may be different. Restore the listed old values in memory and
                # demand the FULL original baseline hash, not a loose tolerance.
                for key in old[label][0]:
                    if key not in ('canonical_sha256','model_contract_sha256'):
                        assert old[label][0][key]==rows[label][0][key],(label,key)
                matching=[(obj['Target'],obj) for obj in snapshot.level['Object'].values() if labels.get(obj.get('Target'))==label]
                assert len(matching)==1;name,obj=matching[0];model=snapshot.level['Model'][name]
                reconstructed=copy.deepcopy(model)
                for change in proof['metadata_changes']:
                    assert '/Duv' in change['path']
                    keys=change['path'].strip('/').split('/');cursor=reconstructed
                    for key in keys[:-1]:cursor=cursor[int(key)] if isinstance(cursor,list) else cursor[key]
                    finalkey=int(keys[-1]) if isinstance(cursor,list) else keys[-1]
                    assert cursor[finalkey]==change['new'];cursor[finalkey]=change['old']
                snapshot.level['Model'][name]=reconstructed
                restored=snapshot.model(name,obj)
                snapshot.level['Model'][name]=model
                assert restored==old[label][0],('Difference outside documented Duv metadata',label)
                metadata_only.append(proof)
        assert not new,('New non-Chilis objects require explicit scope review',new)
        basket_same_bytes=hashlib.sha256(archive.read('baskets.SCNE')).hexdigest()==baseline['basket_scne_sha256']
        basket_rows=snapshot.basket_snapshot()
        assert basket_rows==baseline['basket_models_by_instance'],'Native basket geometry, weight streams or material bindings changed'
        for binary,expected in baseline['basket_binary_sha256'].items():assert snapshot.bhash(binary)==expected,('Basket binary changed',binary)
        source=read_json(source_report);construction=audit_construction(snapshot,source)
        report={'revision':'R11','status':'passed','actual_iff':str(path),'published_build_sha256':manifest['output_sha256'],
                'bytes':path.stat().st_size,'full_archive_crc_or_hash_recomputed':False,
                'geometry_origin':'Final IFF VB/IB and native SCNE transforms; source-name map identifies models only.',
                'protected_source_object_count':len(old),'protected_active_model_count':sum(map(len,old.values())),
                'missing_protected_source_objects':missing,'changed_protected_geometry_materials_or_transforms':[],
                'documented_streaming_hint_metadata_differences':metadata_only,'unexpected_new_non_chilis_source_objects':new,
                'basket_scne_byte_identical':basket_same_bytes,
                'basket_native_buffers_and_id_normalized_contracts_identical':True,'chilis_construction':construction,
                'checks':{'all_non_chilis_native_streams_and_index_buffers_exact':True,'all_non_chilis_native_materials_and_dds_exact':True,
                          'all_non_chilis_transforms_and_draws_exact':True,'native_basket_rig_preserved':True,
                          'all_new_building_and_furniture_components_present':True,'old_replaced_components_absent':True,
                          'distinct_entry_and_confirmed_left_return_terrace':True,'frames_have_valid_native_winding':True,
                          'two_door_frames_clear_openings_and_three_louvre_banks':True,'court_side_access_strip_clear':True,
                          'new_materials_have_no_emission_bindings':True},
                'limitations':['Native package invariance is an offline check; it cannot establish in-game appearance.']}
        output=ROOT/'validation/current-chilis-iff-audit.json'
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'status':'passed','report':str(output),'protected_objects':len(old),'protected_models':sum(map(len,old.values()))}))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--iff',default=str(ROOT/'output/arena_700_int.iff'))
    parser.add_argument('--capture-baseline',action='store_true')
    parser.add_argument('--source-report',default=str(ROOT/'validation/chilis-building-current.json'));args=parser.parse_args()
    path=Path(args.iff).resolve();assert path.is_relative_to(ROOT),'Workspace archive only'
    manifest=read_json(ROOT/'validation/iff-current.json');label_doc=read_json(ROOT/'validation/native-source-build.json')
    assert label_doc['source_glb_sha256']==manifest['source_glb_sha256'],'Stale source label map'
    start=(path.stat().st_size,path.stat().st_mtime_ns)
    if args.capture_baseline:run_baseline(path,manifest,label_doc)
    else:run_final(path,manifest,label_doc,Path(args.source_report))
    assert start==(path.stat().st_size,path.stat().st_mtime_ns),'IFF replaced during audit'

if __name__=='__main__':main()
