"""Prevent invisible donor meshes from becoming false preview obstacles."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from revision3_preview import all_index_triangles_degenerate


class PreviewVisibilityTests(unittest.TestCase):
    def test_repeated_vertex_proves_zero_area_without_positions(self):
        model = {'Prim': [{'Start': 0, 'Count': 6, 'LodList': [{'Start': 6, 'Count': 3}]}]}
        self.assertTrue(all_index_triangles_degenerate(model, np.array([0, 0, 8, 3, 4, 4, 9, 9, 9])))

    def test_a_visible_lower_lod_prevents_hidden_classification(self):
        model = {'Prim': [{'Start': 0, 'Count': 3, 'LodList': [{'Start': 3, 'Count': 3}]}]}
        self.assertFalse(all_index_triangles_degenerate(model, np.array([0, 0, 0, 0, 1, 2])))

    def test_omitted_start_continues_and_preserves_visible_geometry(self):
        model = {'Prim': [{'Start': 3, 'Count': 3}, {'Count': 3}]}
        self.assertFalse(all_index_triangles_degenerate(model, np.array([0, 0, 0, 1, 1, 1, 0, 1, 2])))

    def test_missing_or_invalid_data_is_not_evidence_of_hiding(self):
        self.assertFalse(all_index_triangles_degenerate({'Prim': []}, np.array([], dtype=int)))
        with self.assertRaisesRegex(ValueError, 'Invalid primitive/LOD'):
            all_index_triangles_degenerate({'Prim': [{'Count': 3, 'LodList': [{'Start': 30, 'Count': 3}]}]}, np.array([0, 0, 0]))
        # Distinct indices may or may not be geometrically collinear. Do not guess.
        self.assertFalse(all_index_triangles_degenerate({'Prim': [{'Count': 3}]}, np.array([0, 1, 2])))


if __name__ == '__main__':
    unittest.main(verbosity=2)
