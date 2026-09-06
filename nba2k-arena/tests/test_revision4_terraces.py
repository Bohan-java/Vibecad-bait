"""Real native-buffer readback, coverage, grounding and mutation-boundary tests."""
import copy
import json
from pathlib import Path
import sys
import unittest
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import revision4_terraces as bank
from revision4_fixtures import DEFAULT_PLACEMENTS


class TerraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(ROOT/'donor/original/arena_020_int_original.iff') as z:
            cls.original = json.loads(b'{'+z.read('level.SCNE')+b'}')['level']
        cls.fixture = copy.deepcopy(cls.original)
        # A prior generated model is the only mutable slot. Donor export format
        # and all original scene sections remain real, independent fixture data.
        cls.fixture['Model'][bank.MODEL] = {'fixture_previous_generated_geometry': True}
        cls.fixture['Object'][bank.MODEL] = {'Type': 'OBJECT', 'Target': bank.MODEL, 'Matrix': bank.IDENTITY[:], 'Transform': bank.MODEL}
        cls.fixture['Material']['venice_v3:grass'] = {}
        cls.fixture['Material']['venice_v3:concrete'] = {}
        cls.palms = [(1860,65,-2400),(2210,100,-1700),(1780,65,-940),
                     (2200,100,-170),(1720,65,650),(2160,100,1410),
                     (1770,65,2200),(2430,100,2910),(1850,65,3650),
                     (2960,100,-3460),(3330,100,-2500),(2960,100,-780),
                     (3430,100,380),(3030,100,2110),(3300,100,3750),
                     (-2960,0,-2450),(-3310,0,-3380),(-2930,0,2510),
                     (-4070,0,3310),(-4220,0,-4080)]
        for i, position in enumerate(cls.palms):
            matrix = bank.IDENTITY[:]; matrix[12:15] = position
            cls.fixture['Object'][f'venice_v3:palm_{i:02}_section_0'] = {'Type': 'OBJECT', 'Target': 'palm_fixture', 'Matrix': matrix}
        for i, (x, y, z, yaw) in enumerate(DEFAULT_PLACEMENTS):
            matrix = bank.IDENTITY[:]; matrix[12:15] = [x,y,z]
            cls.fixture['Object'][f'venice_v3:coastal_double_lamp_{i}'] = {'Type': 'OBJECT', 'Target': 'lamp_fixture', 'Matrix': matrix}
        cls.level = copy.deepcopy(cls.fixture)
        cls.extra = {'keep_old_resource.bin': b'unchanged'}
        cls.report = bank.apply_terraces(cls.level, cls.extra)
        cls.triangles, cls.normals = bank.decode_export(cls.level['Model'][bank.MODEL], cls.extra)

    def test_only_single_generated_model_changes_and_old_bytes_survive(self):
        before, after = copy.deepcopy(self.fixture), copy.deepcopy(self.level)
        del before['Model'][bank.MODEL]; del after['Model'][bank.MODEL]
        self.assertEqual(before, after)
        for section, entries in self.original.items():
            if isinstance(entries, dict):
                for name, value in entries.items():
                    self.assertEqual(self.level[section][name], value)
        self.assertEqual(self.extra['keep_old_resource.bin'], b'unchanged')
        self.assertEqual(self.report['changed_objects'], [])

    def test_all_exported_faces_and_tangent_normals_are_valid(self):
        p = self.triangles
        cross = np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])
        area = np.linalg.norm(cross,axis=1)
        self.assertTrue(np.all(area>1e-7))
        direction = cross/area[:,None]
        self.assertGreater(float((direction[:,None]*self.normals).sum(-1).min()), .999)
        self.assertTrue(np.all(direction[np.abs(direction[:,1])>.1,1]>0))
        self.assertTrue(np.all(direction[np.abs(direction[:,1])<.1,0]<.001))
        self.assertGreaterEqual(p[:,:,0].min(),1100)

    def test_complete_projected_area_and_both_original_empty_regions(self):
        p=self.triangles
        projected = np.abs(np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])[:,1]).sum()/2
        self.assertAlmostEqual(projected,np.ptp(p[:,:,0])*np.ptp(p[:,:,2]),places=4)
        for end in (-1,1):
            for z in (5051,5500,5999,6200,6499,7100,7999):
                for x in (1101,1250,1650,2200,2430,2900,4099):
                    actual=bank.height_on_triangles(p,x,end*z)
                    self.assertLess(abs(actual-bank.surface_height(x,end*z)),.35)

    def test_original_twenty_palms_and_all_three_lamps_remain_supported(self):
        checks = self.report['grounding']
        self.assertEqual(sum('palm_' in c['objects'][0] for c in checks),15)
        self.assertEqual(sum('coastal_double_lamp' in c['objects'][0] for c in checks),3)
        self.assertEqual(len(self.report['unchanged_palms_outside_this_model']),5)
        self.assertTrue(all(c['footprint_supported'] and abs(c['base_error_cm'])<.3 for c in checks))
        for i, position in enumerate(self.palms):
            self.assertEqual(self.level['Object'][f'venice_v3:palm_{i:02}_section_0']['Matrix'][12:15],list(position))

    def test_curved_fronts_follow_design_radii_after_real_quantization(self):
        p=self.triangles
        cross=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])
        wall=p[np.abs(cross[:,1])<1e-7].reshape(-1,3)
        curved=wall[(wall[:,0]<2434.8)&(np.abs(wall[:,2])>4001)]
        radius=np.hypot(curved[:,0]-2435,np.abs(curved[:,2])-4000)
        error=np.min(np.abs(radius[:,None]-np.array(bank.RADII)),axis=1)
        self.assertGreater(len(curved),1000)
        self.assertLess(float(error.max()),.3)
        for x,y in ((1300,30),(1800,65),(2200,100),(3200,100)):
            self.assertLess(abs(bank.height_on_triangles(p,x,0)-y),.13)

    def test_invalid_placement_fails_without_partial_mutation(self):
        level=copy.deepcopy(self.fixture); extra={'old':b'original'}
        level['Object']['venice_v3:palm_00_section_0']['Matrix'][13]=99
        before=copy.deepcopy(level)
        with self.assertRaisesRegex(ValueError,'lose ground'):
            bank.apply_terraces(level,extra)
        self.assertEqual(level,before); self.assertEqual(extra,{'old':b'original'})

    def test_repeated_application_is_deterministic(self):
        level=copy.deepcopy(self.level); extra=dict(self.extra)
        report=bank.apply_terraces(level,extra)
        self.assertEqual(level,self.level); self.assertEqual(extra,self.extra)
        self.assertEqual(report,self.report)


if __name__=='__main__':
    unittest.main()
