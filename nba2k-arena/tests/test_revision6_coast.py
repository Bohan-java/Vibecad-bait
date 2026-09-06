"""Core regression tests against the actual, hash-verified R5 native archive."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from revision6_coast import COAST, PREFIX, apply_coast, decode_model, height_at, ray_hits


class NativeCoastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=ROOT/'output/revision5/venice_court_revision5.zip'
        if not path.exists():raise unittest.SkipTest('Verified local R5 archive required')
        with zipfile.ZipFile(path) as package:raw=package.read('arena_700_int.iff')
        if hashlib.sha256(raw).hexdigest()!='2fd02c8cfb3d771947cd4fe655db1f64f1ecf51a598bc1a8656ba16e1a670a3d':
            raise AssertionError('R5 fixture hash changed')
        cls.archive=zipfile.ZipFile(io.BytesIO(raw))
        cls.original=json.loads('{'+cls.archive.read('level.SCNE').decode().strip()+'}')['level']
        cls.level=copy.deepcopy(cls.original);cls.extra={};cls.tmp=tempfile.TemporaryDirectory(prefix='revision6-coast-tests-')
        cls.report=apply_coast(cls.level,cls.archive,cls.extra,output_dir=Path(cls.tmp.name)/'ok')
        def read(name):return cls.extra[name] if name in cls.extra else cls.archive.read(name)
        cls.land=[];cls.all=[]
        for name in [COAST]+cls.report['new_models']+['venice_v3:grass_terraces','venice_v3:promenade']:
            p,i,_=decode_model(cls.level['Model'][name],read)
            faces=p[i].reshape(-1,3,3);cls.all.extend(faces)
            if name.startswith(PREFIX):cls.land.extend(faces)
        cls.land=np.asarray(cls.land);cls.all=np.asarray(cls.all)

    @classmethod
    def tearDownClass(cls):
        cls.archive.close();cls.tmp.cleanup()

    def test_only_authorized_old_model_changes_and_objects_are_preserved(self):
        for name,model in self.original['Model'].items():
            if name!=COAST:self.assertEqual(self.level['Model'][name],model,name)
        for name,obj in self.original['Object'].items():self.assertEqual(self.level['Object'][name],obj,name)
        for section,value in self.original.items():
            if section not in ('Model','Object'):self.assertEqual(self.level[section],value,section)
        self.assertEqual(len(self.report['new_models']),63)
        for name in self.report['new_objects']:
            self.assertTrue(name.startswith(PREFIX))
            self.assertEqual(self.level['Object'][name],{'Type':'OBJECT','Target':name,'Transform':name,
                                                       'Matrix':np.eye(4).reshape(-1).tolist()})

    def test_known_gaps_have_the_correct_top_surface_not_only_the_foundation(self):
        for sign in (-1,1):
            self.assertAlmostEqual(height_at(self.all,4300,sign*15000),100.36580834668439,places=7)
            self.assertGreater(height_at(self.all,6500,sign*22500),30.)
            self.assertAlmostEqual(height_at(self.all,3000,sign*30000),100.36580834668439,places=7)
            self.assertAlmostEqual(height_at(self.all,3000,sign*8000.3),100.36580834668439,places=7)
            self.assertGreater(height_at(self.all,-3000,sign*6500.5),-2.)
            self.assertGreater(height_at(self.all,1100.09,sign*5500),-2.)

    def test_tile_boundaries_and_terrace_joins_are_continuous(self):
        for boundary in (-152000.,-72000.,-24000.,-8000.,8000.,24000.,72000.,152000.):
            for x in (3000.,4300.,6500.):
                heights=[height_at(self.all,x,boundary+epsilon) for epsilon in (-.01,0.,.01)]
                self.assertTrue(all(value is not None for value in heights))
                self.assertLess(max(heights)-min(heights),1e-7)
        self.assertEqual(self.report['near_terrace_points_unchanged'],1375)

    def test_original_ocean_and_submerged_toe_avoid_a_coplanar_cover(self):
        def ocean_faces(model,read):
            p,i,prims=decode_model(model,read)
            prim=next(v for v in prims if v['Material']=='venice_v3:ocean')
            return p[i[prim['Start']:prim['Start']+prim['Count']]].reshape(-1,3,3)
        before=ocean_faces(self.original['Model'][COAST],self.archive.read)
        after=ocean_faces(self.level['Model'][COAST],self.extra.__getitem__)
        np.testing.assert_allclose(after,before,atol=1e-8,rtol=0)
        sea=self.report['ocean_level_y_cm'];toe=self.report['toe_x_cm']
        for z in (-159000.,-22500.,0.,22500.,159000.):
            self.assertLess(height_at(self.land,toe-.01,z),sea-.3)
            self.assertAlmostEqual(height_at(self.all,toe-.01,z),sea,places=7)
        self.assertGreater(self.report['foundation_below_ocean_cm'],4.8)

    def test_exported_faces_and_principal_view_rays(self):
        cross=np.cross(self.land[:,1]-self.land[:,0],self.land[:,2]-self.land[:,0])
        self.assertTrue((cross[:,1]>0).all())
        for aim in ([4300,98,-15000],[6500,30,-22500],[3000,98,-30000],[-35000,-38,-60000]):
            self.assertTrue(ray_hits(self.all,[0,850,2200],aim))
        self.assertEqual(self.report['native_grid_span_cm'],16000.)
        json.dumps(self.report,allow_nan=False)

    def test_resource_collision_leaves_scene_and_extra_unchanged(self):
        level=copy.deepcopy(self.original)
        key=next(iter(self.extra));extra={key:b'explicit collision fixture'};saved=extra.copy()
        with self.assertRaisesRegex(ValueError,'Resource collision'):
            apply_coast(level,self.archive,extra,output_dir=Path(self.tmp.name)/'collision')
        self.assertEqual(level,self.original)
        self.assertEqual(extra,saved)


if __name__=='__main__':unittest.main()
