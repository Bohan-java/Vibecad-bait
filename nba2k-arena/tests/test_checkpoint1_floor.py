"""Guard the exact change boundary of the real packed checkpoint candidate."""
from pathlib import Path
import copy
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from checkpoint1_floor import (DONOR, SOURCE, FLOOR_SOURCE, OUTPUT_DIR, CACHE,
                               candidate_scene, donor_line_slots, floor_data,
                               load_scene, validate_pair, verified_inputs)


class CheckpointFloorTests(unittest.TestCase):
    def test_archived_inputs_have_not_been_overwritten(self):
        verified_inputs()

    def test_original_floor_matches_v2_geometry(self):
        target, donor, positions, indices, prims = floor_data()
        with zipfile.ZipFile(SOURCE) as archive:
            v2 = load_scene(archive)
        self.assertEqual(donor, v2['Model'][target])
        self.assertEqual(len(positions), 3231)
        self.assertEqual(len(indices), 9126)
        self.assertEqual(prims[8]['Mesh'], 'line_four_point_lowShape')
        self.assertEqual((prims[8]['Start'], prims[8]['Count']), (3642, 1236))

    def test_removing_draw_does_not_shift_subsequent_indices_or_mutate_source(self):
        with zipfile.ZipFile(SOURCE) as archive:
            source = load_scene(archive)
        baseline = copy.deepcopy(source)
        candidate, removed = candidate_scene(source)
        self.assertEqual(source, baseline)
        model = candidate['Model'][source['Object']['__floor00__']['Target']]
        by_name = {p['Mesh']: p for p in model['Prim']}
        self.assertNotIn(removed['Mesh'], by_name)
        self.assertEqual(by_name['line_free_throw_circle_lowShape']['Start'], 4878)
        self.assertEqual(by_name['line_charge_circle_lowShape']['Start'], 7686)
        self.assertEqual(by_name['line_charge_circle_lowShape']['Material'],
                         'floor_clutchtime_court:floor_line_mat1')
        for name, slot in donor_line_slots().items():
            actual = candidate['Material'][name]['Resource']['DetailAlbedoTexture']
            self.assertEqual(actual, slot)
            texture = candidate['Texture'][actual['Pixelmap']]
            self.assertEqual(texture['Min'][3], 0)
            self.assertEqual(texture['Max'][3], 1)
        model['Prim'][0]['Min'][0] = 123456
        self.assertEqual(source, baseline)

    def test_missing_four_point_draw_is_rejected(self):
        with zipfile.ZipFile(SOURCE) as archive:
            scene = load_scene(archive)
        model = scene['Model'][scene['Object']['__floor00__']['Target']]
        model['Prim'][8]['Mesh'] = 'unknown_mesh'
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            candidate_scene(scene)

    def test_actual_packed_candidate_retains_all_protected_resources(self):
        # Run checkpoint1_floor.py --build first. Missing outputs must fail,
        # rather than silently skipping the only archive integration check.
        report = validate_pair(OUTPUT_DIR / SOURCE.name, OUTPUT_DIR / FLOOR_SOURCE.name)
        self.assertTrue(report['vertex_and_index_buffers_unchanged'])
        self.assertTrue(report['all_objects_baskets_collisions_lights_and_trees_unchanged'])
        self.assertEqual(report['retained_primitives'], 11)
        self.assertFalse(report['game_runtime_verified'])


if __name__ == '__main__':
    unittest.main()
