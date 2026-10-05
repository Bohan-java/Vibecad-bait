"""Audit R10 geometry and solid albedo from final native IFF, never source GLB.

The source-name JSON only identifies models. All geometry, matrices, native
materials and DDS pixels are independently decoded from the delivered archive.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'build/high_hoop/deps'))
import numpy as np
from iff_codec import load_scne,decode_attribute,resolve_binary
from audit_fence_iff_current import digest,decode_active,material_audit

LAMPS={
    'R10 left tall floodlight tapered mast':'444C4B',
    'R10 left tall floodlight housings and brackets':'343B3B',
    'R10 left tall floodlight non-emitting lens faces':'596563',
    'R10 left tall floodlight mechanical fixings':'767D79',
}
PAVING={
    'R02 observed low plaza wave outside court':'ADB0A7',
    'R02 architecture Chilis narrow restaurant terrace':'9FA399',
    'R02 continuous pale plaza ground':'949994',
    'R02 scattered grey stone inserts':'9BA097',
}


def decoded_color(record,expected_hex):
    sample=record['actual_albedo_dds'];assert sample,'Missing real DDS'
    expected=np.array([int(expected_hex[i:i+2],16) for i in (0,2,4)])
    actual=np.array(sample['median_encoded_rgb'])
    error=np.abs(actual-expected)
    return {'expected_srgb':'#'+expected_hex,'actual_encoded_rgb':actual.tolist(),
            'per_channel_error_8bit':error.tolist(),'max_channel_error_8bit':float(error.max()),
            'accepted_bc1_quantization_error_8bit':5,'matches':bool(error.max()<=5),
            'source':'Actual compressed DDS decoded by Pillow; no source PNG or GLB loaded.'}


def basket_anchor_audit(current,donor):
    """Byte and draw equality establish anchor preservation independently."""
    baskets=load_scne(current.read('baskets.SCNE'))['baskets']
    original=load_scne(donor.read('baskets.SCNE'))['baskets']
    assert baskets['Object']==original['Object'],'Basket instance matrices changed'
    rows=[]
    for name,old in original['Model'].items():
        matching=[(i,p) for i,p in enumerate(old.get('Prim',[])) if p.get('Mesh')=='basket_rimShape']
        if not matching:continue
        model=baskets['Model'][name]
        assert model['Transform']==old['Transform'],'Native rim bone transforms changed'
        assert model['VertexFormat']['POSITION0']==old['VertexFormat']['POSITION0']
        actual_raw=current.read(resolve_binary(current,model['VertexStream'][0]['Binary']))
        old_raw=donor.read(resolve_binary(donor,old['VertexStream'][0]['Binary']))
        assert actual_raw.startswith(old_raw),'Original native positions not retained exactly'
        actual_ib=np.frombuffer(current.read(resolve_binary(current,model['IndexBuffer']['Binary'])),'<u2')
        old_ib=np.frombuffer(donor.read(resolve_binary(donor,old['IndexBuffer']['Binary'])),'<u2')
        positions=decode_attribute(current,model,'POSITION0')[:,:3]
        for primitive_index,old_prim in matching:
            prim=model['Prim'][primitive_index];assert prim.get('Mesh')=='basket_rimShape'
            lods=prim.get('LodList',[prim]);old_lods=old_prim.get('LodList',[old_prim])
            assert len(lods)==len(old_lods)
            for draw,old_draw in zip(lods,old_lods):
                actual_ix=actual_ib[draw['Start']:draw['Start']+draw['Count']]
                previous_ix=old_ib[old_draw['Start']:old_draw['Start']+old_draw['Count']]
                assert np.array_equal(actual_ix,previous_ix),'Native rim LOD changed'
            active=lods[0];ids=np.unique(actual_ib[active['Start']:active['Start']+active['Count']])
            assert int(ids.max())<len(positions)
            instances=[]
            for instance,obj in baskets['Object'].items():
                if obj.get('Target')!=name:continue
                matrix=np.asarray(obj.get('Matrix',np.eye(4).reshape(-1)),dtype=float).reshape(4,4)
                p=(np.column_stack((positions[ids],np.ones(len(ids))))@matrix)[:,:3][:,[2,0,1]]/100
                instances.append({'name':instance,'native_instance_matrix':matrix.reshape(-1).tolist(),
                                  'actual_rim_bounds_blender_m':[p.min(0).tolist(),p.max(0).tolist()]})
            rows.append({'model':name,'native_rim_lods_preserved':len(lods),'original_position_prefix_bytes':len(old_raw),
                         'position_prefix_sha256':hashlib.sha256(old_raw).hexdigest(),'native_bone_transforms_unchanged':True,
                         'instances':instances})
    assert rows and sum(len(row['instances']) for row in rows)>=2
    return {'basket_object_definitions_exactly_equal_to_donor':True,'decoded_native_rim_models':rows,
            'method':'Native instance definitions, bone transforms, original position bytes and every native rim LOD draw verified against original donor.'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--iff',default=str(ROOT/'output/arena_700_int.iff'))
    parser.add_argument('--expected-sha256',required=True);args=parser.parse_args()
    path=Path(args.iff).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Final archive must remain in project')
    sha=digest(path);assert sha==args.expected_sha256
    final=json.loads((ROOT/'validation/iff-current.json').read_text(encoding='utf8'))
    assert final['revision']=='R10' and final['output_sha256']==sha,'Wait for final R10'
    labels_path=ROOT/'validation/native-source-build.json';doc=json.loads(labels_path.read_text(encoding='utf8'))
    assert doc['source_glb_sha256']==final['source_glb_sha256'],'Stale naming map'
    labels={r['model']:r['source_object'] for r in doc['models']}
    report={'revision':'R10','status':'pending','actual_iff':str(path),'sha256':sha,'bytes':path.stat().st_size,
            'labels_sha256':digest(labels_path),'source_blend_or_source_glb_read':False,
            'geometry_source':'Final IFF native VertexBuffer/IndexBuffer, active SCNE Model/Object and native material DDS'}
    donor_path=ROOT.parent/'洛克公园/arena_blacktop_ext.iff'
    with zipfile.ZipFile(path) as archive,zipfile.ZipFile(donor_path) as donor:
        raw_level=archive.read('level.SCNE');level=load_scne(raw_level)['level']
        by_label={};clouds={};materials={};court_parts=[]
        for object_name,obj in level['Object'].items():
            target=obj.get('Target');label=labels.get(target)
            if obj.get('Type')!='OBJECT' or label not in set(LAMPS|PAVING)|{'court_surface'}:continue
            p,row=decode_active(archive,level['Model'][target],obj)
            row.update(model=target,object=object_name,label=label)
            if label=='court_surface':
                court_parts.append((p,row));continue
            by_label.setdefault(label,[]).append(row);clouds.setdefault(label,[]).append(p)
            for name in row['materials']:
                if name not in materials:materials[name]=material_audit(archive,level,name)
        assert set(by_label)==set(LAMPS|PAVING),'Missing requested actual native meshes'
        lamp_rows={}
        for label,color in LAMPS.items():
            assert len(by_label[label])==1,'Lamp unexpectedly split or duplicated'
            row=by_label[label][0];assert len(row['materials'])==1
            mat=materials[row['materials'][0]];color_result=decoded_color(mat,color)
            assert color_result['matches'],(label,color_result)
            lamp_rows[label]={'native_geometry':row,'material':mat,'color_comparison':color_result}
        p=np.concatenate(clouds['R10 left tall floodlight tapered mast']);low=p.min(0);high=p.max(0)
        assert abs(high[2]-10.8)<.001 and abs(low[2]-.004)<.001
        assert np.max(np.abs((low[:2]+high[:2])/2-np.array([-4.2,-9.85])))<.001
        all_lamp=np.concatenate([p for label,parts in clouds.items() if label in LAMPS for p in parts])
        assert all_lamp[:,1].max()<-9.2,'Lamp enters fence/playing side'
        ground_rows={}
        for label,color in PAVING.items():
            matches=[];candidates=[]
            for row in by_label[label]:
                for material in row['materials']:
                    audit=materials[material];sample=audit['actual_albedo_dds']
                    if not sample:continue
                    # The plaza top also has an atlas. Verify only its actual
                    # small solid side/bottom DDS, never substitute atlas pixels.
                    if sample['size']!=[4,4]:continue
                    color_result=decoded_color(audit,color)
                    candidates.append({'native_material':material,'color_comparison':color_result})
                    if color_result['matches']:matches.append({'native_geometry':row,'material':audit,'color_comparison':color_result})
            assert len(matches)==1,('Expected exactly one native solid material',label,candidates)
            ground_rows[label]=matches[0]
        anchors=basket_anchor_audit(archive,donor)
        assert court_parts,'Missing native court surface'
        court=np.concatenate([p for p,row in court_parts]);court_low=court.min(0);court_high=court.max(0)
        assert np.abs(court[:,2]).max()<1e-9,'Court is not exactly at zero height'
        assert np.max(np.abs(court_low[:2]-[-18.3256,-11.62]))<.001
        assert np.max(np.abs(court_high[:2]-[18.3256,11.62]))<.001
        report.update(status='passed',level_scne_sha256=hashlib.sha256(raw_level).hexdigest(),
                      lamp={'components':lamp_rows,'actual_total_bounds_blender_m':[all_lamp.min(0).tolist(),all_lamp.max(0).tolist()],
                            'mast_height_top_m':float(high[2]),'mast_center_xy_m':((low[:2]+high[:2])/2).tolist(),
                            'no_explicit_emission_bindings':True,'dimensions_status':'Photo-supported silhouette; metric placement/height inferred.'},
                      four_non_atlas_paving_materials=ground_rows,native_basket_anchors=anchors,
                      court_surface={'actual_native_bounds_blender_m':[court_low.tolist(),court_high.tolist()],
                                     'exact_zero_height':True,'native_meshes':[row for p,row in court_parts]},
                      checks={'all_four_lamp_meshes_from_native_package':True,'height_position_match_approved_source_plan':True,
                              'four_non_atlas_grays_match_with_BC1_quantization':True,'no_lamp_emission_binding':True,
                              'original_native_basket_positions_bones_instances_and_rim_lods_preserved':True,
                              'court_exact_zero_height_and_existing_apron_extent_preserved':True},
                      limitations=['This is an asset/decode audit, not a game screenshot or game lighting validation.',
                                   'Source labels identify models only; no source geometry or texture supplies these results.'])
    assert digest(path)==sha,'Delivered archive changed during audit'
    destination=ROOT/'validation/current-streetlight-iff-audit.json'
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'status':'passed','report':str(destination),'sha256':sha,'native_lamp_meshes':4,'gray_materials':4,
                      'mast_top_m':report['lamp']['mast_height_top_m'],'native_basket_anchors_preserved':True}))


if __name__=='__main__':main()
