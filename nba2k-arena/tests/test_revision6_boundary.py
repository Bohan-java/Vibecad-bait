"""The final scenery checkpoint must not silently regress the protected court."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_revision6 import CHANGED_MODELS, check_scene_changes
from revision3_landscape import IDENTITY


class Revision6BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.before = {
            'Model': {**{name: {'version': 5} for name in CHANGED_MODELS}, 'floor': {'paint': 5}},
            'Object': {'court': {'Type': 'OBJECT', 'Target': 'floor', 'Matrix': IDENTITY}},
            'Material': {'paint': {'DEPTHBIAS': -4}},
            'Texture': {'scan': {'Width': 4096}},
            'Effect': {'native': {'Binary': 'original.shader'}},
        }
        self.after = copy.deepcopy(self.before)
        for name in CHANGED_MODELS:
            self.after['Model'][name]['version'] = 6

    def test_accepts_two_scenery_changes_with_identity_coast_instance(self):
        name = 'venice_v3:coast_r6_0'
        self.after['Model'][name] = {'triangles': 2}
        self.after['Object'][name] = {'Type': 'OBJECT', 'Target': name, 'Transform': name, 'Matrix': IDENTITY}
        changed, added = check_scene_changes(self.before, self.after)
        self.assertEqual({item['name'] for item in changed}, CHANGED_MODELS)
        self.assertEqual({item['category'] for item in added}, {'Model', 'Object'})

    def test_rejects_floor_material_shader_or_existing_object_regression(self):
        for category, name in [('Model', 'floor'), ('Material', 'paint'),
                               ('Effect', 'native'), ('Object', 'court'), ('Texture', 'scan')]:
            with self.subTest(category=category):
                candidate = copy.deepcopy(self.after)
                candidate[category][name]['unexpected'] = True
                with self.assertRaises(ValueError):
                    check_scene_changes(self.before, candidate)

    def test_rejects_removed_records_and_new_light_disguised_as_coast(self):
        candidate = copy.deepcopy(self.after)
        del candidate['Texture']['scan']
        with self.assertRaises(ValueError):
            check_scene_changes(self.before, candidate)
        name = 'venice_v3:coast_r6_light'
        self.after['Object'][name] = {'Type': 'LIGHT', 'Target': name, 'Matrix': IDENTITY}
        with self.assertRaises(ValueError):
            check_scene_changes(self.before, self.after)

    def test_rejects_unintended_instance_movement(self):
        name = 'venice_v3:coast_r6_0'
        self.after['Model'][name] = {'triangles': 2}
        matrix = list(IDENTITY)
        matrix[12] = 1.
        self.after['Object'][name] = {'Type': 'OBJECT', 'Target': name, 'Transform': name, 'Matrix': matrix}
        with self.assertRaises(ValueError):
            check_scene_changes(self.before, self.after)


if __name__ == '__main__':
    unittest.main()
