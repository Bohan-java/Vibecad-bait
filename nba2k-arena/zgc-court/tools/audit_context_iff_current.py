"""R12 native archive audit. Capture R11 before publication, audit R12 after.

Source names identify native parts; all protected geometry and resources are
compared using the actual final IFF bytes, not source metadata. The only allowed
non-geometric difference in a protected part is demonstrable Prim Duv streaming
metadata: restoring its prior values must reproduce the complete original hash.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import numpy as np
from PIL import Image  # Load runtime Pillow before the legacy donor deps path.

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT.parent/'build/high_hoop/deps'))
from iff_codec import load_scne
from audit_chilis_iff_current import NativeSnapshot, jhash, read_json, audit_construction, triangles_world
from audit_fence_iff_current import decode_active, material_audit

BASELINE=ROOT/'validation/context-protected-native-baseline.json'
OUTPUT=ROOT/'validation/context-native-current.json'
PLANTING_ALLOWLIST={
    'R02 organic planted ground','R02 continuous low garden groundcover',
    'R02 curving raised stone edges','R02 curb expansion joints',
    'R02 arching ornamental grass','R02 grass warm tips',
    'R02 white allium flower stems','R02 fine white flower florets',
    'R02 shrub twig structure','R02 trees branching trunks','R02 flowerbed natural stones',
    *('R02 low groundcover leaf clusters '+str(i) for i in range(3)),
    *('R02 shrub leaves '+str(i) for i in range(3)),
    *('R02 broadleaf canopy '+str(i) for i in range(4))}
NEW_PREFIXES=('R12 Chilis ','R12 left context ','R12 right bench ','R12 skyline ')


def excluded(label):
    return ('chilis' in label.casefold() or label=='Glazed tower silhouette' or
            label.startswith(('Tower fine','Tower horizontal')) or label in PLANTING_ALLOWLIST or
            label.startswith(NEW_PREFIXES))


def duv_metadata(value,path=''):
    found={}
    if isinstance(value,dict):
        for key,item in value.items():
            here=path+'/'+key
            if key.startswith('Duv') and key[3:].isdigit():found[here]=copy.deepcopy(item)
            else:found.update(duv_metadata(item,here))
    elif isinstance(value,list):
        for index,item in enumerate(value):found.update(duv_metadata(item,path+'/'+str(index)))
    return found


def rows_for(snapshot):
    rows={};excluded_labels=[]
    for obj_name,obj in snapshot.level['Object'].items():
        target=obj.get('Target');label=snapshot.labels.get(target)
        if obj.get('Type')!='OBJECT' or label is None:continue
        if excluded(label):excluded_labels.append(label);continue
        row=snapshot.model(target,obj)
        row['duv_metadata']=duv_metadata(snapshot.level['Model'][target])
        rows.setdefault(label,[]).append(row)
    for parts in rows.values():parts.sort(key=lambda r:r['canonical_sha256'])
    return rows,sorted(set(excluded_labels))


def baseline(path,manifest,labels):
    assert manifest['revision']=='R11','Capture must precede R12 publication'
    if BASELINE.exists():
        existing=read_json(BASELINE)
        assert existing['published_build_sha256']==manifest['output_sha256'],'Refuse to overwrite a different baseline'
        if all('duv_metadata' in part for rows in existing['models'].values() for part in rows):
            print('R11 baseline already captured; preserved.');return
        # Enrich the same immutable R11 byte hashes with its Duv metadata. This
        # cannot replace or bless a changed baseline: every full native hash
        # must match the already captured rows before writing the added fields.
        with zipfile.ZipFile(path) as archive:
            snap=NativeSnapshot(archive,labels);updated,_=rows_for(snap)
        for label,parts in existing['models'].items():
            assert [p['canonical_sha256'] for p in parts]==[p['canonical_sha256'] for p in updated[label]]
        existing['models']=updated
        BASELINE.write_text(json.dumps(existing,ensure_ascii=False,indent=2),encoding='utf8')
        print('Existing R11 hashes preserved; Duv metadata attached.');return
    with zipfile.ZipFile(path) as archive:
        snap=NativeSnapshot(archive,labels);rows,exceptions=rows_for(snap)
        technical={k:v for k,v in snap.level['Object'].items() if v.get('Type')=='MARKER'}
        report={'revision':'R11','status':'captured','archive':str(path),'bytes':path.stat().st_size,
                'published_build_sha256':manifest['output_sha256'],'source_glb_sha256':manifest['source_glb_sha256'],
                'method':'Exact native VB/IB and resource hashes, normalized model/object/material/texture contracts; original Duv retained for provable metadata-only differences.',
                'protected_source_objects':len(rows),'protected_native_models':sum(map(len,rows.values())),
                'models':rows,'explicitly_excluded_source_objects':exceptions,
                'allowed_local_planting_names':sorted(PLANTING_ALLOWLIST),
                'basket_models':snap.basket_snapshot(),'original_technical_markers':technical,
                'Light':snap.level['Light'],'Attribute':snap.level['Attribute']}
        BASELINE.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'captured':str(BASELINE),'protected_objects':len(rows),'protected_models':sum(map(len,rows.values()))}))


def compare_protected(snapshot,current,old):
    assert set(current)==set(old),('Protected source object membership changed',sorted(set(old)-set(current)),sorted(set(current)-set(old)))
    meta=[]
    for label,before in old.items():
        after=current[label]
        if before==after:continue
        assert len(before)==len(after),('Protected native part count changed',label)
        matches=[(o['Target'],o) for o in snapshot.level['Object'].values()
                 if o.get('Type')=='OBJECT' and snapshot.labels.get(o.get('Target'))==label]
        restored=[];changes=[]
        for name,obj in matches:
            current_row=snapshot.model(name,obj)
            candidates=[b for b in before if all(current_row[k]==b[k] for k in
                ('object_contract_sha256','vertex_streams','vertex_format','index_buffer','material_contract_sha256'))]
            assert len(candidates)==1,('Actual geometry, material, object, or texture changed',label)
            b=candidates[0];model=snapshot.level['Model'][name];trial=copy.deepcopy(model)
            deltas=[]
            now_values=duv_metadata(trial)
            assert set(now_values)==set(b['duv_metadata']),('Duv structure changed',label)
            for path,prior in b['duv_metadata'].items():
                now=now_values[path]
                if now!=prior:
                    deltas.append({'path':path,'old':prior,'new':now})
                    keys=path.strip('/').split('/');cursor=trial
                    for key in keys[:-1]:cursor=cursor[int(key)] if isinstance(cursor,list) else cursor[key]
                    cursor[keys[-1]]=prior
            snapshot.level['Model'][name]=trial
            proof=snapshot.model(name,obj)
            snapshot.level['Model'][name]=model
            assert proof=={k:v for k,v in b.items() if k!='duv_metadata'},('Difference outside proven Duv metadata',label)
            restored.append(proof['canonical_sha256']);changes.extend(deltas)
        assert sorted(restored)==sorted(b['canonical_sha256'] for b in before)
        meta.append({'source_object':label,'restored_full_baseline_contract_exact':True,'changes':changes})
    return meta


def source_components(source):
    assert source['revision']=='R12' and source['status']=='passed'
    assert source['unexpected_changes']==[] and source['lights_world_exposure_preserved']
    actual_hash=hashlib.sha256((ROOT/'source/scene.blend').read_bytes()).hexdigest()
    assert source['published_source_sha256']==actual_hash,'Source changed after construction report'
    components=source['components']
    expected=set()
    for key,report in components.items():
        if key=='chilis':
            expected.update(report['new_building_objects']);expected.update(report['furniture']['objects'])
        else:expected.update(report['objects'])
    assert expected and all(n.startswith(NEW_PREFIXES) for n in expected),('Unexpected component names',sorted(n for n in expected if not n.startswith(NEW_PREFIXES)))
    return components,expected


def chilis_native(snapshot,report):
    # Reuse R11's native geometric/winding/clear-opening checks while mapping
    # labels in memory only. Native buffers and scene content are untouched.
    adapted=copy.deepcopy(report);adapted['revision']='R11'
    adapted['parameters'].update(terrace_side=-1,terrace_side_confirmed=True)
    def rename(value):
        if isinstance(value,dict):return {k:rename(v) for k,v in value.items()}
        if isinstance(value,list):return [rename(v) for v in value]
        if isinstance(value,str):return value.replace('R12 Chilis ','R11 Chilis ')
        return value
    adapted=rename(adapted)
    # R12 replaces many R11 names with equivalent planar details. Don't call
    # those retained semantic detail names stale; old curved-envelope names
    # remain in the obsolete list and are checked for actual absence.
    expected=set(adapted['new_building_objects'])|set(adapted['furniture']['objects'])
    adapted['removed_old_building_objects']=[n for n in adapted['removed_old_building_objects'] if n not in expected]
    adapted['furniture']['deleted_old_objects']=[n for n in adapted['furniture']['deleted_old_objects'] if n not in expected]
    saved=snapshot.labels
    snapshot.labels={k:v.replace('R12 Chilis ','R11 Chilis ') for k,v in saved.items()}
    try:details=audit_construction(snapshot,adapted)
    finally:snapshot.labels=saved
    # An independent native-vertex test proves the new envelope has a long
    # constant-X run and only small end roundovers, rather than an ellipse.
    label='R12 Chilis building rectangular restaurant roof and rear envelope'
    clouds=[]
    for obj in snapshot.level['Object'].values():
        if snapshot.labels.get(obj.get('Target'))==label:
            p,_=decode_active(snapshot.archive,snapshot.level['Model'][obj['Target']],obj);clouds.append(p)
    assert clouds,'Rectangular native roof absent'
    p=np.concatenate(clouds);params=report['parameters'];top=p[np.abs(p[:,2]-4.365)<.004]
    front=top[(top[:,1]>params['left_y']+params['corner_radius']-.004)&
              (top[:,1]<params['right_y']-params['corner_radius']+.004)&
              (top[:,0]>params['front_x']-.1)]
    assert len(front)>=2 and np.ptp(front[:,1])>28.0
    assert np.max(np.abs(front[:,0]-params['front_x']))<.004,'Native front still bows away from rectangle'
    details['native_rectangular_footprint']={'straight_front_vertices':len(front),
        'front_x_max_error_m':float(np.max(np.abs(front[:,0]-params['front_x']))),
        'straight_y_extent_m':float(np.ptp(front[:,1])), 'small_corner_radius_photo_estimate_m':params['corner_radius']}
    return details


def final(path,manifest,labels,source_path):
    assert manifest['revision']=='R12','Await R12 publication'
    original=read_json(BASELINE);source=read_json(source_path)
    components,expected=source_components(source)
    with zipfile.ZipFile(path) as archive:
        snapshot=NativeSnapshot(archive,labels);current,exceptions=rows_for(snapshot)
        metadata=compare_protected(snapshot,current,original['models'])
        assert snapshot.basket_snapshot()==original['basket_models'],'Native basket buffers/weights/bindings changed'
        assert snapshot.level['Light']==original['Light'] and snapshot.level['Attribute']==original['Attribute']
        for name,value in original['original_technical_markers'].items():
            assert snapshot.level['Object'].get(name)==value,('Existing technical marker changed',name)
        active_labels={labels[o['Target']] for o in snapshot.level['Object'].values()
                       if o.get('Type')=='OBJECT' and o.get('Target') in labels}
        obsolete={n for n in active_labels if n.startswith(('R11 Chilis ','Tower fine','Tower horizontal'))
                  or n=='Glazed tower silhouette'}
        assert not obsolete,('Obsolete restaurant or placeholder tower still active',sorted(obsolete))
        missing=expected-active_labels;assert not missing,('Missing source-to-IFF new objects',sorted(missing))
        unexpected={n for n in active_labels if n.startswith(NEW_PREFIXES)}-expected
        assert not unexpected,('Unexpected stale R12 objects',sorted(unexpected))
        construction=chilis_native(snapshot,components['chilis'])
        geometry={};materials={}
        for object_name,obj in snapshot.level['Object'].items():
            target=obj.get('Target');label=labels.get(target)
            if obj.get('Type')!='OBJECT' or label not in expected:continue
            model=snapshot.level['Model'][target];points,row=decode_active(archive,model,obj)
            assert np.isfinite(points).all(),label
            row.update(model=target,object=object_name)
            geometry.setdefault(label,[]).append(row)
            for material in row['materials']:
                if material not in materials:materials[material]=material_audit(archive,snapshot.level,material)
        # Only the explicitly reported old planting pieces may be cropped.
        left=components['left'];assert left['unexpected_changes']==[] and left['lights_world_exposure_unchanged']
        trimmed=left['trimmed_old_inferred_planting']
        assert all(item['name'] in PLANTING_ALLOWLIST and item['far_region_unchanged'] for item in trimmed)
        # The source builder provides exact per-polygon retention evidence; the
        # native audit separately protects all other objects byte-for-byte.
        report={'revision':'R12','status':'passed','actual_iff':str(path),
                'published_build_sha256':manifest['output_sha256'],'bytes':path.stat().st_size,
                'source_glb_sha256':manifest['source_glb_sha256'],
                'geometry_origin':'Actual IFF vertex/index buffers, DDS and native SCNE transforms; source map only identifies parts.',
                'protected_source_objects':len(current),'protected_native_models':sum(map(len,current.values())),
                'protected_geometry_material_transforms_equal':True,
                'documented_prim_duv_metadata_only':metadata,
                'native_basket_contract_identical':True,'original_technical_markers_identical':True,
                'global_native_light_and_attributes_identical':True,
                'expected_new_source_objects':len(expected),'actual_new_native_parts':sum(map(len,geometry.values())),
                'new_components':geometry,'new_materials':materials,'chilis':construction,
                'allowed_left_planting_source_proof':trimmed,
                'source_scene_hash_checked':True,'game_verified':False,
                'limits':['Positions and silhouettes estimated from photos; offline package checks do not establish gameplay or role-marker use.']}
    from r12_seating import audit_archive
    report['bench_seating']=audit_archive(path)
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'status':'passed','report':str(OUTPUT),'protected_objects':len(current),'new_source_objects':len(expected)}))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--capture-baseline',action='store_true')
    parser.add_argument('--iff',default=str(ROOT/'output/arena_700_int.iff'))
    parser.add_argument('--source-report',default=str(ROOT/'validation/context-current.json'));args=parser.parse_args()
    path=Path(args.iff).resolve();assert path.is_relative_to(ROOT)
    manifest=read_json(ROOT/'validation/iff-current.json');label_doc=read_json(ROOT/'validation/native-source-build.json')
    assert manifest['source_glb_sha256']==label_doc['source_glb_sha256'],'Stale label map'
    assert path.stat().st_size==manifest['output_bytes']
    labels={r['model']:r['source_object'] for r in label_doc['models']}
    start=(path.stat().st_size,path.stat().st_mtime_ns)
    if args.capture_baseline:baseline(path,manifest,labels)
    else:final(path,manifest,labels,Path(args.source_report))
    assert start==(path.stat().st_size,path.stat().st_mtime_ns),'IFF replaced during audit'


if __name__=='__main__':main()
