"""R6 geometry, native quantization, actual texture codec and scope tests."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from revision3_landscape import M, Mesh, add_object
from revision3_mesh import make_unbaked_material
from revision3_textures import decode_tld_mips, encode_texture
from revision6_building import (COLORS, FULL_MIN, FULL_MAX, MODEL, PREFIX,
                               apply_building, building_geometry)


class BuildingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive=zipfile.ZipFile(ROOT/'donor/original/arena_020_int_original.iff')
        cls.base=json.loads(b'{'+cls.archive.read('level.SCNE').strip()+b'}')['level']
        cls.extra={}
        with tempfile.TemporaryDirectory() as directory:
            yy,xx=np.indices((64,64))
            color=np.stack([145+(xx%13),142+(yy%11),132+((xx+yy)%17)],axis=-1).astype('uint8')
            refs=[]
            for name,image,linear in (('test_r6_color',Image.fromarray(color),False),
                    ('test_r6_normal',Image.new('RGBA',(32,32),(130,125,0,242)),True)):
                key,spec,raw,_=encode_texture(name,image,linear=linear,output_dir=directory)
                cls.base['Texture'][key]=spec;cls.extra[spec['Binary']]=raw;refs.append(key)
        make_unbaked_material(cls.base,M('concrete'),*refs)
        old=Mesh();old.box('concrete',[120,150,-3210],[1200,300,620],bevel=2)
        old.box('concrete',[120,304,-3210],[1220,8,640],bevel=1)
        old.export(cls.base,cls.extra,'service_building')
        add_object(cls.base,MODEL,'service_building',(0,0,0))
        cls.mesh=building_geometry()
        cls.result=copy.deepcopy(cls.base);cls.result_extra=dict(cls.extra)
        cls.report=apply_building(cls.result,cls.archive,cls.result_extra,output_dir=None)

    @classmethod
    def tearDownClass(cls):
        cls.archive.close()

    def test_geometry_bounds_normals_and_uvs(self):
        self.assertEqual(set(self.mesh.parts),{M(PREFIX+r) for r in COLORS})
        p=np.concatenate(list(self.mesh.parts.values())).reshape(-1,3)
        np.testing.assert_array_equal(p.min(0),FULL_MIN)
        np.testing.assert_array_equal(p.max(0),FULL_MAX)
        self.assertLess(len(p),65536)
        for mat,values in self.mesh.parts.items():
            faces=np.asarray(values);normals=np.asarray(self.mesh.normals[mat])
            cross=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
            length=np.linalg.norm(cross,axis=1)
            self.assertTrue(np.isfinite(faces).all());self.assertGreater(length.min(),.01)
            np.testing.assert_allclose(normals,cross[:,None,:]/length[:,None,None]+np.zeros_like(normals),atol=1e-12)
            uv=np.asarray(self.mesh.uv[mat]);a,b=uv[:,1]-uv[:,0],uv[:,2]-uv[:,0]
            self.assertGreater(np.abs(a[:,0]*b[:,1]-a[:,1]*b[:,0]).min(),1e-8)
        wall=np.asarray(self.mesh.parts[M(PREFIX+'wall')])
        n=np.asarray(self.mesh.normals[M(PREFIX+'wall')])[:,0]
        for axis,bound,sign in ((0,-480,-1),(0,720,1),(1,0,-1),(1,300,1),(2,-3520,-1),(2,-2900,1)):
            mask=np.isclose(wall[:,:,axis],bound).all(1)
            self.assertTrue(mask.any());np.testing.assert_allclose(n[mask,axis],sign)

    def test_front_is_tiled_with_recess_and_no_overlay_or_door_projection(self):
        projected=0.
        for mat,values in self.mesh.parts.items():
            if mat.endswith('roof'):
                continue
            p=np.asarray(values)
            self.assertLessEqual(p[:,:,2].max(),-2900)
            cross=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])
            front=cross[:,2]>0
            projected+=cross[front,2].sum()/2
            if mat.endswith('joint'):
                np.testing.assert_allclose(p[front,:,2],-2900.6)
        # All front triangles exactly cover the 12 x 3 m projection once.
        self.assertAlmostEqual(projected,1200*300,places=7)

    def test_native_recess_survives_r16_export(self):
        r=self.report['native_validation']
        self.assertGreater(r['decoded_recess_cm'],.55)
        self.assertLess(r['decoded_recess_cm'],.65)
        self.assertEqual(r['index_format'],'R16_UINT')
        self.assertEqual(r['zero_area_triangles'],0)
        self.assertGreater(r['minimum_native_normal_dot'],.999)
        model=self.result['Model'][MODEL]
        start=0
        for prim in model['Prim']:
            self.assertEqual(prim['Start'],start)
            self.assertEqual(prim['LodList'],[{'Start':start,'Count':prim['Count']}])
            start+=prim['Count']
        self.assertEqual(start,self.report['model']['vertices'])

    def test_only_one_model_changes_and_dedicated_resources_append(self):
        changes=[]
        names={M(PREFIX+r) for r in COLORS}
        for section,values in self.base.items():
            if isinstance(values,dict):
                for key,value in values.items():
                    if self.result[section].get(key)!=value:changes.append((section,key))
                self.assertEqual(set(self.result[section])-set(values),names if section in ('Material','Texture') else set())
            else:self.assertEqual(self.result[section],values)
        self.assertEqual(changes,[('Model',MODEL)])
        for name,raw in self.extra.items():self.assertEqual(self.result_extra[name],raw)
        self.assertEqual(self.result['Object'],self.base['Object'])
        self.assertFalse(self.report['changed_object_keys'])
        json.dumps(self.report)

    def test_materials_reuse_exact_normal_bindings_and_full_source_resolution(self):
        old=self.base['Material'][M('concrete')]
        for role in COLORS:
            key=M(PREFIX+role);mat=self.result['Material'][key]
            expected=copy.deepcopy(old)
            expected['Resource']['AlbedoMap']['Pixelmap']=key
            expected['Parameter']['NormalHeight']=.08
            self.assertEqual(mat,expected)
            spec=self.result['Texture'][key]
            self.assertEqual([spec['Width'],spec['Height']],[64,64])
            decoded=decode_tld_mips(self.result_extra[spec['Binary']],spec)
            self.assertEqual(decoded[-1].size,(1,1))
            rgb=np.asarray(decoded[0])[:,:,:3]
            self.assertGreater(rgb.std(),.1)
            self.assertLess(rgb.std(),8)
            np.testing.assert_allclose(rgb.mean((0,1)),COLORS[role],atol=7)

    def test_failures_leave_scene_and_resource_mappings_unchanged(self):
        level=copy.deepcopy(self.base);extra=dict(self.extra)
        with patch('revision6_building._verify_native',side_effect=ValueError('forced native validation failure')):
            with self.assertRaisesRegex(ValueError,'forced native'):
                apply_building(level,self.archive,extra,output_dir=None)
        self.assertEqual(level,self.base);self.assertEqual(extra,self.extra)
        level['Texture'][M(PREFIX+'wall')]={'reserved':True}
        before=copy.deepcopy(level)
        with self.assertRaisesRegex(ValueError,'already exists'):
            apply_building(level,self.archive,extra,output_dir=None)
        self.assertEqual(level,before);self.assertEqual(extra,self.extra)


if __name__=='__main__':
    unittest.main()
