"""One continuous beach court landscape, composed from all five references.

Units are centimetres. All added scenery lies outside the preserved playable
court. Fan palms are closed, explicitly double-sided leaf geometry, not alpha
cards or a photograph pasted over an indoor wall. This module generates native
geometry; it does not install any software or touch a game directory.
"""
from __future__ import annotations

from collections import defaultdict
import math
import numpy as np
from revision3_mesh import export_mesh, make_unbaked_material

IDENTITY = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
M = lambda name: 'venice_v3:' + name


class Mesh:
    def __init__(self):
        self.parts, self.uv, self.normals = (defaultdict(list) for _ in range(3))

    def tri(self, material, points, uv=None, normals=None):
        p = np.asarray(points, dtype=float)
        n = np.cross(p[1] - p[0], p[2] - p[0])
        if np.linalg.norm(n) < 1e-7:
            return
        n /= np.linalg.norm(n)
        if uv is None:
            axis = int(np.argmax(np.abs(n)))
            uv = np.delete(p, axis, axis=1) / 200.
        self.parts[M(material)].append(p)
        self.uv[M(material)].append(np.asarray(uv, dtype=float))
        self.normals[M(material)].append(np.tile(n, (3, 1)) if normals is None else np.asarray(normals))

    def quad(self, material, points, uv=None, normals=None, double=False):
        p = np.asarray(points)
        uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1.]]) if uv is None else np.asarray(uv)
        for ids in ([0, 1, 2], [0, 2, 3]):
            ns = None if normals is None else np.asarray(normals)[ids]
            self.tri(material, p[ids], uv[ids], ns)
            if double:
                ri = ids[::-1]
                self.tri(material, p[ri], uv[ri], None if normals is None else -np.asarray(normals)[ri])

    def plane(self, material, x0, x1, z0, z1, y=0., tile=200.):
        p = np.array([[x0,y,z0], [x0,y,z1], [x1,y,z1], [x1,y,z0]])
        self.quad(material, p, p[:, [0,2]]/tile)

    def box(self, material, center, size, bevel=0., tile=200.):
        x, y, z = center
        w, h, d = np.asarray(size)/2
        b = min(bevel, w/2, d/2, h/2)
        # Bevelled plan corners remove razor-sharp concrete/metal silhouettes.
        outline = np.array([[-w+b,-d], [w-b,-d], [w,-d+b], [w,d-b],
                            [w-b,d], [-w+b,d], [-w,d-b], [-w,-d+b]]) if b else np.array([[-w,-d], [w,-d], [w,d], [-w,d]])
        bottom = np.column_stack((outline[:,0]+x, np.full(len(outline), y-h), outline[:,1]+z))
        top = bottom.copy(); top[:,1] = y+h
        for i in range(len(outline)):
            j = (i+1)%len(outline)
            self.quad(material, [bottom[i], top[i], top[j], bottom[j]],
                      [[0,0], [0,2*h/tile], [np.linalg.norm(outline[j]-outline[i])/tile,2*h/tile], [np.linalg.norm(outline[j]-outline[i])/tile,0]])
            self.tri(material, [[x,y+h,z],top[j],top[i]], np.array([[x,z],outline[j]+[x,z],outline[i]+[x,z]])/tile)
            self.tri(material, [[x,y-h,z],bottom[i],bottom[j]])

    def tube(self, material, start, end, radius, radius_end=None, sides=20, caps=True):
        a, b = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
        axis = b-a; length = np.linalg.norm(axis); axis /= length
        reference = np.eye(3)[np.argmin(np.abs(axis))]
        u = np.cross(axis, reference); u /= np.linalg.norm(u)
        v = np.cross(axis, u)
        radius_end = radius if radius_end is None else radius_end
        angles = np.linspace(0, 2*np.pi, sides+1)
        radial = np.cos(angles)[:,None]*u + np.sin(angles)[:,None]*v
        ring0, ring1 = a + radial*radius, b + radial*radius_end
        for i in range(sides):
            n0, n1 = radial[i], radial[i+1]
            # UVs continue around the circumference and along the pole.
            self.quad(material, [ring0[i],ring0[i+1],ring1[i+1],ring1[i]],
                      [[i/sides,0],[(i+1)/sides,0],[(i+1)/sides,length/200],[i/sides,length/200]],
                      [n0,n1,n1,n0])
            if caps:
                self.tri(material, [a,ring0[i+1],ring0[i]])
                self.tri(material, [b,ring1[i],ring1[i+1]])

    def export(self, level, extra, name):
        return export_mesh(level, extra, M(name), self.parts,
                           uv_parts=self.uv, normal_parts=self.normals)

    def export_sections(self, level, extra, name, face_limit=20000):
        """Preserve dense foliage by partitioning native R16 draw models."""
        reports=[];section=Mesh();count=0
        for material,faces in self.parts.items():
            cursor=0
            while cursor<len(faces):
                take=min(face_limit-count,len(faces)-cursor)
                for src,dst in ((self.parts,section.parts),(self.uv,section.uv),(self.normals,section.normals)):
                    dst[material].extend(src[material][cursor:cursor+take])
                count+=take;cursor+=take
                if count==face_limit:
                    reports.append(section.export(level,extra,f'{name}_section_{len(reports)}'))
                    section=Mesh();count=0
        if count:reports.append(section.export(level,extra,f'{name}_section_{len(reports)}'))
        return reports


def palm_geometry(variant=0):
    """Cylindrical smooth trunk, ribbed fan leaves and a restrained dry skirt."""
    rng = np.random.default_rng(7330+variant)
    mesh = Mesh()
    height = [1120., 1370., 960., 1240.][variant]
    lean = np.array([[48.,-23.],[-37.,25.],[25.,33.],[-22.,-48.]][variant])
    sides, segments = 48, 48
    rings, normals = [], []
    for j in range(segments+1):
        t=j/segments; angle=np.linspace(0,2*np.pi,sides+1)
        r = 18.5-4*t + 7*np.exp(-t*18) + 1.1*np.sin(t*height/14*2*np.pi)
        center = lean*t*t
        radial = np.column_stack((np.cos(angle), np.zeros(sides+1), np.sin(angle)))
        p = radial*r+[center[0],height*t,center[1]]
        n=radial.copy(); n[:,1]=-(2*t*(radial[:,0]*lean[0]+radial[:,2]*lean[1])-4)/height
        n/=np.linalg.norm(n,axis=1)[:,None]
        rings.append(p); normals.append(n)
    for j in range(segments):
        for i in range(sides):
            mesh.quad('bark',[rings[j][i],rings[j+1][i],rings[j+1][i+1],rings[j][i+1]],
                      [[i/sides,j/segments*height/400],[i/sides,(j+1)/segments*height/400],[(i+1)/sides,(j+1)/segments*height/400],[(i+1)/sides,j/segments*height/400]],
                      [normals[j][i],normals[j+1][i],normals[j+1][i+1],normals[j][i+1]])
    apex=np.array([lean[0],height,lean[1]])
    fronds=60
    for k in range(fronds):
        azimuth = k*2.399963229728653 + rng.uniform(-.13,.13)
        # Continuous elevations avoid four visibly separate umbrella tiers.
        maturity=k/(fronds-1)
        elevation=1.22-2.38*maturity+rng.uniform(-.23,.23)
        outward=np.array([math.cos(azimuth),0.,math.sin(azimuth)])
        lateral=np.array([-math.sin(azimuth),0.,math.cos(azimuth)])
        forward=outward*math.cos(elevation)+[0,math.sin(elevation),0]
        blade_normal=np.cross(lateral, forward); blade_normal/=np.linalg.norm(blade_normal)
        # Wind twists individual fan planes around their petioles. Keeping all
        # transverse axes horizontal produces an artificial stack of disks.
        roll=rng.uniform(-.9,.9)
        lateral=lateral*math.cos(roll)+blade_normal*math.sin(roll)
        blade_normal=np.cross(lateral,forward);blade_normal/=np.linalg.norm(blade_normal)
        root=apex+[0,-maturity*60.+rng.uniform(-12,12),0]
        petiole=74+rng.uniform(-13,20)
        fan_root=root+forward*petiole
        mesh.tube('leaf_light' if maturity<.3 else 'leaf',root,fan_root,2.4,.9,sides=8)
        length=106+rng.uniform(-19,17); spread=1.16+rng.uniform(-.16,.13)
        rays=28; depth=6
        # Each folded segment has a fine separated tip; the fan base is joined.
        for ray in range(rays):
            a0=-spread+2*spread*ray/rays
            a1=-spread+2*spread*(ray+1)/rays
            segment_length=length*(.89+.11*np.cos((a0+a1)/2/spread*np.pi/2)+rng.uniform(-.07,.07))
            # Alternate pleats, subtle edge droop, no intersecting alpha planes.
            grid=[]
            for d in range(depth+1):
                t=.025+.975*d/depth
                pair=[]
                for e,original_angle in enumerate((a0,a1)):
                    # Mature palmate leaves split deeply into narrow folded
                    # segments. The connected base stops at 40% of the radius;
                    # tapered, separated tips produce a feathery silhouette.
                    split=max(0.,(t-.40)/.60)
                    mid=(a0+a1)/2
                    ang=mid+(original_angle-mid)*(1-.92*split*split)
                    tipped=1.0-(.035 if (ray+e)%2 else 0.)
                    radial=(forward*np.cos(ang)+lateral*np.sin(ang))*segment_length*t*tipped
                    fold=blade_normal*(5.8*np.sin(np.pi*t)*(-1 if (ray+e)%2 else 1))
                    droop=np.array([0,-(25+55*maturity)*t*t*(.45+.55*abs(ang)/spread),0])
                    pair.append(fan_root+radial+fold+droop)
                grid.append(pair)
            mat='leaf_light' if maturity<.23 or (k%9==1) else 'leaf'
            for d in range(depth):
                p=[grid[d][0],grid[d][1],grid[d+1][1],grid[d+1][0]]
                mesh.quad(mat,p,[[ray/rays,d/depth],[(ray+1)/rays,d/depth],[(ray+1)/rays,(d+1)/depth],[ray/rays,(d+1)/depth]],double=True)
    # Washingtonia's brown hanging leaves below the living crown.
    for k in range(18):
        a=k*2*np.pi/18+.2*variant; v=np.array([np.cos(a),0,np.sin(a)])
        side=np.array([-np.sin(a),0,np.cos(a)])
        root=apex+v*18+[0,-45,0]
        for j in range(3):
            t0,t1=j/3,(j+1)/3
            c0=root+v*(45*t0-18*t0*t0)+[0,-105*t0,0]
            c1=root+v*(45*t1-18*t1*t1)+[0,-105*t1,0]
            mesh.quad('leaf_dead',[c0-side*14*(1-t0*.7),c0+side*14*(1-t0*.7),c1+side*14*(1-t1*.7),c1-side*14*(1-t1*.7)],double=True)
    return mesh


def add_object(level, model, name, position=(0.,0.,0.), yaw=0.):
    c,s=math.cos(yaw),math.sin(yaw)
    matrix=[c,0.,-s,0.,0.,1.,0.,0.,s,0.,c,0.,*map(float,position),1.]
    level['Object'][M(name)]={'Type':'OBJECT','Target':model,'Transform':model,'Matrix':matrix}
    return {'object':M(name),'model':model,'position':list(position),'yaw_radians':yaw}


def bleachers():
    mesh=Mesh()
    # Five rows of open aluminium plank seating, on a triangulated steel frame.
    for row in range(5):
        x=-row*71; y=45+row*38
        for z in (-262.,262.):
            mesh.box('aluminum',[x,y,z],[40,5,520],bevel=1.)
            # Parallel extrusion ribs visible at low camera angles.
            for offset in (-14,0,14):
                mesh.box('aluminum',[x+offset,y+2.65,z],[1.5,.3,518])
        if row:
            mesh.box('aluminum',[x+43,y-30,0],[48,4,1050],bevel=.8)
        for z in (-490.,-245.,0.,245.,490.):
            mesh.tube('dark_metal',[x,1,z],[x,y-3,z],3.2,sides=12)
            if row:
                mesh.tube('dark_metal',[x+71,y-41,z],[x,y-3,z],2.4,sides=12)
    for z in (-535.,535.):
        for row in (0,2,4):
            x=-row*71; y=45+row*38
            mesh.tube('aluminum',[x,0,z],[x,y+92,z],2.8,sides=20)
        mesh.tube('aluminum',[0,137,z],[-284,289,z],2.8,sides=20)
        mesh.tube('aluminum',[0,105,z],[-284,257,z],2.1,sides=16)
    for y in (252,289):
        mesh.tube('aluminum',[-284,y,-535],[-284,y,535],2.8,sides=20)
    for z in np.arange(-490,501,98):
        mesh.tube('aluminum',[-284,197,z],[-284,289,z],1.8,sides=12)
    return mesh


def coastal_fixtures():
    mesh=Mesh()
    # A green bin, adjacent rounded concrete receptacle: visible in ref 4.
    mesh.tube('dark_metal',[0,0,0],[0,96,0],29,32,sides=40,caps=False)
    mesh.tube('dark_metal',[0,86,0],[0,92,0],33,33,sides=40,caps=False)
    mesh.tube('concrete',[76,0,0],[76,94,0],29,31,sides=40)
    mesh.tube('concrete',[76,92,0],[76,99,0],34,34,sides=40)
    for j in range(10):
        y0=99+j*2.8; y1=y0+2.8
        r0=24*np.sqrt(max(.001,1-(j/10)**2));r1=24*np.sqrt(max(.001,1-((j+1)/10)**2))
        mesh.tube('aluminum',[76,y0,0],[76,y1,0],r0,r1,sides=40,caps=False)
    return mesh


def apply_landscape(level, extra, textures):
    materials=[]
    for key in ('concrete','grass','bark','sand','leaf','leaf_light','leaf_dead','aluminum','dark_metal','ocean'):
        materials.append(make_unbaked_material(level,M(key),textures[key],textures[key+'_normal']))
        level['Material'][M(key)]['Parameter']['NormalHeight']={
            'concrete':.16,'grass':.35,'bark':.5,'sand':.22,
            'leaf':.25,'leaf_light':.25,'leaf_dead':.2,'aluminum':0.,'dark_metal':0.,'ocean':.03}[key]
    meshes=[]; placements=[]
    def install(mesh,name,position=(0.,0.,0.),yaw=0.):
        report=mesh.export(level,extra,name);meshes.append(report)
        placements.append(add_object(level,report['model'],name,position,yaw))
        return report

    # Same broad ground plane in all reference views, with an exact donor hole.
    f=level['Model'][level['Object']['__floor00__']['Target']]
    xmin,xmax=f['Min'][0],f['Max'][0];zmin,zmax=f['Min'][2],f['Max'][2]
    paved=Mesh()
    paved.plane('concrete',-6000,xmin,-6500,6500,y=-.4,tile=220)
    paved.plane('concrete',xmax,1100,-6500,6500,y=-.4,tile=220)
    paved.plane('concrete',xmin,xmax,-6500,zmin,y=-.4,tile=220)
    paved.plane('concrete',xmin,xmax,zmax,6500,y=-.4,tile=220)
    # Fine construction joints terminate outside the playable floor.
    for z in np.arange(-6300,6301,300):
        paved.box('dark_metal',[-3487,-.35,z],[5025,.1,.75])
    for x in np.arange(-5700,xmin,300):
        paved.box('dark_metal',[x,-.35,0],[.75,.1,13000])
    install(paved,'promenade')

    terraces=Mesh()
    # Three long low grass platforms; topography remains open to the horizon.
    for i in range(3):
        near=1100+i*445;far=near+445;top=30+i*35
        terraces.box('concrete',[(near+far)/2,top/2,0],[445,top,10100],bevel=2,tile=200)
        terraces.plane('grass',near+18,far,-5025,5025,top+.3,tile=170)
        terraces.box('concrete',[near+8,top+1,0],[16,2,10100],bevel=.6)
    terraces.plane('grass',2435,4100,-8000,8000,100.3,tile=180)
    terraces.box('concrete',[2435,50,0],[10,100,10100])
    install(terraces,'grass_terraces')

    coastal=Mesh()
    coastal.plane('concrete',4100,4500,-10000,10000,99.6,tile=220)
    # Gentle dune descent, no vertical billboard at the ocean horizon.
    coastal.quad('sand',[[4500,100,-20000],[4500,100,20000],[8500,-35,20000],[8500,-35,-20000]],[[0,0],[0,120],[20,120],[20,0]])
    coastal.plane('ocean',8500,150000,-160000,160000,-36,tile=1800)
    coastal.plane('sand',-25000,-6000,-25000,25000,-1,tile=220)
    coastal.plane('sand',-6000,4100,-25000,-6500,-1,tile=240)
    coastal.plane('sand',-6000,4100,6500,25000,-1,tile=240)
    coastal.plane('grass',1100,4100,-25000,-8000,100.3,tile=180)
    coastal.plane('grass',1100,4100,8000,25000,100.3,tile=180)
    install(coastal,'coast')

    bench=bleachers();report=bench.export(level,extra,'bleachers');meshes.append(report)
    for i,z in enumerate((-710.,710.)):
        placements.append(add_object(level,report['model'],f'bleachers_{i}',[-1620,0,z]))
    fixture=coastal_fixtures();report=fixture.export(level,extra,'bins');meshes.append(report)
    for i,(x,z) in enumerate(((-1260,1870),(-1300,-1810),(1110,2650))):
        placements.append(add_object(level,report['model'],f'bins_{i}',[x,0,z]))

    service=Mesh()
    # Low grey service building behind the far baseline, not an enclosing wall.
    service.box('concrete',[120,150,-3210],[1200,300,620],bevel=2,tile=250)
    service.box('dark_metal',[120,304,-3210],[1220,8,640],bevel=1)
    for x in (-360,60,450):
        service.box('dark_metal',[x,119,-2898],[94,236,4],bevel=.6)
        service.box('aluminum',[x+33,120,-2894],[3,17,4],bevel=.8)
    for x in (-470,-125,295,710):
        service.box('aluminum',[x,150,-2897],[2,300,3])
    service.box('aluminum',[120,260,-2896],[1190,2,3])
    install(service,'service_building')

    trees=[]
    for v in range(4):
        reports=palm_geometry(v).export_sections(level,extra,f'palm_variant_{v}')
        meshes.extend(reports);trees.append(reports)
    # Nonuniform, photograph-consistent groupings. Crown extents are checked.
    sites=[(1860,65,-2400,0),(2210,100,-1700,1),(1780,65,-940,2),
           (2200,100,-170,3),(1720,65,650,1),(2160,100,1410,0),
           (1770,65,2200,2),(2430,100,2910,1),(1850,65,3650,0),
           (2960,100,-3460,3),(3330,100,-2500,0),(2960,100,-780,2),
           (3430,100,380,1),(3030,100,2110,3),(3300,100,3750,2),
           (-2960,0,-2450,2),(-3310,0,-3380,0),(-2930,0,2510,1),
           (-4070,0,3310,2),(-4220,0,-4080,3)]
    crown_clearances=[]
    for i,(x,y,z,v) in enumerate(sites):
        for j,part in enumerate(trees[v]):
            entry=add_object(level,part['model'],f'palm_{i:02}_section_{j}',[x,y,z],i*.71)
            entry['crown_radius_cm']=245.;entry['trunk_base_on_ground']=True
            entry['palm_instance']=i
            placements.append(entry)
        for prior in sites[:i]:
            clearance=float(np.linalg.norm(np.array([x,z])-np.array([prior[0],prior[2]]))-490)
            crown_clearances.append(clearance)
            if clearance<0:raise ValueError('Overlapping palm crowns')
    # Distinctive stacked stone sculpture visible on the grass in refs 1/2.
    sculpture=Mesh()
    for j in range(8):
        r=48-2.2*j+(4 if j%2 else 0)
        sculpture.tube('concrete',[0,j*41,0],[0,j*41+39,0],r,r-6,sides=16)
    install(sculpture,'stacked_stone',[3330,100,1510])

    return {'materials':materials,'meshes':meshes,'placements':placements,
            'same_court_reference_images':5,'people_recreated':False,
            'palm_instances':len(sites),'palm_fronds_per_crown':60,'minimum_crown_clearance_cm':min(crown_clearances),
            'photographic_backdrop_cards':0,'new_collision_resources':0,
            'new_mesh_triangles':sum(x['triangles'] for x in meshes),
            'game_render_verified':False}
