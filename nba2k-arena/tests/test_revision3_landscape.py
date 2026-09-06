"""Geometry checks that catch invisible surfaces and export damage."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from revision3_landscape import Mesh, palm_geometry, bleachers, M


class LandscapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.palm=palm_geometry(0)

    def test_trunk_front_faces_point_outward(self):
        faces=np.asarray(self.palm.parts[M('bark')]);ns=np.asarray(self.palm.normals[M('bark')])
        geometric=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0])
        geometric/=np.linalg.norm(geometric,axis=1)[:,None]
        self.assertGreater(float((geometric*ns.mean(1)).sum(1).min()),.98)

    def test_each_palm_fits_native_u16_model_and_has_no_uv_collapse(self):
        calls=[]
        def fake_export(level,extra,name,parts,**kwargs):
            count=sum(len(v) for v in parts.values())
            self.assertLess(count*3,65536)
            calls.append(count)
            return {'model':name}
        with patch('revision3_landscape.export_mesh',side_effect=fake_export):
            self.palm.export_sections({}, {}, 'palm')
        self.assertEqual(sum(calls),sum(len(v) for v in self.palm.parts.values()))
        self.assertGreater(len(calls),1)
        for mat,uv in self.palm.uv.items():
            uv=np.asarray(uv);a,b=uv[:,1]-uv[:,0],uv[:,2]-uv[:,0]
            determinant=a[:,0]*b[:,1]-a[:,1]*b[:,0]
            self.assertTrue(np.all(np.abs(determinant)>1e-9),mat)

    def test_leaf_front_and_back_geometry_have_consistent_normals(self):
        for mat in ('leaf','leaf_light','leaf_dead'):
            faces=np.asarray(self.palm.parts[M(mat)]);ns=np.asarray(self.palm.normals[M(mat)])
            cross=np.cross(faces[:,1]-faces[:,0],faces[:,2]-faces[:,0]);cross/=np.linalg.norm(cross,axis=1)[:,None]
            mean=ns.mean(1);mean/=np.linalg.norm(mean,axis=1)[:,None]
            self.assertTrue(np.all((cross*mean).sum(1)>.98),mat)

    def test_new_terrace_planes_face_up(self):
        mesh=Mesh();mesh.plane('grass',10,50,-60,30,25)
        t=np.asarray(mesh.parts[M('grass')]);self.assertTrue(np.all(np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0])[:,1]>0))

    def test_metal_bleacher_is_low_and_open(self):
        mesh=bleachers();points=np.concatenate(list(mesh.parts.values())).reshape(-1,3)
        self.assertLess(points[:,1].max(),300)
        self.assertGreater(points[:,2].ptp() if hasattr(points[:,2],'ptp') else np.ptp(points[:,2]),1000)
        self.assertLess(sum(len(v) for v in mesh.parts.values())*3,65536)


if __name__=='__main__':unittest.main()
