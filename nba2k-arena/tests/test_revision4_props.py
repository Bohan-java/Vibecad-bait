"""Native prop export, cavity/winding, material channels and mutation scope."""
import copy
from collections import Counter
import json
from pathlib import Path
import sys
import unittest
import zipfile

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from revision3_landscape import M, add_object, bleachers, coastal_fixtures
from revision3_mesh import decode_tangent_frames, make_unbaked_material
from revision3_textures import decode_tld_mips
from revision4_props import CHANGED_MODELS, MOVED_OBJECT, PROP_MATERIALS, apply_props, bins_geometry, bleachers_geometry


class PropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(ROOT/'donor/original/arena_020_int_original.iff') as archive:
            cls.base=json.loads(b'{'+archive.read('level.SCNE').strip()+b'}')['level']
        cls.base['Texture']['test:color']={'Binary':'test_color.tld'}
        cls.base['Texture']['test:normal']={'Binary':'test_normal.tld'}
        for label in ('concrete','aluminum','dark_metal'):
            make_unbaked_material(cls.base,M(label),'test:color','test:normal')
        cls.base_extra={}
        for label,mesh in (('bins',coastal_fixtures()),('bleachers',bleachers())):
            mesh.export(cls.base,cls.base_extra,label)
        for i,p in enumerate(((-1260,0,1870),(-1300,0,-1810),(1110,0,2650))):
            add_object(cls.base,M('bins'),f'bins_{i}',p)
        for i,z in enumerate((-710,710)):
            add_object(cls.base,M('bleachers'),f'bleachers_{i}',(-1620,0,z))
        cls.bins=bins_geometry();cls.bench=bleachers_geometry()

    def test_geometry_is_finite_nondegenerate_with_matching_normals_and_uvs(self):
        for mesh in (self.bins,self.bench):
            self.assertLess(sum(len(v) for v in mesh.parts.values())*3,65536)
            for mat,values in mesh.parts.items():
                faces=np.asarray(values);ns=np.asarray(mesh.normals[mat])
                self.assertTrue(np.all(np.isfinite(faces)))
                cross=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
                length=np.linalg.norm(cross,axis=1)
                self.assertGreater(length.min(),1e-7)
                mean=ns.mean(1);mean/=np.linalg.norm(mean,axis=1)[:,None]
                # A continuous cloth normal spans the real fold between two
                # profile segments; it need not equal either triangle normal.
                threshold=.9 if mat==M('prop_liner') else .96
                self.assertGreater(float((cross/length[:,None]*mean).sum(1).min()),threshold)
                uv=np.asarray(mesh.uv[mat]);a,b=uv[:,1]-uv[:,0],uv[:,2]-uv[:,0]
                self.assertGreater(float(np.abs(a[:,0]*b[:,1]-a[:,1]*b[:,0]).min()),1e-9)

    def test_bin_has_open_mouth_inward_wall_and_dark_upward_floor(self):
        interior=np.asarray(self.bins.parts[M('prop_bin_inside')])
        mid=interior.mean(1);normal=np.cross(interior[:,1]-interior[:,0],interior[:,2]-interior[:,0])
        wall=(mid[:,1]>10)&(mid[:,1]<94)
        radial=mid.copy();radial[:,1]=0
        self.assertTrue(np.all((normal[wall]*radial[wall]).sum(1)<0))
        floor=np.isclose(interior[:,:,1],5).all(1)
        self.assertGreater(np.count_nonzero(floor),50)
        self.assertTrue(np.all(normal[floor,1]>0))
        for mat in ('prop_bin_green','prop_bin_inside','prop_liner'):
            p=np.asarray(self.bins.parts[M(mat)])
            upper=p[p[:,:,1].min(1)>90]
            # No mouth-spanning cap/cloth triangle through the central opening.
            self.assertTrue(np.all(np.linalg.norm(upper[:,:,[0,2]],axis=2).min(1)>25),mat)

    def test_liner_is_separate_double_sided_and_uneven(self):
        p=np.asarray(self.bins.parts[M('prop_liner')])
        self.assertGreater(len(p),1000)
        np.testing.assert_allclose(p[::2],p[1::2,::-1])
        points=p.reshape(-1,3)
        self.assertGreater(points[:,1].max(),98)
        self.assertLess(points[:,1].min(),70)
        self.assertGreater(np.linalg.norm(points[:,[0,2]],axis=1).max(),34)

    def test_liner_fold_does_not_cut_through_the_rolled_green_rim(self):
        faces=np.asarray(self.bins.parts[M('prop_liner')])
        weights=np.array([[1,0,0],[0,1,0],[0,0,1],[1/3,1/3,1/3],
                          [.5,.5,0],[.5,0,.5],[0,.5,.5],
                          [.5,.25,.25],[.25,.5,.25],[.25,.25,.5]])
        sample=np.einsum('sv,tvd->tsd',weights,faces).reshape(-1,3)
        radius=np.linalg.norm(sample[:,[0,2]],axis=1)
        distance=np.sqrt((radius-31.55)**2+(sample[:,1]-96)**2)
        self.assertGreater(float(distance.min()),1.05)

    def test_liner_normals_are_continuous_periodic_unit_and_correctly_double_sided(self):
        normals=np.asarray(self.bins.normals[M('prop_liner')])
        np.testing.assert_allclose(np.linalg.norm(normals,axis=2),1,atol=1e-12)
        np.testing.assert_allclose(normals[::2],-normals[1::2,::-1],atol=1e-12)
        front=normals[::2];uv=np.asarray(self.bins.uv[M('prop_liner')])[::2]
        shared={}
        for coordinate,normal in zip(uv.reshape(-1,2),front.reshape(-1,3)):
            key=(round(coordinate[0]*256)%256,round(coordinate[1]*10))
            if key in shared:np.testing.assert_allclose(shared[key],normal,atol=1e-12)
            else:shared[key]=normal
        self.assertEqual(len(shared),256*11)
        faces=np.asarray(self.bins.parts[M('prop_liner')])[::2]
        geometric=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
        geometric/=np.linalg.norm(geometric,axis=1)[:,None]
        self.assertGreater(float((geometric[:,None,:]*front).sum(2).min()),.7)
        # Smoothly varying shared normals, rather than one hard normal per face.
        self.assertGreater(float(np.linalg.norm(front[:,1]-front[:,0],axis=1).max()),.1)

    def test_concrete_dome_is_grey_material_and_smoothly_outward(self):
        p=np.asarray(self.bins.parts[M('concrete')]);ns=np.asarray(self.bins.normals[M('concrete')])
        crown=p.mean(1)[:,1]>100
        self.assertGreater(np.count_nonzero(crown),2000)
        self.assertAlmostEqual(p[:,:,1].max(),127)
        center=p[crown].mean(1)-[76,99,0]
        self.assertTrue(np.all((center*ns[crown].mean(1)).sum(1)>0))
        self.assertNotIn(M('aluminum'),self.bins.parts)

    def test_bleachers_retain_five_rows_and_add_open_feet_and_braces(self):
        old=bleachers()
        # Recoloring the old dark legs must retain every original triangle.
        original=Counter(np.asarray(face).tobytes() for faces in old.parts.values() for face in faces)
        current=Counter(np.asarray(face).tobytes() for faces in self.bench.parts.values() for face in faces)
        self.assertFalse(original-current)
        self.assertEqual(set(self.bench.parts),{M('aluminum')})
        self.assertEqual(set(self.bench.uv),{M('aluminum')})
        self.assertEqual(set(self.bench.normals),{M('aluminum')})
        p=np.concatenate(list(self.bench.parts.values())).reshape(-1,3)
        self.assertGreaterEqual(p[:,1].min(),0)
        self.assertLess(p[:,1].max(),300)
        self.assertLess(p[:,0].min(),-310)
        self.assertGreater(len(self.bench.parts[M('aluminum')]),sum(len(v) for v in old.parts.values())+500)

    def test_real_export_changes_only_two_models_and_appends_resources(self):
        level=copy.deepcopy(self.base);extra=dict(self.base_extra)
        before=copy.deepcopy(level);before_extra=dict(extra)
        report=apply_props(level,extra);json.dumps(report)
        changed=[]
        for section,values in before.items():
            if isinstance(values,dict):
                for key,value in values.items():
                    if level[section][key]!=value:
                        changed.append((section,key))
            else:self.assertEqual(level[section],values)
        self.assertEqual(set(changed),{('Model',name) for name in CHANGED_MODELS}|{('Object',MOVED_OBJECT)})
        expected_objects=copy.deepcopy(before['Object']);expected_objects[MOVED_OBJECT]['Matrix'][12]=940.
        self.assertEqual(level['Object'],expected_objects)
        for binary,raw in before_extra.items():self.assertEqual(extra[binary],raw)
        self.assertEqual(report['changed_model_keys'],list(CHANGED_MODELS))
        self.assertEqual(set(report['added_materials']),{M(n) for n in PROP_MATERIALS})
        self.assertEqual(len(report['preserved_object_names']),4)
        self.assertEqual(report['changed_object_keys'],[MOVED_OBJECT])
        self.assertEqual(report['object_changes'][MOVED_OBJECT]['only_changed_matrix_index'],12)
        bins=level['Model'][M('bins')]
        self.assertLess(bins['Max'][0]+940,1100)
        for item in report['models']:
            model=level['Model'][item['model']]
            ids=np.frombuffer(extra[model['IndexBuffer']['Binary']],'<u2')
            self.assertLess(int(ids.max()),item['vertices'])
            self.assertEqual(len(ids),item['vertices'])
            self.assertEqual(item['handedness_mismatches'],0)
            self.assertLess(item['max_position_error'],.01)
            for stream in model['VertexStream']:
                self.assertEqual(len(extra[stream['Binary']]),stream['Size'])
            if item['model']==M('bins'):
                part=next(p for p in model['Prim'] if p['Material']==M('prop_liner'))
                stream=model['VertexStream'][2]
                frames=np.ndarray((item['vertices'],),'<u4',extra[stream['Binary']],strides=(stream['Stride'],))
                decoded=decode_tangent_frames(frames[part['Start']:part['Start']+part['Count']])[0]
                expected=np.asarray(self.bins.normals[M('prop_liner')]).reshape(-1,3)
                self.assertGreater(float((decoded*expected).sum(1).min()),np.cos(np.radians(.3)))
        for label,(_,roughness) in PROP_MATERIALS.items():
            material=level['Material'][M(label)]
            key=material['Resource']['NormalAndRoughMap']['Pixelmap'];spec=level['Texture'][key]
            pixels=np.asarray(decode_tld_mips(extra[spec['Binary']],spec)[0])
            self.assertEqual(spec['TexelUsage'],'LINEAR')
            self.assertGreater(float(pixels[:,:,3].min())/255,.8)
            self.assertAlmostEqual(float(pixels[:,:,3].mean())/255,roughness,delta=.01)
            self.assertEqual(material['Parameter']['NormalHeight'],0)

    def test_missing_target_or_existing_prop_material_fails_atomically(self):
        for remove_target in (True,False):
            level=copy.deepcopy(self.base);extra=dict(self.base_extra)
            if remove_target:del level['Model'][M('bins')]
            else:level['Material'][M('prop_liner')]={'sentinel':1}
            before=copy.deepcopy(level);before_extra=dict(extra)
            with self.assertRaises(ValueError):apply_props(level,extra)
            self.assertEqual(level,before);self.assertEqual(extra,before_extra)

    def test_generated_bin_move_rejects_an_unexpected_existing_position(self):
        level=copy.deepcopy(self.base);extra=dict(self.base_extra)
        level['Object'][MOVED_OBJECT]['Matrix'][12]=1120.
        before=copy.deepcopy(level);before_extra=dict(extra)
        with self.assertRaisesRegex(ValueError,'Expected generated bins_2 position'):
            apply_props(level,extra)
        self.assertEqual(level,before);self.assertEqual(extra,before_extra)


if __name__=='__main__':unittest.main()
