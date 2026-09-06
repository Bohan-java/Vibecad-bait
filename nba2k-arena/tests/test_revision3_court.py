"""Mathematical court checks plus real donor buffer/lightmap preservation."""
from __future__ import annotations

import copy
import io
import math
from pathlib import Path
import sys
import unittest
import zipfile

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import revision3_court as court
from revision_textures import make_dds
from scene_primitives import iter_primitives


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.features, cls.geometry = court.court_geometry()
        cls.by_name = {f['name']: (f, g) for f, g in zip(cls.features, cls.geometry)}

    def test_complete_center_and_no_old_or_duplicate_lane_geometry(self):
        self.assertEqual(len(self.by_name), len(self.features))
        self.assertFalse(any('four_point' in name or 'inner_lane' in name for name in self.by_name))
        _, divider = self.by_name['division_line']
        p = divider.reshape(-1, 3)
        self.assertEqual(p[:, 0].min(), -762)
        self.assertEqual(p[:, 0].max(), 762)
        self.assertAlmostEqual(np.ptp(p[:, 2]), 5.08)
        for name, expected_inner, expected_outer in (('center_outer_circle', 177.8, 182.88),
                                                     ('center_inner_circle', 60.96, 66.04)):
            feature, geometry = self.by_name[name]
            points = geometry.reshape(-1, 3)[:, [0, 2]]
            radius = np.linalg.norm(points, axis=1)
            self.assertAlmostEqual(radius.min(), expected_inner)
            self.assertAlmostEqual(radius.max(), expected_outer)
            angles = np.unique(np.round(np.mod(np.arctan2(points[:, 1], points[:, 0]), math.tau), 8))
            gaps = np.diff(np.r_[angles, angles[0] + math.tau])
            self.assertLess(gaps.max(), math.radians(.501))
            self.assertEqual(feature['angle_radians'], [0, math.tau])

    def test_exact_inside_boundary_and_outside_lane_dimensions(self):
        for side in (-1, 1):
            _, sideline = self.by_name[f'boundary_sideline_{side}']
            x = np.abs(sideline[:, :, 0])
            self.assertAlmostEqual(x.min(), 762)
            self.assertAlmostEqual(x.max(), 767.08)
            _, baseline = self.by_name[f'boundary_baseline_{side}']
            z = np.abs(baseline[:, :, 2])
            self.assertAlmostEqual(z.min(), 1432.56)
            self.assertAlmostEqual(z.max(), 1437.64)
            for lane_side in (-1, 1):
                _, lane = self.by_name[f'end_{side}_lane_side_{lane_side}']
                x = np.abs(lane[:, :, 0])
                self.assertAlmostEqual(x.min(), 238.76)
                self.assertAlmostEqual(x.max(), 243.84)
            _, ft = self.by_name[f'end_{side}_free_throw_line']
            inward = 1432.56 - side * ft[:, :, 2]
            self.assertAlmostEqual(inward.min(), 574.04)
            self.assertAlmostEqual(inward.max(), 579.12)

    def test_three_point_edges_meet_corners_without_seams(self):
        for end in (-1, 1):
            feature, arc = self.by_name[f'end_{end}_three_point_arc']
            p = arc.reshape(-1, 3)
            d = court.HALF_LENGTH - end * p[:, 2]
            radius = np.hypot(p[:, 0], d - court.RIM_FROM_BASELINE)
            self.assertAlmostEqual(radius.min(), 718.82)
            self.assertAlmostEqual(radius.max(), 723.9)
            self.assertAlmostEqual(np.max(np.abs(p[:, 0])), 670.56)
            for side in (-1, 1):
                _, corner = self.by_name[f'end_{end}_three_point_corner_{side}']
                cp = np.unique(corner.reshape(-1, 3), axis=0)
                endpoints = cp[np.abs(cp[:, 2]) < court.HALF_LENGTH - .001]
                self.assertEqual(len(endpoints), 2)
                for endpoint in endpoints:
                    self.assertLess(np.linalg.norm(p - endpoint, axis=1).min(), 1e-9)
                self.assertAlmostEqual(np.abs(cp[:, 0]).max() - np.abs(cp[:, 0]).min(), 5.08)

    def test_restricted_area_radius_and_legs_to_backboard(self):
        for end in (-1, 1):
            feature, arc = self.by_name[f'end_{end}_restricted_arc']
            self.assertAlmostEqual(feature['inner_radius_cm'], 121.92)
            self.assertAlmostEqual(feature['outer_radius_cm'], 127)
            for side in (-1, 1):
                _, leg = self.by_name[f'end_{end}_restricted_leg_{side}']
                inward = court.HALF_LENGTH - end * leg[:, :, 2]
                self.assertAlmostEqual(inward.min(), 121.92)
                self.assertAlmostEqual(inward.max(), 160.02)

    def test_winding_widths_finite_and_enclosed_by_donor_apron(self):
        for feature, triangles in zip(self.features, self.geometry):
            with self.subTest(feature=feature['name']):
                cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
                self.assertTrue(np.all(cross[:, 1] > 0))
                self.assertTrue(np.all(np.isfinite(triangles)))
                self.assertEqual(float(np.max(np.abs(triangles[:, :, 1]))), 0)
                self.assertLess(np.max(np.abs(triangles[:, :, 0])), 975.360352)
                self.assertLess(np.max(np.abs(triangles[:, :, 2])), 1889.76001)
                self.assertAlmostEqual(feature['line_width_cm'], 30.48 if feature.get('neutral_zone_exception') else 5.08)
        dashed = [f for f in self.features if f.get('dashed')]
        self.assertEqual(len(dashed), 12)

    def test_piecewise_uv_interpolation_and_outside_rejection(self):
        # Two adjacent triangles deliberately have a non-affine UV field so a
        # global fit cannot accidentally satisfy the per-triangle requirement.
        pos = np.array([[0, 0, 0], [2, 0, 0], [0, 0, 2], [2, 0, 2]], float)
        ids = np.array([0, 2, 1, 1, 2, 3])
        uv = {'TEXCOORD1': np.array([[0, 0], [1, 0], [0, 1], [.8, .6]])}
        result = court.interpolate_floor_uvs(np.array([[.5, .5], [1.5, 1.5]]), pos, ids, uv)
        np.testing.assert_allclose(result['TEXCOORD1'], [[.25, .25], [.65, .55]])
        with self.assertRaisesRegex(ValueError, 'outside donor base'):
            court.interpolate_floor_uvs(np.array([[3, 3]]), pos, ids, uv)


class DonorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(ROOT / 'output/revision2/arena_700_int.iff') as archive:
            cls.before = court._fragment(archive.read('level.SCNE'))['level']
        cls.after = copy.deepcopy(cls.before)
        cls.extra = {}
        with zipfile.ZipFile(ROOT / 'donor/original/arena_020_int_original.iff') as archive:
            cls.report = court.apply_court(cls.after, archive, cls.extra)

    def test_base_vertices_indices_anchors_bounds_and_scene_scope(self):
        report = self.report
        self.assertTrue(report['old_vertex_prefix_byte_identical'])
        self.assertTrue(report['base_indices_byte_identical'])
        self.assertTrue(report['protected_model_bounds_unchanged'])
        self.assertEqual(report['units_verification']['backboard_anchor_z_cm'], [-1310.64001, 1310.64001])
        self.assertAlmostEqual(report['units_verification']['net_pivot_forward_cm'], 38.1, places=4)
        restored = copy.deepcopy(self.after)
        restored['Model'][report['model']] = copy.deepcopy(self.before['Model'][report['model']])
        for section in ('Material', 'Texture'):
            for key in list(restored[section]):
                if key not in self.before[section]:
                    del restored[section][key]
        self.assertEqual(restored, self.before)
        self.assertFalse(report['game_runtime_verified'])
        self.assertFalse(report['game_scoring_logic_modified'])

    def test_actual_buffers_indices_normals_and_uv1(self):
        model = self.after['Model'][self.report['model']]
        vb = self.extra[model['VertexStream'][0]['Binary']]
        ib = np.frombuffer(self.extra[model['IndexBuffer']['Binary']], '<u2')
        n = len(vb) // 28
        prims = list(iter_primitives(model, indices=ib, vertex_count=n))
        self.assertLess(n, 65536)
        self.assertEqual(prims[0]['Count'], 2010)
        self.assertEqual(prims[0]['Mesh'], 'NBA_full_court_floor_low1Shape')
        self.assertEqual(len(prims), 74)
        self.assertFalse(any('four_point' in p['Mesh'] for p in prims))
        pos = np.ndarray((n, 3), '<f4', vb, strides=(28, 4))
        tri = pos[ib[2010:]].reshape(-1, 3, 3)
        self.assertTrue(np.all(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])[:, 1] > 0))
        self.assertLess(self.report['uv1_max_quantization_error'], 8e-6)
        uv1 = np.ndarray((n, 2), '<i2', vb, offset=16, strides=(28, 2))
        self.assertGreater(np.ptp(uv1[3231:, 0].astype(float)), 40000)
        self.assertGreater(np.ptp(uv1[3231:, 1].astype(float)), 40000)

    def test_white_texture_is_fully_white_opaque_and_self_contained(self):
        mat = self.after['Material'][court.WHITE_MATERIAL]
        texture = self.after['Texture'][mat['Resource']['DetailAlbedoTexture']['Pixelmap']]
        raw = self.extra[texture['Binary']]
        im = Image.open(io.BytesIO(make_dds(raw[32:], 4, 4, 'BC1_UNORM'))).convert('RGBA')
        self.assertEqual(np.unique(np.asarray(im).reshape(-1, 4), axis=0).tolist(), [[255, 255, 255, 255]])

    def test_deterministic_construction(self):
        other = copy.deepcopy(self.before)
        extra = {}
        with zipfile.ZipFile(ROOT / 'donor/original/arena_020_int_original.iff') as archive:
            report = court.apply_court(other, archive, extra)
        self.assertEqual(other, self.after)
        self.assertEqual(extra, self.extra)
        self.assertEqual(report, self.report)


if __name__ == '__main__':
    unittest.main()
