#!/usr/bin/env python3
"""Offline tests: real supplied buffer + synthetic complete-scene/archive fixtures.
No test result is evidence of NBA 2K26 runtime behavior.
Usage: python -S test_diagnostic.py --bundle /path/to/realtime_light_research.zip
"""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
from rtl_common import Bundle, GRID_KEY, GRID_MEMBER, JsonSource, load_scne, sha256
from analyze_bundle import inspect_grid
from generate_diagnostic import (EXPECTED_GRID_SHA256, LIGHT_NAME, NEW_MEMBER, prepare_payload,
                                 load_extra, read_source_iff, verify_packed, workspace_path, write_payload)

BUNDLE = None


class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with Bundle(BUNDLE) as b:
            cls.ours=b.json('ours/level_light_subset.json')
            cls.official=b.json('donors/arena_020_int/level_light_subset.json')
            cls.grid=b.read('ours/'+GRID_MEMBER)
        cls.doc={'level':{
            'Light':copy.deepcopy(cls.ours['Light']),
            'Effect':{'unchanged_effect':{'ResourceMapping':'opaque\\u1234'}},
            'Texture':copy.deepcopy(cls.ours['Texture_LIGHT']),
            'Material':{'unchanged_material':{'color':[.13,.27,.39,1.]}},
            'Model':{'unchanged_model':{'sample':'synthetic, not game geometry'}},
            'Object':copy.deepcopy(cls.ours['Object_LIGHT_markers']),
            'Attribute':{'Unicode':'保留源文本，不重排'},
        }}
        cls.raw=(json.dumps(cls.doc,ensure_ascii=True,indent='\t')[1:-1]+'\n').encode('utf8')

    def prepare(self, experiment='append', raw=None, **kw):
        return prepare_payload(raw or self.raw,self.grid,self.ours,self.official,
                               experiment=experiment,**kw)

    def synthetic_archive(self,path,raw=None,overrides=None):
        members={'level.SCNE':raw or self.raw,GRID_MEMBER:self.grid,
                 'PostEffect.FxTweakables':b'opaque-postfx\x00\xff',
                 'probe_payload.bin':b'opaque-probe-bytes\x00\xfe',
                 'other_unknown_member.xyz':b'keep-me'}
        members.update(overrides or {})
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for k,v in members.items():z.writestr(k,v)

    def test_01_real_grid_fingerprint(self):
        self.assertEqual(sha256(self.grid),EXPECTED_GRID_SHA256)
        self.assertEqual(len(self.grid),9_643_472)

    def test_02_real_grid_structural_analysis(self):
        result,rows=inspect_grid(self.grid,self.ours)
        self.assertEqual(len(rows),840)
        self.assertTrue(result['reassembly_byte_identical'])
        self.assertEqual(result['candidate_mask_words'],[1])
        self.assertEqual(result['candidate_aux_words'],[1])
        self.assertEqual(result['trailer_uint16'],[0,4,0,0])
        self.assertEqual(result['conditional_bit_positions'],[0])
        self.assertTrue(result['both_address_models_fit_this_sample'])
        self.assertEqual(result['world_coordinate_inference']['center_coarse_cell'],[105,7,74])
        self.assertTrue(result['world_coordinate_inference']['matches_probe_grid_origin'])
        self.assertEqual(sum(x['fills_bounding_box'] for x in result['axis_order_candidates']),1)

    def test_03_truncated_grid_rejected(self):
        with self.assertRaises(ValueError):inspect_grid(self.grid[:-4],self.ours)

    def test_04_out_of_bounds_candidate_address_detected(self):
        broken=bytearray(self.grid);struct.pack_into('<I',broken,264,0xffffffff)
        result,_=inspect_grid(bytes(broken),self.ours)
        self.assertFalse(result['both_address_models_fit_this_sample'])

    def test_05_append_exact_scope(self):
        files,m=self.prepare()
        doc=load_scne(files['replacements/level.SCNE'])
        self.assertEqual(list(doc['level']['Light']),['Sun',LIGHT_NAME])
        self.assertEqual(doc['level']['Light']['Sun'],self.doc['level']['Light']['Sun'])
        self.assertEqual(list(files),['replacements/level.SCNE'])
        self.assertEqual(m['add'],[])
        self.assertEqual(doc['level']['Texture'],self.doc['level']['Texture'])

    def test_06_original_sun_source_text_preserved(self):
        original=JsonSource(self.raw);start,end=original.span(('level','Light','Sun'))
        for mode in ('append','alias','word64-2','prepend','movable'):
            files,_=self.prepare(mode,ack_unverified=True)
            modified=JsonSource(files['replacements/level.SCNE'])
            a,b=modified.span(('level','Light','Sun'))
            self.assertEqual(original.text[start:end],modified.text[a:b],mode)

    def test_07_original_protected_sections_source_preserved(self):
        original=JsonSource(self.raw)
        files,_=self.prepare('word64-2',ack_unverified=True)
        modified=JsonSource(files['replacements/level.SCNE'])
        for key in ('Object','Material','Model','Effect','Attribute'):
            a,b=original.span(('level',key));c,d=modified.span(('level',key))
            self.assertEqual(original.text[a:b],modified.text[c:d],key)

    def test_08_prepend_zero_grid_change(self):
        files,m=self.prepare('prepend')
        self.assertEqual(m['light_order_after'],[LIGHT_NAME,'Sun'])
        self.assertEqual(len(files),1);self.assertIsNone(m['word_change'])

    def test_09_word64_needs_explicit_ack(self):
        with self.assertRaises(ValueError):self.prepare('word64-2')

    def test_10_alias_control_identical_scene_one_byte_grid_difference(self):
        a,ma=self.prepare('alias');b,mb=self.prepare('word64-2',ack_unverified=True)
        self.assertEqual(a['replacements/level.SCNE'],b['replacements/level.SCNE'])
        self.assertEqual(a['members/0000.bin'],self.grid)
        differences=[i for i,(x,y) in enumerate(zip(a['members/0000.bin'],b['members/0000.bin'])) if x!=y]
        self.assertEqual(differences,[256])
        self.assertEqual(ma['add'][0]['archive_name'],mb['add'][0]['archive_name'])
        self.assertEqual(ma['add'][0]['archive_name'],NEW_MEMBER)

    def test_11_movable_is_only_light_value_difference(self):
        a,ma=self.prepare('append');b,mb=self.prepare('movable')
        expected=copy.deepcopy(ma['new_light']);expected['Attribute']['VC_IsMovable']=1
        self.assertEqual(mb['new_light'],expected)
        self.assertEqual(ma['add'],mb['add'])

    def test_12_shadow_off_control(self):
        _,a=self.prepare();_,b=self.prepare(casts_shadows=0)
        expected=copy.deepcopy(a['new_light']);expected['Attribute']['VC_CastsShadows']=0
        self.assertEqual(b['new_light'],expected)

    def test_13_intensity_zero_control(self):
        _,m=self.prepare(intensity=0)
        self.assertEqual(m['new_light']['Intensity'],0.)

    def test_14_unsupported_grid_fingerprint_rejected(self):
        bad=bytearray(self.grid);bad[300]^=1
        with self.assertRaises(ValueError):prepare_payload(self.raw,bytes(bad),self.ours,self.official)

    def test_15_subset_cannot_be_used_as_level_scene(self):
        raw=json.dumps(self.ours).encode()
        with self.assertRaises(ValueError):self.prepare(raw=raw)

    def test_16_relighting_change_rejected(self):
        doc=copy.deepcopy(self.doc);doc['level']['Object']['LIGHT_PROBE_GRID_DATA']['Attribute']['USE_RELIGHTING']=1
        with self.assertRaises(ValueError):self.prepare(raw=json.dumps(doc).encode())

    def test_17_existing_diagnostic_rejected(self):
        files,_=self.prepare()
        with self.assertRaises(ValueError):self.prepare(raw=files['replacements/level.SCNE'])

    def test_18_duplicate_json_rejected(self):
        with self.assertRaises(ValueError):load_scne(b'"level":{"Light":{},"Light":{}}')

    def test_19_nonfinite_parameter_rejected(self):
        with self.assertRaises(ValueError):self.prepare(intensity=float('nan'))

    def test_20_json_bom_fragment_and_full_noop(self):
        for raw in (self.raw,b'\xef\xbb\xbf'+self.raw,json.dumps(self.doc,ensure_ascii=False).encode('utf8')):
            self.assertEqual(JsonSource(raw).patch([]),raw)
            files,m=self.prepare(raw=raw)
            self.assertEqual(load_scne(files['replacements/level.SCNE'])['level']['Object'],self.doc['level']['Object'])
            self.assertEqual(files['replacements/level.SCNE'].startswith(b'\xef\xbb\xbf'),raw.startswith(b'\xef\xbb\xbf'))

    def test_21_workspace_escape_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'work';root.mkdir()
            with self.assertRaises(ValueError):workspace_path(root,root/'../outside',False)

    def test_22_game_like_path_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.assertRaises(ValueError):workspace_path(root,'steamapps/common/NBA 2K26/arena_700_int.iff',False)

    def test_23_payload_output_refuses_overwrite(self):
        files,m=self.prepare()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'payload';write_payload(path,files,m)
            with self.assertRaises(ValueError):write_payload(path,files,m)

    def test_24_payload_bridge_and_verifier_synthetic_archives(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);base=root/'synthetic_base.zip';self.synthetic_archive(base)
            old_bytes=base.read_bytes();raw,grid,src=read_source_iff(base)
            files,m=prepare_payload(raw,grid,self.ours,self.official,experiment='word64-2',ack_unverified=True)
            m['source']=src;payload=root/'payload';write_payload(payload,files,m)
            with zipfile.ZipFile(base,'r') as original:
                extra=load_extra(payload,original)
                members={name:original.read(name) for name in original.namelist()}
            self.assertEqual(base.read_bytes(),old_bytes)
            members.update(extra);final=root/'synthetic_final.zip'
            with zipfile.ZipFile(final,'w',compression=zipfile.ZIP_DEFLATED) as z:
                for name,data in members.items():z.writestr(name,data)
            self.assertTrue(verify_packed(final,payload)['PostEffect_and_original_member_inventory_covered'])
            # A postfx corruption must be rejected.
            members['PostEffect.FxTweakables']=b'forbidden'
            bad=root/'synthetic_bad.zip'
            with zipfile.ZipFile(bad,'w') as z:
                for name,data in members.items():z.writestr(name,data)
            with self.assertRaises(ValueError):verify_packed(bad,payload)

    def test_25_wrong_packaging_base_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);base=root/'synthetic_base.zip'
            self.synthetic_archive(base,raw=self.raw+b' ')
            files,m=self.prepare();write_payload(root/'payload',files,m)
            with zipfile.ZipFile(base) as z:
                with self.assertRaises(ValueError):load_extra(root/'payload',z)

    def test_26_no_extra_object_locator_or_probe_mutation(self):
        files,m=self.prepare();after=load_scne(files['replacements/level.SCNE'])['level']
        self.assertEqual(after['Object'],self.doc['level']['Object'])
        self.assertNotIn(LIGHT_NAME,after['Object'])
        self.assertEqual(m['new_light']['Attribute']['VC_PresentationLightId'],0)
        self.assertEqual(m['new_light']['Attribute']['VC_LocatorName'],LIGHT_NAME)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True,type=Path)
    a,rest=p.parse_known_args();BUNDLE=a.bundle
    unittest.main(argv=[__file__,*rest],verbosity=2)
