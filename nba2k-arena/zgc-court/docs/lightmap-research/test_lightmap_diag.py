"""Synthetic tests only. No real game archive or shader is included or executed."""
from __future__ import annotations
import argparse
import base64
import copy
import contextlib
import io
import json
import math
from pathlib import Path
import struct
import sys
sys.dont_write_bytecode = True
import tempfile
import unittest
import zipfile

import codec_stdlib as c
import lightmap_diag as d


def fixture():
    resources = {}
    ground, ground_obj = c.plane_model('zgc_r03:ground', (-1000,1000,-1800,1800), 0., 'ground_mat', resources, 'synthetic_base')
    stone, stone_obj = c.plane_model('native_test:stone', (-20,20,-20,20), 0., 'stone_mat', resources, 'synthetic_base')
    lamp, lamp_obj = c.plane_model(d.LAMP_OBJECT, (-20,20,-20,20), 100., 'light_lamppost_genericb:light_mat', resources, 'synthetic_base')
    user = base64.b64encode(bytes(range(48))).decode('ascii')
    stone_obj['UserData'] = lamp_obj['UserData'] = user
    gray = c.make_dds([128]*4096,64,64,'BC4_UNORM',bc4_header='ATI1')
    resources['native_lm.1111111111111111.dds'] = gray
    color = c.make_dds([(80,80,80)]*16,4,4,'BC1_UNORM')
    resources['native_color.2222222222222222.dds'] = color
    lm = {'Width':64,'Height':64,'Mips':7,'Format':'BC4_UNORM','Min':[-.025,0.,0.,.997],
          'Max':[1.13,0.,0.,1.002], 'Twiddled':1,'CompressionMethod':33,'PixelDataSize':2744,
          'Binary':'native_lm.1111111111111111.tld'}
    mat = {'Effect':'simplepbr_CLOD.fx#SYNTHETIC_NOT_A_REAL_SHADER',
           'Resource':{'AlbedoMap':{'Pixelmap':'color'}, 'NormalAndRoughMap':{'Pixelmap':'color'},
                       'MetalMap':{'Pixelmap':'color'}},
           'Parameter':{'AlphaStyle':'OPAQUE','AlbedoModulate':[1.,1.,1.,1.]},
           'Technique':{'AssetHiresLightmap':{'Pass':{'GBuffer':{'CULLMODE':'BACK'}}}}}
    emit = copy.deepcopy(mat)
    emit['Parameter'].update(EmissiveIntensity=5.,EmissiveTint=[1.,1.,1.],AlwaysEmit=1)
    emit['Resource']['EmissiveAlbedoMap']={'Pixelmap':'color'}
    resources['synthetic_vs.bin']=b'SYNTHETIC vertex shader placeholder'
    resources['synthetic_ps.bin']=b'SYNTHETIC pixel shader placeholder'
    effect={'VertexFormat':{'POSITION0':{},'TEXCOORD7':{}},
            'Technique':{'AssetHiresLightmap':{'EnableMask':2,'Pass':{'GBuffer':{
                'VS':{'Binary':'synthetic_vs.bin','Input':['POSITION0','TEXCOORD7']},
                'PS':{'Binary':'synthetic_ps.bin'}}}}}}
    level={'Texture':{'native_test:stone':lm, d.LAMP_OBJECT:copy.deepcopy(lm),
                      'color':{'Binary':'native_color.2222222222222222.tld','Format':'BC1_UNORM','Width':4,'Height':4,'Mips':3},
                      'LIGHT_PROBE_GRID_KEEP':{'sentinel':[1.,2.,3.]}},
           'Material':{'stone_mat':mat,'ground_mat':copy.deepcopy(mat), d.SCONCE_MATERIAL:emit,
                       'light_lamppost_genericb:light_mat':copy.deepcopy(emit),d.CUP_MATERIAL:copy.deepcopy(mat)},
           'Model':{'zgc_r03:ground':ground, 'native_test:stone':stone, d.LAMP_OBJECT:lamp},
           'Object':{'zgc_r03:ground':ground_obj,'native_test:stone':stone_obj,d.LAMP_OBJECT:lamp_obj,
                     'LIGHT_PROBE_GRID_DATA':{'Attribute':{'VERSION':4,'USE_RELIGHTING':0}},
                     'LIGHT_BRICK_MAP':{'sentinel':'unchanged'}},
           'Effect':{mat['Effect']:effect},'Light':{'Sun':{'sentinel':[42,43]}},'Attribute':{'sentinel':'keep'}}
    doc={'level':level}
    resources['level.SCNE']=c.dump_native(doc)
    resources['PostEffect.FxTweakables']=b'UNCHANGED_SYNTHETIC_POSTFX\x00\xff'
    return doc, resources


def zip_memory(resources):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=False) as z:
        for name,raw in resources.items():z.writestr(name,raw)
    stream.seek(0)
    return zipfile.ZipFile(stream,'r')


def args_for(mode='bc4',**kw):
    values=dict(mode=mode,ground_object='zgc_r03:ground',x_cm=0.,z_cm=700.,offset_cm=.01,
                metadata='clone',lm_object='native_test:stone',lm_material='stone_mat',
                emission_scale=1.,invert_bc4=False,minmax_native=False)
    values.update(kw)
    return argparse.Namespace(**values)


class CodecTests(unittest.TestCase):
    def test_bc4_eight_entry_known_vector(self):
        ids=list(range(8))*2
        block=b'\xff\x00'+sum(v<<(3*i) for i,v in enumerate(ids)).to_bytes(6,'little')
        expected=[1,0,6/7,5/7,4/7,3/7,2/7,1/7]*2
        for a,b in zip(c.decode_bc4_block(block),expected):self.assertAlmostEqual(a,b)
    def test_bc4_six_entry_known_vector(self):
        block=b'\x00\xff'+sum((i%8)<<(3*i) for i in range(16)).to_bytes(6,'little')
        for a,b in zip(c.decode_bc4_block(block),[0,1,.2,.4,.6,.8,0,1]*2):self.assertAlmostEqual(a,b)
    def test_bc4_constants(self):
        for q in (0,1,128,254,255):
            self.assertEqual(c.decode_bc4_block(c.encode_bc4_block([q]*16)),[q/255]*16)
    def test_bc4_size_and_mip_chain(self):
        self.assertEqual(c.payload_size(64,64,7,'BC4_UNORM'),2744)
        for header,size in [('ATI1',2872),('DX10',2892),('BC4U',2872)]:
            raw=c.make_dds([128]*4096,64,64,'BC4_UNORM',bc4_header=header)
            self.assertEqual(len(raw),size)
            self.assertTrue(c.inspect_dds(raw)['payload_size_matches'])
    def test_rectangular_non_power_two(self):
        raw=c.make_dds([128]*(120*32),120,32,'BC4_UNORM')
        self.assertEqual(c.inspect_dds(raw)['mips'],7)
        self.assertEqual(c.decode_bc4_top(raw),[128/255]*(120*32))
    def test_bc4_asymmetric_orientation(self):
        pixels=d.chart_scalar()
        raw=c.make_dds(pixels,64,64,'BC4_UNORM')
        decoded=c.decode_bc4_top(raw)
        self.assertAlmostEqual(decoded[0],230/255)
        self.assertAlmostEqual(decoded[63],100/255)
        self.assertEqual(decoded[40*64+10],0.)
    def test_complete_bc1_and_bc3(self):
        for fmt,pixel in [('BC1_UNORM',(80,90,100)),('BC3_UNORM',(128,128,0,240))]:
            raw=c.make_dds([pixel]*16,4,4,fmt)
            self.assertTrue(c.inspect_dds(raw)['payload_size_matches'])
    def test_truncated_dds_rejected(self):
        raw=c.make_dds([128]*4096,64,64,'BC4_UNORM')
        with self.assertRaises(ValueError):c.decode_bc4_top(raw[:-1])
    def test_array_not_treated_as_plain_texture(self):
        raw=bytearray(c.make_dds([128]*4096,64,64,'BC4_UNORM'))
        struct.pack_into('<I',raw,140,2)
        with self.assertRaises(ValueError):c.decode_bc4_top(bytes(raw))
    def test_duplicate_scne_key_rejected(self):
        with self.assertRaises(ValueError):c.load_scne(b'"level":{"a":1,"a":2}')
    def test_nonfinite_scne_rejected(self):
        with self.assertRaises(ValueError):c.load_scne(b'"level":{"a":NaN}')
    def test_native_scne_roundtrip(self):
        doc,_=fixture()
        raw=c.dump_native(doc)
        self.assertEqual(c.dump_native(c.load_scne(raw)),raw)
    def test_plane_position_uv7_and_winding(self):
        r={}
        m,o=c.plane_model('t',(-200,200,500,900),.01,'mat',r,'test')
        with zip_memory(r) as z:p=d.decode_positions(z,m)
        self.assertTrue(all(v[1]==.01 for v in p))
        self.assertEqual(o['Matrix'],c.ROTATED)
        ib=r[m['IndexBuffer']['Binary']]
        ix=struct.unpack('<6H',ib)
        a,b,e=[p[k] for k in ix[:3]]
        cross_y=(b[2]-a[2])*(e[0]-a[0])-(b[0]-a[0])*(e[2]-a[2])
        self.assertGreater(cross_y,0)
        self.assertEqual(m['Duv7'],m['Prim'][0]['Duv7'])
        self.assertAlmostEqual(m['Duv7'][0],.94/400)
        self.assertEqual([v['Stride'] for v in m['VertexStream']],[8,4,12])


class PlanTests(unittest.TestCase):
    def setUp(self):self.doc,self.resources=fixture()
    def test_all_modes_are_additive_and_exactly_reversible(self):
        for mode in ('bound-control','bc4','uv7-flip','minmax','emission'):
            with self.subTest(mode=mode),zip_memory(self.resources) as z:
                additions,extra,manifest=d.make_plan(z,args_for(mode))
            patched=c.dump_native(d.check_additive(self.doc,additions))
            self.assertEqual(d.reverse_document(patched,self.resources['level.SCNE'],additions),self.resources['level.SCNE'])
            self.assertEqual(len(additions['Object']),4)
            self.assertTrue(all(not n.endswith(('.iff','.tld')) for n in extra))
            self.assertFalse(manifest['game_tested'])
            self.assertEqual(self.doc['level']['Light'],c.load_scne(patched)['level']['Light'])
    def test_patch_is_exactly_four_meters(self):
        with zip_memory(self.resources) as z:a,e,m=d.make_plan(z,args_for())
        self.assertEqual(m['patch_bounds_world_cm'],[-200,200,500,900])
        self.assertEqual(m['tiles'][3]['world_bounds_xz_cm'],[2.,200.,702.,900.])
    def test_uv7_flip_does_not_change_textures_or_materials(self):
        with zip_memory(self.resources) as z:a,e,_=d.make_plan(z,args_for('bc4'))
        with zip_memory(self.resources) as z:b,f,_=d.make_plan(z,args_for('uv7-flip'))
        self.assertEqual(a['Texture'],b['Texture'])
        self.assertEqual(a['Material'],b['Material'])
        for name in a['Model']:
            ma,mb=copy.deepcopy(a['Model'][name]),copy.deepcopy(b['Model'][name])
            sa,sb=ma.pop('VertexStream'),mb.pop('VertexStream')
            self.assertEqual(ma,mb)
            self.assertEqual(sa[:2],sb[:2])
            ra,rb=e[sa[2]['Binary']],f[sb[2]['Binary']]
            for i in range(4):self.assertEqual(ra[12*i:12*i+8],rb[12*i:12*i+8])

    def test_minmax_same_position_baseline_only_changes_ranges(self):
        _, base = fixture()
        with zip_memory(base) as z:
            a, ar, _ = d.make_plan(z, args_for('minmax', minmax_native=True))
        with zip_memory(base) as z:
            b, br, _ = d.make_plan(z, args_for('minmax'))
        self.assertEqual(ar, br)
        for index in (1,2,3):
            key=d.PREFIX+f'tile-{index}'
            a['Texture'][key]['Min'][0]=b['Texture'][key]['Min'][0]
            a['Texture'][key]['Max'][0]=b['Texture'][key]['Max'][0]
        self.assertEqual(a,b)

    def test_minmax_changes_only_red_range(self):
        with zip_memory(self.resources) as z:a,e,_=d.make_plan(z,args_for('minmax'))
        original=self.doc['level']['Texture']['native_test:stone']
        specs=[a['Texture'][d.PREFIX+f'tile-{i}'] for i in range(4)]
        self.assertEqual(len({s['Binary'] for s in specs}),1)
        for s in specs:
            self.assertEqual(s['Min'][1:],original['Min'][1:])
            self.assertEqual(s['Max'][1:],original['Max'][1:])
    def test_bc4_inversion_at_fixed_positions(self):
        with zip_memory(self.resources) as z:a,e,_=d.make_plan(z,args_for())
        with zip_memory(self.resources) as z:b,f,_=d.make_plan(z,args_for(invert_bc4=True))
        self.assertEqual(a['Object'],b['Object'])
        self.assertEqual(a['Model'],b['Model'])
        key=d.PREFIX+'tile-0'
        ra=e[a['Texture'][key]['Binary'][:-4]+'.dds']
        rb=f[b['Texture'][key]['Binary'][:-4]+'.dds']
        self.assertEqual(set(c.decode_bc4_top(ra)),{0.})
        self.assertEqual(set(c.decode_bc4_top(rb)),{1.})
    def test_emission_off_is_exact_position_control(self):
        with zip_memory(self.resources) as z:a,e,_=d.make_plan(z,args_for('emission'))
        with zip_memory(self.resources) as z:b,f,_=d.make_plan(z,args_for('emission',emission_scale=0.))
        self.assertEqual(e,f)
        self.assertEqual(a['Texture'],b['Texture'])
        self.assertEqual(a['Object'],b['Object'])
        self.assertEqual(a['Model'],b['Model'])
        for name,mat in a['Material'].items():
            clone=copy.deepcopy(mat);clone['Parameter']['EmissiveIntensity']=0.
            self.assertEqual(clone,b['Material'][name])
    def test_metadata_is_independent_axis(self):
        with zip_memory(self.resources) as z:a,e,_=d.make_plan(z,args_for())
        with zip_memory(self.resources) as z:b,f,_=d.make_plan(z,args_for(metadata='plain'))
        self.assertEqual(e,f)
        for i in range(4):
            s=copy.deepcopy(a['Texture'][d.PREFIX+f'tile-{i}'])
            del s['Twiddled'];del s['CompressionMethod']
            self.assertEqual(s,b['Texture'][d.PREFIX+f'tile-{i}'])
    def test_outside_ground_rejected(self):
        with zip_memory(self.resources) as z:
            with self.assertRaises(ValueError):d.make_plan(z,args_for(x_cm=2000.))
    def test_arbitrary_ground_matrix_rejected(self):
        self.doc['level']['Object']['zgc_r03:ground']['Matrix'][12]=123.
        self.resources['level.SCNE']=c.dump_native(self.doc)
        with zip_memory(self.resources) as z:
            with self.assertRaises(ValueError):d.make_plan(z,args_for())
    def test_namespace_collision_rejected(self):
        self.doc['level']['Object'][d.PREFIX+'other']={}
        self.resources['level.SCNE']=c.dump_native(self.doc)
        with zip_memory(self.resources) as z:
            with self.assertRaises(ValueError):d.make_plan(z,args_for())
    def test_missing_userdata_rejected(self):
        del self.doc['level']['Object']['native_test:stone']['UserData']
        self.resources['level.SCNE']=c.dump_native(self.doc)
        with zip_memory(self.resources) as z:
            with self.assertRaises(ValueError):d.make_plan(z,args_for())
    def test_noncanonical_scene_stays_inventory_only(self):
        self.resources['level.SCNE']=json.dumps(self.doc).encode()
        with zip_memory(self.resources) as z:
            with self.assertRaises(ValueError):d.make_plan(z,args_for())
    def test_changed_diagnostic_blocks_rollback(self):
        with zip_memory(self.resources) as z:a,e,_=d.make_plan(z,args_for())
        patched=d.check_additive(self.doc,a)
        patched['level']['Object'][d.PREFIX+'tile-0']['UserData']='changed'
        with self.assertRaises(ValueError):d.reverse_document(c.dump_native(patched),self.resources['level.SCNE'],a)
    def test_lighting_edit_blocks_rollback(self):
        with zip_memory(self.resources) as z:a,e,_=d.make_plan(z,args_for())
        patched=d.check_additive(self.doc,a)
        patched['level']['Light']['Sun']['sentinel'][0]=99
        with self.assertRaises(ValueError):d.reverse_document(c.dump_native(patched),self.resources['level.SCNE'],a)
    def test_short_reference_followed(self):
        level={'Object':{'ROOT':{'target':'B0'}},'Texture':{'B0':{'Binary':'test.bin'}}}
        closure,amb=d.references(level,[('Object','ROOT')])
        self.assertIn(('Texture','B0'),closure)
    def test_ambiguous_reference_not_guessed(self):
        level={'Object':{'ROOT':{'target':'X'},'X':{}},'Texture':{'X':{'Binary':'test.bin'}}}
        closure,amb=d.references(level,[('Object','ROOT')])
        self.assertIn('X',amb)
        self.assertNotIn(('Texture','X'),closure)
    def test_safe_bundle_composition(self):
        with zip_memory(self.resources) as z:a,e,m=d.make_plan(z,args_for('emission'))
        with tempfile.TemporaryDirectory(dir=d.HERE/'evidence',prefix='_test_') as temp:
            out=Path(temp);(out/'members').mkdir()
            raw=d.json_bytes(a);m['additions_sha256']=c.sha256(raw)
            (out/'additions.json').write_bytes(raw);(out/'manifest.json').write_bytes(d.json_bytes(m))
            for n,b in e.items():(out/'members'/n).write_bytes(b)
            with zip_memory(self.resources) as z:replacements=d.build_replacements(z,out)
            self.assertEqual(c.sha256(replacements['level.SCNE']),m['planned_scene_sha256'])
            first=next(iter(e));(out/'members'/first).write_bytes(b'bad')
            with zip_memory(self.resources) as z:
                with self.assertRaises(ValueError):d.build_replacements(z,out)
    def test_cli_inventory_plan_compose_roundtrip(self):
        _, resources=fixture()
        with tempfile.TemporaryDirectory(dir=d.HERE/'evidence') as tmp:
            root=Path(tmp)
            source=root/'SYNTHETIC_fixture.zip'
            with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=False) as z:
                for name,blob in resources.items():z.writestr(name,blob)
            prefix=str(root.relative_to(d.HERE))
            before=source.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(d.main(['inventory','--iff',str(source),'--extract-evidence','--out',prefix+'/inventory']),0)
                self.assertEqual(d.main(['plan','--iff',str(source),'--mode','emission','--out',prefix+'/emission']),0)
                self.assertEqual(d.main(['compose','--iff',str(source),'--bundle',prefix+'/emission','--out',prefix+'/composed']),0)
            self.assertEqual(source.read_bytes(),before)
            info=json.loads((root/'inventory/inventory.json').read_text())
            self.assertEqual(info['formats']['BC4_UNORM'],2)
            self.assertFalse(info['shader_semantics_decoded'])
            receipt=json.loads((root/'composed/compose_receipt.json').read_text())
            self.assertTrue(receipt['exact_rollback_verified'])
            self.assertFalse(receipt['iff_written'])
            self.assertFalse(list(root.rglob('*.iff')))

    def test_lfs_pointer_rejected(self):
        with tempfile.TemporaryDirectory(dir=d.HERE/'evidence',prefix='_test_') as temp:
            p=Path(temp)/'pointer.txt';p.write_text('version https://git-lfs.github.com/spec/v1\noid sha256:abcd\nsize 1686988259\n')
            with self.assertRaises(ValueError):d.open_archive(p)
    def test_input_path_outside_workspace_rejected(self):
        with self.assertRaises(ValueError):d.read_path('/etc/hosts')
    def test_output_traversal_and_overwrite_rejected(self):
        for value in ('../../escape','/tmp/escape','evidence'):
            with self.assertRaises(ValueError):d.new_output(value)


if __name__=='__main__':unittest.main(verbosity=2)
