"""Evidence-led audit and factory for R04 native dynamic glass compatibility.

This module never modifies an IFF, source blend, or game installation itself.
The root builder may call a verified factory after inspecting its audit report.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import zipfile
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from iff_codec import load_scne,dump_scne,resolve_binary,decode_attribute
DONOR=ROOT.parent/'洛克公园'/'arena_blacktop_ext.iff'
CUSTOM_GLASS_MATERIALS={'zgc_r03:material_031','zgc_r03:material_100'}
CUSTOM_GLASS_MODELS={'zgc_r03:part-0038','zgc_r03:part-0294','zgc_r03:part-0420'}
CUSTOM_GLASS_SOURCE_OBJECTS={'R02 architecture Chilis terrace side-walk glass guard',
                           'Backboard.open','Backboard.reference'}


def repair_glass(level,original_donor_level,current_zip,donor_zip,extra_dict,source_models=None,omitted_source_objects=()):
    """Use the demonstrated native basket-glass binding, without new weights.

    Remove only the explicitly named custom transparent models/instances. The
    R11 caller may document removal of the old terrace sheet in the source;
    both backboard placeholders remain mandatory. Restore only
    the original glass model's index-buffer descriptor/CRC and its original bin
    payload; preserve native skeleton, instances and all other basket draw
    ranges. R10 replaces the complete glass rendering contract with the native
    dedicated basket_glass pipeline, including its Presentation shaders.
    Guard-rail framing stays; its transparent panel is omitted.
    Caller owns writing a candidate IFF and recording this visible limitation.
    """
    del original_donor_level  # No alternate or opaque template is needed here.
    glass_materials={n for n,m in level['Material'].items()
                     if n.startswith('zgc_r03:') and m.get('Parameter',{}).get('AlphaStyle')=='TRANSLUCENT'}
    expected_materials=CUSTOM_GLASS_MATERIALS
    expected_models=CUSTOM_GLASS_MODELS
    omitted=set(omitted_source_objects)
    guard='R02 architecture Chilis terrace side-walk glass guard'
    if not omitted.issubset({guard}) or (omitted and source_models is None):
        raise ValueError('Only a documented source removal of the terrace sheet is allowed')
    if source_models is not None:
        rows=source_models.get('models',[]) if isinstance(source_models,dict) else source_models
        selected=[r for r in rows if r.get('source_object') in CUSTOM_GLASS_SOURCE_OBJECTS]
        expected_sources=CUSTOM_GLASS_SOURCE_OBJECTS-omitted
        if len(selected)!=len(expected_sources) or {r['source_object'] for r in selected}!=expected_sources:
            raise ValueError('Unexpected named glass sources; both backboards are mandatory')
        expected_models={r['model'] for r in selected}
        expected_materials={r['material'] for r in selected}
        if len(expected_materials)!=(1 if omitted else 2):raise ValueError('Unexpected named glass material sharing')
    if glass_materials!=expected_materials:
        raise ValueError('Unexpected custom translucent material set: '+str(glass_materials))
    removal=[]
    for name,model in level['Model'].items():
        prims=model.get('Prim',[])
        glass=[p.get('Material') in glass_materials for p in prims]
        if not any(glass):continue
        if not all(glass):raise ValueError('Refuse removal of mixed opaque/glass mesh '+name)
        removal.append(name)
    if set(removal)!=expected_models:
        raise ValueError('Unexpected custom glass model set: '+str(removal))

    original_doc=load_scne(donor_zip.read('baskets.SCNE'));original=original_doc['baskets']
    current_doc=load_scne(extra_dict.get('baskets.SCNE') or current_zip.read('baskets.SCNE'))
    current=current_doc['baskets']
    if current['Object']!=original['Object']:
        raise ValueError('Basket instances changed; native glass restore requires review')
    original_names=[n for n in original['Model'] if n.endswith(':glass')]
    if len(original_names)!=1:raise ValueError('Expected one original instanced glass model')
    name=original_names[0];model=original['Model'][name];before=current['Model'][name]
    native_model=model
    for key in set(model)|set(before):
        if key in ('IndexBuffer','IndexBufferCrc32'):continue
        if before.get(key)!=model.get(key):raise ValueError('Basket glass changed outside index data: '+key)
    weight=model['VertexFormat']['WEIGHTDATA0'];stream=model['VertexStream'][weight['Stream']]
    raw=donor_zip.read(resolve_binary(donor_zip,stream['Binary']))
    values=np.ndarray((len(raw)//stream['Stride'],),'<u4',raw,
                      offset=weight['ByteOffset'],strides=(stream['Stride'],))
    if weight['Format']!='R32_UINT' or not np.all(values==0x100):
        raise ValueError('Native glass binding differs from audited constant')
    for prim in model['Prim']:
        material=original['Material'][prim['Material']]
        effect=original['Effect'][material['Effect']]
        if not all(t in effect['Technique'] for t in ('AssetHires','AssetLores')):
            raise ValueError('Native glass shader lacks dynamic techniques')
    original_binary=resolve_binary(donor_zip,model['IndexBuffer']['Binary'])
    payload=donor_zip.read(original_binary)
    current_binary=resolve_binary(current_zip,before['IndexBuffer']['Binary'])
    hidden_payload=current_zip.read(current_binary)
    if len(hidden_payload)!=len(payload):raise ValueError('Original glass index length changed')
    current['Model'][name]['IndexBuffer']=copy.deepcopy(model['IndexBuffer'])
    if 'IndexBufferCrc32' in model:
        current['Model'][name]['IndexBufferCrc32']=model['IndexBufferCrc32']
    else:current['Model'][name].pop('IndexBufferCrc32',None)
    extra_dict[original_binary]=payload
    if current['Model'][name]!=model:raise AssertionError('Native glass model not restored exactly')
    changed_basket_models=[n for n in current['Model'] if current['Model'][n]!=load_scne(current_zip.read('baskets.SCNE'))['baskets']['Model'][n]]
    if changed_basket_models not in ([name],[]):raise AssertionError('Unexpected basket model changes')
    positions=decode_attribute(donor_zip,model,'POSITION0')[:,:3]
    indices=np.frombuffer(payload,'<u2')
    visible=[]
    for prim in model['Prim']:
        draw=prim['LodList'][0]
        visible.extend(indices[draw['Start']:draw['Start']+draw['Count']])
    p=positions[np.unique(visible)]

    # R09 restored the general asset-glass contract but replay remained black.
    # The native Blacktop glass has a separate whole basket_glass pipeline with
    # Presentation and alpha-discard depth passes. Keep geometry/pose unchanged
    # and import that full contract, never isolated guessed render-state edits.
    from specialized_basket_glass import apply_specialized_glass
    specialized=apply_specialized_glass(current,extra_dict)
    glass_material_changes=specialized['material_changes']
    texture_changes=specialized['textures']
    extra_dict['baskets.SCNE']=dump_scne(current_doc)

    removed_objects=[];removed_models=[]
    for name in removal:
        model=level['Model'].pop(name)
        removed_models.append({'model':name,'materials':[p['Material'] for p in model['Prim']],
                               'index_buffer_unchanged':model['IndexBuffer']['Binary'],
                               'vertex_buffers_unchanged':[s['Binary'] for s in model['VertexStream']]})
    for name,obj in list(level['Object'].items()):
        if obj.get('Target') in removal:
            del level['Object'][name];removed_objects.append(name)
    if len(removed_objects)!=len(removal):raise AssertionError('Unexpected transparent instance count')
    # Unused custom material definitions and binary data remain inert; no opaque
    # material, vertex, index, UV, rim, net or runtime marker has been rewritten.
    return {'game_verified':False,'strategy':'complete native outdoor basket_glass pipeline with Presentation; neutral alpha-bearing albedo and roughness avoid duplicate painted frames',
            'new_skinning_weight_factory':False,
            'reason':'No demonstrated single-root static dynamic-glass binding in available native level. Constant basket weight belongs to an existing four-node runtime skeleton.',
            'removed_static_model_count':len(removed_models),'removed_models':removed_models,
            'removed_objects':removed_objects,'documented_source_omissions':sorted(omitted),
            'guard_glass':('R11 source replaced the old terrace sheet and guardrail with photo-guided wide framed viewing openings' if omitted else 'transparent sheet omitted; opaque guardrail framing retained'),
            'native_glass':{'model':original_names[0],'restored_model_exactly_matches_donor':True,
                            'restored_original_binary':original_binary,'index_payload_sha256':hashlib.sha256(payload).hexdigest(),
                            'index_count':len(indices),'changed_from_degenerate_indices':int(np.count_nonzero(np.frombuffer(hidden_payload,'<u2')!=indices)),
                            'weight_value_copied_without_reencoding':'0x00000100','weight_vertex_count':len(values),
                            'transform_count':len(native_model.get('Transform',{})),
                            'local_visible_bounds_game_cm':{'min':p.min(0).tolist(),'max':p.max(0).tolist()},
                            'instances_and_binding_unchanged':True,'glass_materials_changed':True,
                            'unused_original_texture_bytes_unchanged':True},
            'geometry_payloads_modified':False,'new_extra_payloads':list(extra_dict),
            'glass_material_changes':glass_material_changes,
            'glass_texture_changes':texture_changes,
            'dedicated_glass_pipeline':specialized,
            'limitations':['Dedicated basket_glass replay response still needs in-game confirmation; geometry and bone binding remain exact donor data.',
                           'Terrace transparent guard sheet omitted in this compatibility candidate.',
                           'No in-game rendering or global-lighting result established.']}


def audit(path=DONOR):
    result={'input':str(path),'scenes':{},'game_verified':False}
    with zipfile.ZipFile(path) as archive:
        for filename in ('level.SCNE','baskets.SCNE'):
            document=load_scne(archive.read(filename))
            level=next(iter(document.values()))
            glass={n:m for n,m in level.get('Material',{}).items()
                   if 'glass' in n.lower() or m.get('Parameter',{}).get('AlphaStyle')=='TRANSLUCENT'}
            effects={m['Effect']:level.get('Effect',{}).get(m['Effect']) for m in glass.values()}
            models={n:m for n,m in level.get('Model',{}).items()
                    if any(p.get('Material') in glass for p in m.get('Prim',[]))}
            observations=[]
            for name,model in models.items():
                weight=model['VertexFormat'].get('WEIGHTDATA0')
                ob={'model':name,'vertex_format':model['VertexFormat'],'vertex_streams':model['VertexStream'],
                    'transform':model.get('Transform'),'blend_index_offset':model.get('BlendIndexOffset'),
                    'blend_index_range':model.get('BlendIndexRange'),
                    'primitives':[{k:v for k,v in p.items() if k in ('Material','Mesh','Type','Start','Count','BlendIndexRange','LodList')} for p in model.get('Prim',[])],
                    'instances':{n:o for n,o in level.get('Object',{}).items() if o.get('Target')==name}}
                if weight:
                    stream=model['VertexStream'][weight.get('Stream',0)]
                    raw=archive.read(resolve_binary(archive,stream['Binary']))
                    count=len(raw)//stream['Stride'];offset=weight.get('ByteOffset',0)
                    words=[raw[i*stream['Stride']+offset:i*stream['Stride']+offset+4].hex() for i in range(count)]
                    counts={}
                    for word in words:counts[word]=counts.get(word,0)+1
                    ob['weight_bytes']={'format':weight['Format'],'vertex_count':count,'unique_4byte_values':counts,
                                        'stream_sha256':hashlib.sha256(raw).hexdigest()}
                observations.append(ob)
            result['scenes'][filename]={'materials':glass,'effects':effects,'models':observations}
            weighted=[]
            for name,model in level.get('Model',{}).items():
                weight=model.get('VertexFormat',{}).get('WEIGHTDATA0')
                if not weight:continue
                stream=model['VertexStream'][weight.get('Stream',0)]
                raw=archive.read(resolve_binary(archive,stream['Binary']))
                values=np.ndarray((len(raw)//stream['Stride'],),'<u4',raw,
                                  offset=weight.get('ByteOffset',0),strides=(stream['Stride'],))
                unique,counts=np.unique(values,return_counts=True)
                weighted.append({'model':name,'transform_count':len(model.get('Transform',{})),
                                 'blend_range':model.get('BlendIndexRange'),'blend_offset':model.get('BlendIndexOffset'),
                                 'weight_unique_count':len(unique),
                                 'weight_values':{hex(int(v)):int(c) for v,c in zip(unique[:16],counts[:16])},
                                 'transform':model.get('Transform') if len(model.get('Transform',{}))<=2 else None})
            result['scenes'][filename]['all_weighted_models_summary']=weighted
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--donor',default=str(DONOR))
    parser.add_argument('--check-package')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    path=Path(args.donor).resolve()
    if not path.is_relative_to(ROOT.parent):raise ValueError('Input must remain in permitted workspace')
    report=audit(path)
    output=ROOT/'validation'/'r04-glass-native-audit.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    if args.check_package:
        current_path=Path(args.check_package).resolve()
        if not current_path.is_relative_to(ROOT):raise ValueError('Package must stay inside project')
        with zipfile.ZipFile(path) as donor,zipfile.ZipFile(current_path) as current:
            level=load_scne(current.read('level.SCNE'))['level']
            original=load_scne(donor.read('level.SCNE'))['level']
            extra={};repair_report=repair_glass(level,original,current,donor,extra)
            repair_report['dry_run_only']=True
            repair_report['package_unchanged']=str(current_path)
            (ROOT/'validation'/'r04-glass-repair-dry-run.json').write_text(json.dumps(repair_report,ensure_ascii=False,indent=2),encoding='utf8')
            print('R04_GLASS_REPAIR_DRY_RUN '+json.dumps({k:repair_report[k] for k in ('strategy','removed_static_model_count','removed_objects','geometry_payloads_modified')}))
    print('R04_GLASS_AUDIT '+str(output))
    for filename,scene in report['scenes'].items():
        print('ALL WEIGHTED',filename,len(scene['all_weighted_models_summary']))
        for model in scene['all_weighted_models_summary']:
            if model['transform_count']<=2 or model['weight_unique_count']==1:
                print('CANDIDATE',json.dumps(model))
        for model in scene['models']:
            if 'weight_bytes' in model:
                print(filename,model['model'],model['blend_index_offset'],model['blend_index_range'],
                      model['weight_bytes']['format'],len(model['weight_bytes']['unique_4byte_values']),
                      list(model['weight_bytes']['unique_4byte_values'].items())[:12])


if __name__=='__main__':main()
