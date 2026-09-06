"""Small analytic polygon tests; deliberately never run full clip_domains."""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import revision5_paint_geometry as geometry


def signed_area(poly):
    p=np.asarray(poly,float)
    return float(sum(np.linalg.det(np.array([p[i],p[(i+1)%len(p)]])) for i in range(len(p)))/2)


def cross(a,b):
    return float(a[0]*b[1]-a[1]*b[0])


def inside_convex(point, polygon, tolerance=1e-9):
    sides=np.array([cross(polygon[(i+1)%len(polygon)]-polygon[i],point-polygon[i]) for i in range(len(polygon))])
    return bool(np.all(sides>=-tolerance) or np.all(sides<=tolerance))


def intersection_area(first, second):
    """Independent oracle: contained vertices plus segment intersections.

    This does not call the implementation's half-plane clipper or subtraction.
    For convex inputs the collected boundary points sort around their centroid.
    """
    a,b=np.asarray(first,float),np.asarray(second,float)
    if np.any(a.max(0)<=b.min(0)+1e-10) or np.any(b.max(0)<=a.min(0)+1e-10):
        return 0.
    points=[p for p in a if inside_convex(p,b)]+[p for p in b if inside_convex(p,a)]
    for i,p in enumerate(a):
        r=a[(i+1)%len(a)]-p
        for j,q in enumerate(b):
            s=b[(j+1)%len(b)]-q
            denominator=cross(r,s)
            if abs(denominator)<1e-12:
                continue
            t,u=cross(q-p,s)/denominator,cross(q-p,r)/denominator
            if -1e-10<=t<=1+1e-10 and -1e-10<=u<=1+1e-10:
                points.append(p+np.clip(t,0,1)*r)
    if len(points)<3:
        return 0.
    points=np.unique(np.round(points,11),axis=0)
    if len(points)<3:
        return 0.
    center=points.mean(0)
    angles=np.arctan2(points[:,1]-center[1],points[:,0]-center[0])
    return abs(signed_area(points[np.argsort(angles)]))


class ConvexDifferenceTests(unittest.TestCase):
    def assert_valid_difference(self,subject,cutter,expected_area):
        original_subject=subject.copy(); original_cutter=cutter.copy()
        pieces=geometry.subtract_triangle(subject,cutter)
        np.testing.assert_array_equal(subject,original_subject)
        np.testing.assert_array_equal(cutter,original_cutter)
        measured=0.
        for i,piece in enumerate(pieces):
            self.assertGreaterEqual(len(piece),3)
            self.assertTrue(np.isfinite(piece).all())
            value=signed_area(piece)
            self.assertGreater(value,0,'Difference output must remain CCW for signed area accumulation')
            measured+=value
            turn=np.array([cross(piece[(k+1)%len(piece)]-piece[k],
                                 piece[(k+2)%len(piece)]-piece[(k+1)%len(piece)]) for k in range(len(piece))])
            self.assertTrue(np.all(turn>=-1e-8),'Every output piece must be convex')
            self.assertTrue(all(inside_convex(v,subject,1e-8) for v in piece))
            self.assertLess(intersection_area(piece,cutter),1e-7)
            for other in pieces[:i]:
                self.assertLess(intersection_area(piece,other),1e-7,'Difference pieces must not overlap')
        self.assertAlmostEqual(measured,expected_area,delta=1e-7)
        self.assertAlmostEqual(measured+intersection_area(subject,cutter),abs(signed_area(subject)),delta=1e-7)
        return pieces

    def test_analytic_disjoint_tangent_containment_and_crossing_cases(self):
        square=np.array([[0.,0.],[4,0],[4,4],[0,4]])
        cases=[
            ('disjoint',[[0,5],[4,5],[0,9]],16.),
            ('single_vertex_touch',[[4,4],[6,4],[4,6]],16.),
            ('shared_edge_touch',[[4,0],[6,0],[4,4]],16.),
            ('interior_triangle',[[1,1],[3,1],[1,3]],14.),
            ('triangle_contains_subject',[[-2,-2],[12,-2],[-2,12]],0.),
            ('exact_half_square',[[0,0],[4,0],[0,4]],8.),
            ('partial_corner',[[-1,-1],[2,-1],[-1,2]],15.5),
            ('vertical_crossing',[[1,-10],[3,-10],[2,10]],12.8),
            ('horizontal_crossing',[[-10,1],[-10,3],[10,2]],12.8),
            ('diagonal_crossing',[[-1,-1],[5,5],[-1,5]],8.),
        ]
        for name,triangle,expected in cases:
            for subject_reversed in (False,True):
                for cutter_reversed in (False,True):
                    with self.subTest(case=name,subject_reversed=subject_reversed,cutter_reversed=cutter_reversed):
                        p=square[::-1] if subject_reversed else square
                        t=np.asarray(triangle,float)
                        if cutter_reversed:t=t[::-1]
                        self.assert_valid_difference(p,t,expected)

    def test_coincident_triangle_in_both_orientations_and_rotated_start(self):
        triangle=np.array([[0.,0.],[4,0],[0,4]])
        for reverse in (False,True):
            for start in range(3):
                cutter=np.roll(triangle[::-1] if reverse else triangle,start,axis=0)
                self.assertEqual(self.assert_valid_difference(triangle,cutter,0.),[])

    def test_rotations_translation_and_scale_preserve_analytic_area(self):
        square=np.array([[0.,0.],[4,0],[4,4],[0,4]])
        cutter=np.array([[1.,-10.],[3,-10],[2,10]])
        for angle in (math.pi/7,math.pi/2,5*math.pi/4):
            for scale in (.125,7.):
                with self.subTest(angle=angle,scale=scale):
                    matrix=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
                    p=square@matrix.T*scale+[213.25,-731.125]
                    t=cutter@matrix.T*scale+[213.25,-731.125]
                    self.assert_valid_difference(p,t,12.8*scale*scale)

    def test_zero_area_cutter_cannot_multiply_subject(self):
        square=np.array([[0.,0.],[4,0],[4,4],[0,4]])
        for cutter in (np.array([[1.,1.],[1,1],[1,1]]),np.array([[0.,0.],[2,2],[4,4]])):
            with self.subTest(cutter=cutter.tolist()):
                try:
                    pieces=geometry.subtract_triangle(square,cutter)
                except ValueError:
                    continue  # An explicit rejection is also a valid contract.
                self.assertAlmostEqual(sum(abs(signed_area(p)) for p in pieces),16.)
                for i,piece in enumerate(pieces):
                    for other in pieces[:i]:self.assertLess(intersection_area(piece,other),1e-7)

    def test_halfplane_area_complement_and_boundary_ownership(self):
        square=np.array([[0.,0.],[4,0],[4,4],[0,4]])
        # Oriented edge y direction, through x=1: left side is x<=1.
        first=geometry.halfplane(square,np.array([1.,0.]),np.array([0.,1.]))
        second=geometry.halfplane(square,np.array([1.,0.]),np.array([0.,1.]),inside=False)
        self.assertAlmostEqual(abs(signed_area(first)),4.)
        self.assertAlmostEqual(abs(signed_area(second)),12.)
        self.assertLess(intersection_area(first,second),1e-9)
        # Coincident edge retains the polygon once; zero-area complementary
        # boundary may disappear, but cannot become a finite area polygon.
        keep=geometry.halfplane(square,np.array([0.,0.]),np.array([1.,0.]))
        outside=geometry.halfplane(square,np.array([0.,0.]),np.array([1.,0.]),inside=False)
        self.assertAlmostEqual(abs(signed_area(keep)),16.)
        self.assertTrue(outside is None or abs(signed_area(outside))<1e-9)

    def test_adjacent_overlapping_and_repeated_cutters_remove_union_only(self):
        square=np.array([[0.,0.],[4,0],[4,4],[0,4]])
        # Two adjacent triangles form [1,3]^2; two more form [2,4]^2.
        # Their removed union has area 4+4-1=7, leaving 9 of the original 16.
        cutters=np.array([[[1,1],[3,1],[3,3]],[[1,1],[3,3],[1,3]],
                          [[2,2],[4,2],[4,4]],[[2,2],[4,4],[2,4]]],float)
        for order in (range(4),range(3,-1,-1)):
            pieces=[square]
            for i in list(order)+[0,0]:
                pieces=[remaining for piece in pieces for remaining in geometry.subtract_triangle(piece,cutters[i])]
            self.assertAlmostEqual(sum(signed_area(p) for p in pieces),9.,delta=1e-8)
            for i,piece in enumerate(pieces):
                for cutter in cutters:self.assertLess(intersection_area(piece,cutter),1e-8)
                for other in pieces[:i]:self.assertLess(intersection_area(piece,other),1e-8)

    def test_clean_removes_consecutive_duplicates_and_rejects_flat_polygon(self):
        polygon=np.array([[0.,0.],[0,4],[4,4],[4,0],[4,0],[0,0]])
        clean=geometry.clean(polygon)
        self.assertEqual(len(clean),4)
        self.assertAlmostEqual(signed_area(clean),16.)
        self.assertIsNone(geometry.clean([[0,0],[1,0],[2,0]]))


class MarkingClearanceTests(unittest.TestCase):
    def test_clearance_mask_shape_empty_input_and_original_candidate_index(self):
        empty=np.empty((0,3,2))
        for markings,invalid_mask in ((empty,[False]),(empty,np.empty((0,1))),
                                      (np.zeros((1,3,2)),[]),(np.zeros((1,3,2)),[[True]]),
                                      (np.zeros((1,3,2)),True)):
            with self.subTest(shape=markings.shape,mask_shape=np.shape(invalid_mask)):
                with self.assertRaisesRegex(ValueError,'clearance-mask'):
                    geometry.clip_domains(markings,clearance_cm=.25,clearance_mask=invalid_mask)
        square=np.array([[0.,0.],[4,0],[4,4],[0,4]])
        # Keep this a four-vertex synthetic domain, not a full-court clip.
        with patch.object(geometry,'domains',return_value=[('unit_square',square)]):
            reports,output=geometry.clip_domains(empty,clearance_cm=.25,clearance_mask=np.array([],bool))
            self.assertEqual(reports[0]['marking_triangle_candidates'],0)
            self.assertEqual(reports[0]['clipped_pairs'],0)
            self.assertAlmostEqual(sum(signed_area(p) for p in output[0]),16.)
            # ID 0 is outside the domain: candidate[0] is original marking ID
            # 1, so selecting ID 0 must not accidentally expand the inside one.
            markings=np.array([[[20.,20.],[22,20],[20,22]],[[1,1],[3,1],[1,3]]])
            for mask,expected in (([True,False],14.),([False,True],11.75)):
                reports,output=geometry.clip_domains(markings,clearance_cm=.25,clearance_mask=mask)
                self.assertEqual(reports[0]['marking_triangle_candidates'],1)
                self.assertAlmostEqual(sum(signed_area(p) for p in output[0]),expected)

    def test_square_minkowski_sum_analytic_area_and_bbox(self):
        triangle=np.array([[0.,0.],[4,0],[0,4]])
        for angle in (0.,math.pi/7,math.pi/2):
            rotation=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
            for clearance in (.000125,.125,2.):
                for reverse in (False,True):
                    with self.subTest(angle=angle,clearance=clearance,reverse=reverse):
                        original=triangle@rotation.T+[213.25,-731.125]
                        if reverse: original=original[::-1]
                        before=original.copy()
                        expanded=geometry.expand_triangle_square(original,clearance)
                        # Mixed area for any convex shape plus [-e,e]^2:
                        # A + 2e*(x span + y span) + 4e^2.
                        expected=8.+2*clearance*float(np.ptp(original,axis=0).sum())+4*clearance**2
                        self.assertAlmostEqual(signed_area(expanded),expected,delta=1e-8)
                        np.testing.assert_allclose(expanded.min(0),original.min(0)-clearance,atol=1e-10)
                        np.testing.assert_allclose(expanded.max(0),original.max(0)+clearance,atol=1e-10)
                        np.testing.assert_array_equal(original,before)

    def test_expansion_contains_triangle_and_all_square_translations(self):
        triangle=np.array([[-3.,-2.],[5,1],[.25,7.]])
        for clearance in (.000125,.25):
            expanded=geometry.expand_triangle_square(triangle,clearance)
            points=triangle[:,None]+clearance*np.array([[-1,-1],[-1,1],[1,-1],[1,1]])
            self.assertTrue(all(inside_convex(p,expanded,1e-9) for p in triangle))
            self.assertTrue(all(inside_convex(p,expanded,1e-9) for p in points.reshape(-1,2)))
            turns=[cross(expanded[(i+1)%len(expanded)]-expanded[i],
                         expanded[(i+2)%len(expanded)]-expanded[(i+1)%len(expanded)]) for i in range(len(expanded))]
            self.assertTrue(all(t>=-1e-10 for t in turns))
            self.assertGreater(signed_area(expanded),0)

    def test_zero_clearance_preserves_geometry_and_normalizes_winding(self):
        triangle=np.array([[0.,0.],[0,4],[4,0]])
        output=geometry.expand_triangle_square(triangle,0.)
        self.assertEqual(set(map(tuple,output)),set(map(tuple,triangle)))
        self.assertAlmostEqual(signed_area(output),8.)

    def test_degenerate_markings_remain_skipped(self):
        # Degenerate donor triangles are not visible markings to enlarge.
        for triangle in (np.array([[0.,0.],[0,0],[0,0]]),np.array([[0.,0.],[2,2],[4,4]])):
            for clearance in (0.,.000125,1.):
                self.assertIsNone(geometry.expand_triangle_square(triangle,clearance))

    def test_extremely_acute_triangle_cannot_create_long_miter(self):
        triangle=np.array([[0.,0.],[1000,0],[.000001,.0001]])
        clearance=.000125
        expanded=geometry.expand_triangle_square(triangle,clearance)
        self.assertIsNotNone(expanded)
        self.assertTrue(np.all(expanded.min(0)>=triangle.min(0)-clearance-1e-10))
        self.assertTrue(np.all(expanded.max(0)<=triangle.max(0)+clearance+1e-10))
        for vertex in expanded:
            distances=[]
            for i in range(3):
                p,q=triangle[i],triangle[(i+1)%3]
                t=np.clip(np.dot(vertex-p,q-p)/np.dot(q-p,q-p),0.,1.)
                distances.append(float(np.linalg.norm(vertex-(p+t*(q-p)))))
            self.assertLessEqual(min(distances),math.sqrt(2)*clearance+1e-10)
        expected=.05+2*clearance*(1000.+.0001)+4*clearance**2
        # clean() may remove a bevel whose distance from its chord is <1e-8
        # cm. This deliberately extreme 1000 cm / .0001 cm wedge triggers
        # that documented simplification (area change 1.25e-8 cm^2). Bound
        # its area by half the perimeter times that linear tolerance.
        perimeter=float(np.linalg.norm(np.roll(expanded,-1,axis=0)-expanded,axis=1).sum())
        self.assertAlmostEqual(signed_area(expanded),expected,delta=.5*perimeter*1e-8)

    def test_invalid_clearance_is_rejected(self):
        for clearance in (-1.,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                geometry.expand_triangle_square([[0,0],[4,0],[0,4]],clearance)


class DomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.domains=dict(geometry.domains())

    def test_five_domains_have_independent_standard_dimensions(self):
        self.assertEqual(set(self.domains),{'center_disk','paint_lane_-1','paint_semicircle_-1','paint_lane_1','paint_semicircle_1'})
        radius=182.88  # 6 feet; hard-coded independently of module constants.
        center=self.domains['center_disk']
        self.assertEqual(len(center),720)
        np.testing.assert_allclose(np.linalg.norm(center,axis=1),radius,atol=1e-9)
        np.testing.assert_allclose(center.min(0),[-radius,-radius],atol=1e-9)
        np.testing.assert_allclose(center.max(0),[radius,radius],atol=1e-9)
        for side in (-1,1):
            lane=self.domains[f'paint_lane_{side}']
            low,high=lane.min(0),lane.max(0)
            np.testing.assert_allclose([low[0],high[0]],[-243.84,243.84],atol=1e-9)
            np.testing.assert_allclose(sorted([low[1]*side,high[1]*side]),[855.98,1432.56],atol=1e-9)
            cap=self.domains[f'paint_semicircle_{side}']
            self.assertEqual(len(cap),361)
            np.testing.assert_allclose(np.linalg.norm(cap-[0,side*855.98],axis=1),radius,atol=1e-9)
            self.assertAlmostEqual(float((cap[:,1]*side).min()),673.10)
            self.assertAlmostEqual(float((cap[:,1]*side).max()),855.98)

    def test_analytic_regular_polygon_and_rectangle_areas(self):
        radius=182.88
        circle_polygon_area=720/2*radius*radius*math.sin(2*math.pi/720)
        lane_area=487.68*576.58
        for name,domain in self.domains.items():
            expected=circle_polygon_area if name=='center_disk' else (lane_area if 'lane' in name else circle_polygon_area/2)
            self.assertAlmostEqual(signed_area(domain),expected,delta=1e-6)
            edges=np.roll(domain,-1,axis=0)-domain
            turns=edges[:,0]*np.roll(edges,-1,axis=0)[:,1]-edges[:,1]*np.roll(edges,-1,axis=0)[:,0]
            self.assertTrue(np.all(turns>=-1e-8))
        self.assertLess((math.pi*radius**2-circle_polygon_area)/(math.pi*radius**2),1.3e-5)

    def test_all_five_interiors_disjoint_and_caps_face_midcourt(self):
        entries=list(self.domains.items())
        for i,(name,domain) in enumerate(entries):
            for other_name,other in entries[:i]:
                with self.subTest(first=name,second=other_name):
                    self.assertLess(intersection_area(domain,other),1e-8)
        for side in (-1,1):
            cap=self.domains[f'paint_semicircle_{side}']
            lane=self.domains[f'paint_lane_{side}']
            # Shared diameter/rectangle edge is allowed, positive-area overlap
            # and a semicircle pointing back into the rectangle are not.
            self.assertTrue(np.all(cap[:,1]*side<=855.98+1e-9))
            self.assertTrue(np.all(lane[:,1]*side>=855.98-1e-9))


if __name__=='__main__':
    unittest.main()
