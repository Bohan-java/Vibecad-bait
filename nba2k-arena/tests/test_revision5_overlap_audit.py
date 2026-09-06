"""Independent overlap-audit checks using analytic and small synthetic inputs.

No scene builder, geometry clipper, or full-court audit is run by these tests.
"""
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from revision5_overlap_audit import audit_overlap, triangle_intersection_areas


class TriangleOracleTests(unittest.TestCase):
    def test_analytic_cases_all_windings_and_start_indices(self):
        a = np.array([[0., 0.], [4, 0], [0, 4]])
        cases = [
            ('identical', a, 8.),
            ('contained', [[1, 1], [2, 1], [1, 2]], .5),
            ('disjoint', [[5, 0], [9, 0], [5, 4]], 0.),
            ('vertex_touch', [[4, 0], [8, 0], [4, 4]], 0.),
            ('diagonal_edge_touch', [[0, 4], [4, 4], [4, 0]], 0.),
            ('collinear_edge_partial_overlap', [[2, 0], [6, 0], [2, 4]], 2.),
            ('partial_crossing', [[0, 3], [3, 0], [3, 3]], 2.5),
            ('zero_area', [[0, 0], [2, 2], [4, 4]], 0.),
            ('repeated_point', [[1, 1], [1, 1], [1, 1]], 0.),
        ]
        for name, b, expected in cases:
            for reverse_a in (False, True):
                for reverse_b in (False, True):
                    for start in range(3):
                        with self.subTest(case=name, reverse_a=reverse_a, reverse_b=reverse_b, start=start):
                            p = a[::-1] if reverse_a else a
                            q = np.asarray(b, float)
                            q = np.roll(q[::-1] if reverse_b else q, start, axis=0)
                            values = triangle_intersection_areas(np.array([p, q]), np.array([q, p]))
                            np.testing.assert_allclose(values, expected, atol=1e-12, rtol=1e-12)

    def test_six_edge_intersections_without_any_contained_vertex(self):
        # Star of David: central hexagon is 4*4 minus four 1*2/2 corners.
        a = np.array([[0., 0.], [6, 0], [3, 6]])
        b = np.array([[0., 4.], [6, 4], [3, -2]])
        for angle in (0., math.pi/7, math.pi/2):
            matrix = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
            for scale in (.125, 7.):
                p = (a@matrix.T*scale+[1432.56, -855.98])[None]
                q = (b@matrix.T*scale+[1432.56, -855.98])[None]
                self.assertAlmostEqual(triangle_intersection_areas(p, q)[0], 12.*scale**2, delta=1e-8)

    def test_actual_float32_one_ulp_sliver_is_detected(self):
        # Thin but long overlap, intentionally above the strict area threshold.
        x = np.float32(1500.)
        delta = float(np.spacing(x))
        a = np.array([[[x-4, 0], [x, 0], [x, 4]]], dtype=np.float32)
        b = np.array([[[x-delta, 0], [x+4, 0], [x-delta, 4]]], dtype=np.float32)
        # Integrate min(s+4, 4*(4-s)/(4+delta)) over s=[-delta,0].
        # The upper edges switch at s=-4*delta/(8+delta).
        expected = 4.*delta - delta**2/2 - 8.*delta**2/((8.+delta)*(4.+delta))
        value = triangle_intersection_areas(a, b)[0]
        self.assertAlmostEqual(value, expected, delta=1e-12)
        report = audit_overlap(a, b)
        self.assertEqual(report['over_threshold_pair_count'], 1)
        self.assertFalse(report['all_pairs_below_threshold'])
        self.assertAlmostEqual(report['max_coordinate_float32_ulp_cm'], delta)

    def test_zero_and_empty_pairs(self):
        empty = np.empty((0, 3, 2))
        self.assertEqual(triangle_intersection_areas(empty, empty).shape, (0,))
        degenerate = np.zeros((3, 3, 2))
        np.testing.assert_array_equal(triangle_intersection_areas(degenerate, degenerate), 0.)


class SpatialAuditTests(unittest.TestCase):
    def test_exact_original_marking_ids_survive_grid_filtering_and_batches(self):
        triangle=np.array([[0.,0.],[4,0],[0,4]])
        paint=np.array([triangle,triangle+[128,0],triangle+[128,0]])
        marks=np.array([triangle+[256,0],triangle+[128,0],
                        [[1,1],[2,1],[1,2]],triangle+[4,0],triangle])
        for cell in (1.,64.,512.):
            for batch in (1,4):
                with self.subTest(cell=cell,batch=batch):
                    result=audit_overlap(paint,marks,area_threshold_cm2=.5,
                                         grid_cell_cm=cell,batch_size=batch)
                    # Original IDs 1 and 4 overlap. ID 2 has exactly the area
                    # threshold, ID 3 only touches, ID 0 is spatially rejected.
                    # Repeating paint[1] increases pair count, not unique IDs.
                    self.assertEqual(result['marking_triangles_over_threshold'],[1,4])
                    self.assertEqual(result['over_threshold_pair_count'],3)
                    self.assertEqual(result['worst_pair']['marking_triangle'],4)
                    self.assertTrue(all(type(index) is int for index in result['marking_triangles_over_threshold']))

    def test_metrics_threshold_and_pair_sum_semantics(self):
        paint = np.array([[[0., 0.], [4, 0], [0, 4]], [[10, 10], [11, 10], [10, 11]]])
        marks = np.array([paint[0], paint[0], [[1, 1], [2, 1], [1, 2]]])
        saved_paint, saved_marks = paint.copy(), marks.copy()
        report = audit_overlap(paint, marks, area_threshold_cm2=.5, batch_size=1)
        self.assertEqual(report['max_overlap_area_cm2'], 8.)
        self.assertEqual(report['total_overlap_area_cm2'], 16.5)
        self.assertEqual(report['over_threshold_pair_count'], 2)
        self.assertEqual(report['paint_triangles_over_threshold_count'], 1)
        self.assertEqual(report['worst_pair'], {
            'paint_triangle': 0, 'marking_triangle': 0, 'overlap_area_cm2': 8.,
            'paint_triangle_xz_cm': paint[0].tolist(), 'marking_triangle_xz_cm': marks[0].tolist()})
        self.assertEqual(report['bbox_candidate_pairs_audited'], 3)
        self.assertIn('not_union', report['total_area_semantics'])
        json.dumps(report, allow_nan=False)
        np.testing.assert_array_equal(paint, saved_paint)
        np.testing.assert_array_equal(marks, saved_marks)

    def test_small_grid_matches_all_pairs_and_batch_sizes(self):
        rng = np.random.default_rng(527)
        paint = rng.uniform(-100, 100, (48, 3, 2)).astype(np.float32)
        marks = rng.uniform(-100, 100, (31, 3, 2)).astype(np.float32)
        pairs = triangle_intersection_areas(np.repeat(paint, len(marks), axis=0),
                                            np.tile(marks, (len(paint), 1, 1)))
        expected_paint_count = int((pairs.reshape(len(paint), len(marks)) > 1e-5).any(1).sum())
        for cell in (7., 64., 999.):
            for batch in (7, 101):
                with self.subTest(cell=cell, batch=batch):
                    report = audit_overlap(paint, marks, grid_cell_cm=cell, batch_size=batch)
                    self.assertAlmostEqual(report['max_overlap_area_cm2'], float(pairs.max()), delta=1e-9)
                    self.assertAlmostEqual(report['total_overlap_area_cm2'], float(pairs.sum()), delta=1e-7)
                    self.assertEqual(report['over_threshold_pair_count'], int((pairs > 1e-5).sum()))
                    self.assertEqual(report['paint_triangles_over_threshold_count'], expected_paint_count)

    def test_sparse_index_does_not_audit_cartesian_product(self):
        count = 384
        offsets = np.column_stack((np.arange(count)*128., np.zeros(count)))
        paint = np.array([[0., 0.], [4, 0], [0, 4]])[None]+offsets[:, None]
        marks = paint+[2., 0.]
        report = audit_overlap(paint, marks)
        self.assertEqual(report['bbox_candidate_pairs_audited'], count)
        self.assertEqual(report['full_cartesian_pair_count'], count**2)
        self.assertEqual(report['over_threshold_pair_count'], count)
        self.assertAlmostEqual(report['total_overlap_area_cm2'], 2.*count)

    def test_oversized_mark_and_paint_use_complete_fallback(self):
        large = [[-200., -200.], [200, -200], [0, 200]]
        small = [[-1., -1.], [1, -1], [0, 1]]
        paint = np.array([small, large])
        marks = np.array([large, small])
        report = audit_overlap(paint, marks, grid_cell_cm=1.)
        self.assertEqual(report['oversized_marking_triangles'], 1)
        self.assertEqual(report['bbox_candidate_pairs_audited'], 4)
        self.assertEqual(report['total_overlap_area_cm2'], 80006.)

    def test_empty_and_bbox_touch_are_valid_json_zero_reports(self):
        empty = np.empty((0, 3, 2))
        triangle = np.array([[[0., 0.], [4, 0], [0, 4]]])
        for paint, marks in ((empty, empty), (empty, triangle), (triangle, empty), (triangle, triangle+[4, 0])):
            report = audit_overlap(paint, marks)
            self.assertEqual(report['total_overlap_area_cm2'], 0.)
            self.assertEqual(report['bbox_candidate_pairs_audited'], 0)
            self.assertIsNone(report['worst_pair'])
            self.assertTrue(report['all_pairs_below_threshold'])
            json.dumps(report, allow_nan=False)

    def test_invalid_inputs_rejected(self):
        valid = np.zeros((1, 3, 2))
        for invalid in (np.zeros((3, 2)), np.zeros((1, 4, 2)), np.full((1, 3, 2), np.nan),
                        np.full((1, 3, 2), np.inf)):
            with self.assertRaises(ValueError): audit_overlap(invalid, valid)
            with self.assertRaises(ValueError): triangle_intersection_areas(invalid, valid)
        for argument in ({'area_threshold_cm2': -1}, {'area_threshold_cm2': math.inf},
                         {'grid_cell_cm': 0}, {'grid_cell_cm': math.nan},
                         {'batch_size': 0}, {'batch_size': True}, {'batch_size': 2.5}):
            with self.assertRaises(ValueError): audit_overlap(valid, valid, **argument)

    def test_finite_float32_extreme_does_not_overflow_grid_or_json(self):
        limit = float(np.finfo(np.float32).max)
        triangle = np.array([[[limit, 0], [limit/2, 0], [limit, limit/2]]])
        report = audit_overlap(triangle, triangle)
        self.assertEqual(report['oversized_marking_triangles'], 1)
        self.assertAlmostEqual(report['max_overlap_area_cm2']/(limit**2/8), 1.)
        self.assertTrue(math.isfinite(report['max_coordinate_float32_ulp_cm']))
        json.dumps(report, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
