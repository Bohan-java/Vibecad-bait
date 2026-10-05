"""Prove exact R13 preservation apart from bounded, derived Duv float drift.

Read-only for both IFF files. No tolerance applies to buffers, vertex formats,
bounds, object/material contracts, or any Model field other than named Duv
streaming hints. The output explicitly records every tolerated scalar change.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile

from audit_chilis_iff_current import NativeSnapshot,jhash
from audit_r13_native import native_snapshot

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'validation/r13-native-duv-audit.json'
ABS_LIMIT=3e-7
REL_LIMIT=3e-6

def read(path):return json.loads(Path(path).read_text(encoding='utf8'))

def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while chunk:=f.read(8*1024*1024):h.update(chunk)
    return h.hexdigest()

def original_labels():
    """Recover unique original labels from still-published actual-IFF GLB."""
    manifest=read(ROOT/'public/game-preview/manifest.json')
    with (ROOT/'public/game-preview/current.glb').open('rb') as f:
        assert f.read(4)==b'glTF';f.seek(12)
        count,kind=struct.unpack('<II',f.read(8));assert kind==0x4e4f534a
        doc=json.loads(f.read(count))
    result={}
    for node in doc['nodes']:
        model=node.get('extras',{}).get('native_model')
        if model:result.setdefault(node['name'],[]).append(model)
    return result,manifest

def normalized(snapshot,name):
    data=copy.deepcopy(snapshot.level['Model'][name])
    for stream in data.get('VertexStream',[]):
        stream['Binary']={'payload_sha256':snapshot.bhash(stream['Binary'])}
    data['IndexBuffer']['Binary']={'payload_sha256':snapshot.bhash(data['IndexBuffer']['Binary'])}
    if 'MatrixWeightsBuffer' in data:
        data['MatrixWeightsBuffer']['Binary']={'payload_sha256':snapshot.bhash(data['MatrixWeightsBuffer']['Binary'])}
    if 'Transform' in data:
        data['Transform']={('$MODEL' if k==name else k):v for k,v in data['Transform'].items()}
    for prim in data.get('Prim',[]):
        if 'Mesh' in prim:prim['Mesh']=prim['Mesh'].replace(name,'$MODEL')
        if 'Material' in prim:prim['Material']=snapshot.material(prim['Material'])['canonical_sha256']
    return data

def duv_tree(data,path=''):
    result={}
    if isinstance(data,dict):
        for key,value in data.items():
            p=path+'/'+key
            if key in ('Duv0','Duv1','Duv2','Duv7'):
                assert isinstance(value,list) and len(value)==2
                assert all(isinstance(x,(int,float)) and math.isfinite(x) and x>=0 for x in value)
                result[p]=list(value)
            else:result.update(duv_tree(value,p))
    elif isinstance(data,list):
        for i,value in enumerate(data):result.update(duv_tree(value,path+'/'+str(i)))
    return result

def without_duv(data):
    if isinstance(data,dict):
        return {k:without_duv(v) for k,v in data.items() if k not in ('Duv0','Duv1','Duv2','Duv7')}
    if isinstance(data,list):return [without_duv(v) for v in data]
    return data

def replace_path(data,path,value):
    keys=path.strip('/').split('/');node=data
    for key in keys[:-1]:node=node[int(key)] if isinstance(node,list) else node[key]
    key=keys[-1];node[int(key) if isinstance(node,list) else key]=copy.deepcopy(value)

def audit(before_path,after_path):
    baseline=read(ROOT/'validation/r13-protected-native-baseline.json')
    before_sha=file_sha(before_path);after_sha=file_sha(after_path)
    assert before_sha==baseline['iff_sha256'],'Published input must be the immutable R12.1 baseline'
    labels,manifest=original_labels()
    assert manifest['iff']['sha256']==before_sha,'Original label mapping must belong to original IFF'
    source_labels=read(ROOT/'validation/native-source-build.json')['models']
    new_names={}
    for row in source_labels:new_names.setdefault(row['source_object'],[]).append(row['model'])
    current=native_snapshot(after_path)['protected_models'];old=baseline['protected_models']
    assert set(current)==set(old)
    different=[n for n in old if old[n]!=current[n]]
    assert different,'Expected explicit float drift evidence, not a blanket tolerance'
    rows=[]
    with zipfile.ZipFile(before_path) as za,zipfile.ZipFile(after_path) as zb:
        sa=NativeSnapshot(za,{});sb=NativeSnapshot(zb,{})
        old_objects={o['Target']:o for o in sa.level['Object'].values() if o.get('Type')=='OBJECT'}
        new_objects={o['Target']:o for o in sb.level['Object'].values() if o.get('Type')=='OBJECT'}
        for label in different:
            # No nearest neighbour, geometry guess or ordering-based pairing.
            assert len(labels[label])==len(new_names[label])==len(old[label])==len(current[label])==1
            n0=labels[label][0];n1=new_names[label][0]
            oldrow=sa.model(n0,old_objects[n0]);newrow=sb.model(n1,new_objects[n1])
            assert oldrow==old[label][0],('Old model label does not reproduce baseline',label)
            assert newrow==current[label][0]
            for key in oldrow:
                if key not in ('canonical_sha256','model_contract_sha256'):
                    assert oldrow[key]==newrow[key],('Actual contract change',label,key)
            a,b=normalized(sa,n0),normalized(sb,n1)
            # Strong equality includes Min/Max/Center/Radius and every unknown
            # native Model field. Merely checking known stream fields is weaker.
            assert without_duv(a)==without_duv(b),('Difference outside Duv',label)
            av,bv=duv_tree(a),duv_tree(b);assert set(av)==set(bv)
            changes=[]
            for path in av:
                for i,(v,w) in enumerate(zip(av[path],bv[path])):
                    if v==w:continue
                    absolute=abs(v-w);relative=absolute/max(abs(v),abs(w),1e-12)
                    assert absolute<ABS_LIMIT and relative<REL_LIMIT,(label,path,v,w,absolute,relative)
                    changes.append({'path':path+'/'+str(i),'before':v,'after':w,
                                    'absolute_error':absolute,'relative_error':relative})
            assert changes
            restored=copy.deepcopy(b)
            for path,value in av.items():replace_path(restored,path,value)
            assert restored==a
            obj=copy.deepcopy(new_objects[n1]);obj['Target']='$MODEL'
            assert jhash(restored)==oldrow['model_contract_sha256']
            assert jhash({'model':restored,'object':obj})==oldrow['canonical_sha256']
            rows.append({'source_object':label,'old_model':n0,'new_model':n1,
                         'before':oldrow,'after':newrow,'exact_scalar_differences':changes,
                         'outside_duv_full_model_exactly_equal':True,
                         'restoring_only_duv_reproduces_old_canonical_hash':True,
                         'max_absolute_error':max(c['absolute_error'] for c in changes),
                         'max_relative_error':max(c['relative_error'] for c in changes)})
    result={'revision':'R13','status':'passed','baseline_iff_sha256':before_sha,'candidate_iff_sha256':after_sha,
            'input_paths':{'before':str(before_path),'after':str(after_path)},
            'scope':'Only listed Model/Prim Duv UV-density streaming hints; native geometry and material payloads remain exact',
            'source_of_fields':'iff_codec.texture_density derives a 75th percentile from unquantized float positions and UVs before native quantization.',
            'interpretation':'Differences are in derived UV streaming metadata below native vertex/UV encoding resolution. No source geometry or serialized vertex/index order differences are permitted.',
            'changed_object_count':len(rows),'protected_object_count':len(old),
            'absolute_error_limit':ABS_LIMIT,'relative_error_limit':REL_LIMIT,
            'max_absolute_error':max(r['max_absolute_error'] for r in rows),
            'max_relative_error':max(r['max_relative_error'] for r in rows),
            'proofs':rows,'iff_or_source_modified':False}
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--before',default=str(ROOT/'output/arena_700_int.iff'))
    ap.add_argument('--after',default=str(ROOT/'.build-staging/r13-native/arena_700_int.iff'))
    args=ap.parse_args();a=Path(args.before).resolve();b=Path(args.after).resolve()
    assert a.is_relative_to(ROOT) and b.is_relative_to(ROOT)
    result=audit(a,b);OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='proofs'}))

if __name__=='__main__':main()
