"""Read-only final-IFF fence audit; source labels are names, never geometry.

All positions, indices, matrices, material bindings and DDS samples below are
read from the delivered ZIP/IFF. No Blender source or source GLB is loaded.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'build/high_hoop/deps'))
import numpy as np
from PIL import Image
from iff_codec import load_scne,decode_attribute,resolve_binary

OLD_PREFIXES=('R02 fence A badge ','R02 A badge outline ','R02 fence A glyph ')
COMPONENTS=('R09 A capsule enclosure.','R09 A recessed channel -1.','R09 A recessed channel 1.',
            'R09 A unlit diffuser -1.','R09 A unlit diffuser 1.','R09 A inner letter channel.',
            'R09 A inner white diffuser.','R09 A stand-off brackets.')


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def decode_active(archive,model,obj):
    positions=decode_attribute(archive,model,'POSITION0')[:,:3]
    matrix=np.asarray(obj.get('Matrix',np.eye(4).reshape(-1)),dtype=float).reshape(4,4)
    positions=(np.column_stack((positions,np.ones(len(positions))))@matrix)[:,:3]
    # Actual native world game XYZ centimetres -> Blender XYZ metres.
    positions=positions[:,[2,0,1]]/100.
    raw=archive.read(resolve_binary(archive,model['IndexBuffer']['Binary']))
    dtype={'R16_UINT':'<u2','R32_UINT':'<u4'}[model['IndexBuffer']['Format']]
    all_indices=np.frombuffer(raw,dtype);active=[];materials=set();triangles=0
    inherited={}
    for primitive in model['Prim']:
        inherited.update({k:v for k,v in primitive.items() if k in ('Type','Material')})
        assert inherited['Type']=='TRIANGLE_LIST'
        draw=(primitive.get('LodList') or [primitive])[0]
        indices=all_indices[draw['Start']:draw['Start']+draw['Count']].reshape(-1,3)
        assert len(indices) and int(indices.max())<len(positions)
        good=indices[(indices[:,0]!=indices[:,1])&(indices[:,1]!=indices[:,2])&(indices[:,0]!=indices[:,2])]
        if len(good):
            active.extend(good.reshape(-1));triangles+=len(good);materials.add(inherited['Material'])
    assert active,'No actual visible triangles'
    p=positions[np.unique(active)]
    assert np.isfinite(p).all()
    if 'IndexBufferCrc32' in model:assert zlib.crc32(raw)==model['IndexBufferCrc32']
    return p,{'vertices':len(p),'triangles':triangles,'materials':sorted(materials),
              'bounds_blender_m':[p.min(0).tolist(),p.max(0).tolist()],
              'index_buffer_sha256':hashlib.sha256(raw).hexdigest(),
              'vertex_buffers':[{'binary':s['Binary'],'sha256':hashlib.sha256(archive.read(resolve_binary(archive,s['Binary']))).hexdigest()} for s in model['VertexStream']],
              'matrix':matrix.reshape(-1).tolist()}


def emission_fields(value,path=''):
    found={}
    if isinstance(value,dict):
        for key,item in value.items():
            name=path+'.'+key if path else key
            if re.search(r'emiss|self.?illum|glow',key,re.I):found[name]=item
            else:found.update(emission_fields(item,name))
    elif isinstance(value,list):
        for i,item in enumerate(value):found.update(emission_fields(item,path+f'[{i}]'))
    return found


def material_audit(archive,level,name):
    material=level['Material'][name];effect=level['Effect'][material['Effect']]
    emission=emission_fields(material)
    # An explicit nonzero or resource binding would invalidate the unlit brief.
    # Numeric offsets in Effect schemas are not material parameter values.
    assert not emission,('Unexpected material emissive contract',name,emission)
    assert material['Effect'].startswith('asset_CLOD.fx#'),material['Effect']
    resources=material.get('Resource',{})
    albedo=resources.get('AlbedoMap') or resources.get('AlbedoMapBC3')
    sample=None
    if albedo:
        texture=level['Texture'][albedo['Pixelmap']]
        binary=str(PurePosixPath(texture['Binary']).with_suffix('.dds'))
        raw=archive.read(binary);image=Image.open(io.BytesIO(raw));image.load()
        pixels=np.asarray(image.convert('RGB')).reshape(-1,3)
        sample={'pixelmap':albedo['Pixelmap'],'dds':binary,'sha256':hashlib.sha256(raw).hexdigest(),
                'size':list(image.size),'median_encoded_rgb':np.median(pixels,axis=0).tolist()}
    return {'effect':material['Effect'],'native_dynamic_asset_techniques':[k for k in effect['Technique'] if k in ('AssetHires','AssetLores')],
            'explicit_emission_fields':emission,'no_emission_binding':not emission,
            'alpha_style':material.get('Parameter',{}).get('AlphaStyle'),'actual_albedo_dds':sample}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--iff',default=str(ROOT/'output/arena_700_int.iff'))
    parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--expected-revision',choices=('R09','R10'),default='R10');args=parser.parse_args()
    path=Path(args.iff).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('IFF must remain in project')
    sha=digest(path);assert sha==args.expected_sha256,'Final IFF hash mismatch'
    final=json.loads((ROOT/'validation/iff-current.json').read_text(encoding='utf8'))
    assert final['revision']==args.expected_revision and final['output_sha256']==sha,'Refuse old or unmatched delivery metadata'
    label_path=ROOT/'validation/native-source-build.json';labels_doc=json.loads(label_path.read_text(encoding='utf8'))
    assert labels_doc['source_glb_sha256']==final['source_glb_sha256'],'Stale source-name mapping'
    labels={r['model']:r for r in labels_doc['models']}
    report={'status':'pending','actual_iff':str(path),'revision':final['revision'],'bytes':path.stat().st_size,'sha256':sha,
            'geometry_origin':'Actual final IFF level.SCNE, indexed VertexBuffer/IndexBuffer payloads and Object matrices',
            'label_mapping':str(label_path),'label_mapping_sha256':digest(label_path),
            'source_blend_or_source_glb_read':False,'scope':'Active fence assets only; independent of moved basket rig labels.',
            'orientation':'Chili’s up = source -X; left = -Y; right = +Y'}
    with zipfile.ZipFile(path) as archive:
        level=load_scne(archive.read('level.SCNE'))['level']
        report['level_scne_sha256']=hashlib.sha256(archive.read('level.SCNE')).hexdigest()
        rows=[];by_label={};decoded={};unknown=[];active_labels=[]
        for object_name,obj in level['Object'].items():
            target=obj.get('Target')
            if obj.get('Type')!='OBJECT' or target not in level['Model']:continue
            label=labels.get(target,{}).get('source_object',target);active_labels.append(label)
            if target.startswith('zgc_r03:') and target not in labels:unknown.append(target)
            tags=labels.get(target,{}).get('tags',[])
            if 'fence' not in tags and not label.startswith(('North partial fence','South partial fence','R09 A ')):continue
            positions,record=decode_active(archive,level['Model'][target],obj)
            record.update(model=target,object=object_name,label=label)
            rows.append(record);by_label.setdefault(label,[]).append(record);decoded.setdefault(label,[]).append(positions)
        assert not unknown,('Unlabelled active custom models could conceal stale assets',unknown)
        old=[x for x in active_labels if x.startswith(OLD_PREFIXES)]
        assert not old,old
        runs={}
        for side,prefix,expected_end in (('left','South',-2.8),('right','North',-4.8)):
            clouds=[p for label,parts in decoded.items() if label.startswith(prefix+' partial fence post ') for p in parts]
            assert len(clouds)==(7 if side=='left' else 6)
            p=np.concatenate(clouds);low=p.min(0);high=p.max(0)
            start=float(low[0]+.0375);end=float(high[0]-.0375);length=end-start
            assert abs(start+16.08)<.0002 and abs(end-expected_end)<.0002
            assert abs((low[1]+high[1])/2-(-9.17 if side=='left' else 9.17))<.0002
            runs[side]={'post_count':len(clouds),'start_x_m':start,'end_x_m':end,'run_length_m':length,'y_m':float((low[1]+high[1])/2),
                        'actual_vertex_bounds_m':[low.tolist(),high.tolist()],'absolute_layout_dimensions':'Inferred source reconstruction, not field measured'}
        assert runs['left']['run_length_m']>runs['right']['run_length_m']
        signs={};material_names=set()
        for side in ('left','right'):
            expected=[prefix+side for prefix in COMPONENTS]
            assert all(label in by_label for label in expected),expected
            p=np.concatenate(decoded['R09 A capsule enclosure.'+side]);size=p.max(0)-p.min(0)
            ratio=float(size[2]/size[0]);assert abs(size[0]-.565)<.0002 and abs(size[2]-1.17)<.0002 and abs(ratio-1.17/.565)<.001
            signs[side]={'component_labels':expected,'components_present':len(expected),'enclosure_width_m':float(size[0]),
                         'enclosure_height_m':float(size[2]),'height_width_ratio':ratio,
                         'component_bounds_m':{label:[np.concatenate(decoded[label]).min(0).tolist(),np.concatenate(decoded[label]).max(0).tolist()] for label in expected}}
            for label in expected:
                for row in by_label[label]:material_names.update(row['materials'])
        materials={name:material_audit(archive,level,name) for name in sorted(material_names)}
        report.update(status='passed',fence_runs=runs,large_A_signs=signs,native_sign_materials=materials,
                      old_sign_active_models=old,unknown_active_custom_models=unknown,
                      checked_native_fence_models=rows,checks={'actual_final_iff_hash_matches':True,'labels_match_final_source_build':True,
                      'left_longer_than_right':True,'all_16_new_large_A_components_present':True,'sign_enclosure_ratio_matches':True,
                      'no_old_large_A_models_active':True,'no_explicit_emission_parameters_or_resources':True,
                      'geometry_and_materials_read_from_final_iff_only':True},
                      limitations=['Material/schema evidence confirms no emissive binding; this is not a game lighting test.',
                                   'Source-name JSON is used solely to identify decoded native models; no source mesh or source GLB geometry was loaded.'])
    # Detect replacement of the delivered archive while this audit was running.
    assert digest(path)==sha,'Delivered IFF changed during audit'
    output=ROOT/'validation/current-fence-iff-audit.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'status':'passed','report':str(output),'sha256':sha,'fence_native_models':len(report['checked_native_fence_models']),
                      'left_length_m':report['fence_runs']['left']['run_length_m'],'right_length_m':report['fence_runs']['right']['run_length_m'],
                      'new_large_A_components':16,'old_active_large_A_models':0,'sign_materials':len(report['native_sign_materials'])}))


if __name__=='__main__':main()
