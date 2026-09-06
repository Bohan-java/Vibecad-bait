"""Outward geometry, real native export and protected-court fixture checks."""
import copy
import json
from pathlib import Path
import sys
import unittest
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from revision3_landscape import M
from revision3_mesh import make_unbaked_material
from revision4_fixtures import DEFAULT_PLACEMENTS, MODEL_NAME, apply_fixtures, fixture_geometry


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(ROOT / 'donor/original/arena_020_int_original.iff') as archive:
            cls.donor = json.loads(b'{' + archive.read('level.SCNE').strip() + b'}')['level']
        cls.mesh = fixture_geometry()

    def level_with_materials(self):
        level = copy.deepcopy(self.donor)
        level['Texture']['test:albedo'] = {'Binary': 'test_albedo.tld'}
        level['Texture']['test:normal'] = {'Binary': 'test_normal.tld'}
        for name in ('aluminum', 'dark_metal'):
            make_unbaked_material(level, M(name), 'test:albedo', 'test:normal')
        return level

    def test_faces_have_outward_agreement_and_valid_uvs(self):
        for material, faces in self.mesh.parts.items():
            faces = np.asarray(faces)
            ns = np.asarray(self.mesh.normals[material])
            geometric = np.cross(faces[:,1]-faces[:,0], faces[:,2]-faces[:,0])
            geometric /= np.linalg.norm(geometric, axis=1)[:,None]
            self.assertTrue(np.all(np.isfinite(ns)))
            mean = ns.mean(1); mean /= np.linalg.norm(mean, axis=1)[:,None]
            self.assertGreater(float((geometric*mean).sum(1).min()), .97)
            uv = np.asarray(self.mesh.uv[material])
            a, b = uv[:,1]-uv[:,0], uv[:,2]-uv[:,0]
            self.assertGreater(float(np.abs(a[:,0]*b[:,1]-a[:,1]*b[:,0]).min()), 1e-9)

    def test_capped_fixture_has_two_separated_heads_above_human_height(self):
        points = np.concatenate(list(self.mesh.parts.values())).reshape(-1,3)
        self.assertAlmostEqual(points[:,1].min(), 0.)
        self.assertGreater(points[:,1].max(), 550)
        self.assertLess(points[:,1].max(), 600)
        left = points[(points[:,0] < -50) & (points[:,1] > 450)]
        right = points[(points[:,0] > 50) & (points[:,1] > 450)]
        self.assertGreater(len(left), 100)
        self.assertEqual(len(left), len(right))
        self.assertAlmostEqual(left[:,0].min(), -right[:,0].max())
        self.assertLess(len(points), 65536)

    def test_native_export_ranges_and_all_original_scene_values_preserved(self):
        level = self.level_with_materials()
        before = copy.deepcopy(level)
        extra = {'existing.bin': b'preserve me'}
        report = apply_fixtures(level, extra)
        json.dumps(report)
        for section, entries in before.items():
            if isinstance(entries, dict):
                for key, value in entries.items():
                    self.assertEqual(level[section][key], value, f'{section}/{key}')
            else:
                self.assertEqual(level[section], entries)
        self.assertEqual(extra['existing.bin'], b'preserve me')
        model = level['Model'][M(MODEL_NAME)]
        indices = np.frombuffer(extra[model['IndexBuffer']['Binary']], dtype='<u2')
        self.assertEqual(len(indices), report['model']['vertices'])
        self.assertLess(int(indices.max()), report['model']['vertices'])
        self.assertEqual(len(extra[model['IndexBuffer']['Binary']]), model['IndexBuffer']['Size'])
        self.assertEqual(report['model']['handedness_mismatches'], 0)
        self.assertLess(report['model']['max_position_error'], .01)
        self.assertEqual(len(report['placements']), len(DEFAULT_PLACEMENTS))
        self.assertEqual(report['new_light_objects'], 0)
        self.assertEqual(report['new_collision_resources'], 0)
        for spec in model['VertexStream']:
            self.assertEqual(len(extra[spec['Binary']]), spec['Size'])

    def test_rotated_lamp_bounds_include_head_overhang(self):
        level = self.level_with_materials()
        report = apply_fixtures(level, {}, placements=((2900, 100, 750, np.pi/2),))
        bounds = report['world_bounds'][0]
        span = np.array(bounds['max'])-bounds['min']
        self.assertGreater(span[2], 200)
        self.assertLess(span[0], 70)
        self.assertGreater(bounds['court_aabb_clearance_cm'], 1000)

    def test_court_intrusion_rejected_before_any_mutation(self):
        level = self.level_with_materials()
        before = copy.deepcopy(level); extra = {'existing.bin': b'x'}
        with self.assertRaisesRegex(ValueError, 'protected court'):
            apply_fixtures(level, extra, placements=((0, 0, 0, 0),))
        self.assertEqual(level, before)
        self.assertEqual(extra, {'existing.bin': b'x'})

    def test_duplicate_names_and_missing_materials_are_atomic(self):
        level = copy.deepcopy(self.donor)
        before = copy.deepcopy(level); extra = {'existing.bin': b'x'}
        with self.assertRaisesRegex(ValueError, 'apply_landscape'):
            apply_fixtures(level, extra)
        self.assertEqual(level, before)
        self.assertEqual(extra, {'existing.bin': b'x'})
        level['Object'][M(MODEL_NAME+'_0')] = {'sentinel': 1}
        before = copy.deepcopy(level)
        with self.assertRaisesRegex(ValueError, 'object already exists'):
            apply_fixtures(level, extra)
        self.assertEqual(level, before)

    def test_design_parameters_reject_nan_and_overlapping_lamps(self):
        for kwargs in ({'pole_height_cm': float('nan')}, {'pole_height_cm': 10},
                       {'arm_reach_cm': 30}, {'shade_radius_cm': 100}):
            with self.assertRaises(ValueError):
                fixture_geometry(**kwargs)


if __name__ == '__main__':
    unittest.main()
