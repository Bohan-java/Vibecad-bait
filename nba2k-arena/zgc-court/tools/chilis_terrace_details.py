"""Photo-grounded R11 Chili's terrace furniture, fountain and floor module.

No file is saved by this module. The architecture builder supplies
``facade_frame(face, u, z, offset) -> (point, outward_normal, tangent)``.
Geometry is made in metre-scale local coordinates, then placed rigidly in that
frame. The entry and terrace faces are deliberately separate.
"""
from __future__ import annotations
import math
import random
from pathlib import Path
import bpy
import bmesh
from mathutils import Vector
import refine_architecture_r02 as primitive
from refine_details_r03 import pbr, shader_for

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'R11 Chilis terrace '
OLD_NAMES = tuple('R02 architecture ' + suffix for suffix in (
    'Chilis narrow restaurant terrace', 'Chilis terrace low rounded curb',
    'Chilis terrace fine paving joints', 'Chilis terrace dark cafe tables',
    'Chilis terrace cafe furniture frames', 'Chilis terrace red brown chair slats',
    'Chilis folded terrace parasols', 'Chilis small observed tiered fountain',
    'Chilis fountain muted blue basin', 'Chilis terrace planters',
    'Chilis terrace planter foliage', 'Chilis terrace side-walk handrail',
    'Chilis terrace side-walk glass guard', 'Chilis low walkway bollards',
))
EVIDENCE = {
    '01': 'Summer restaurant photo: warm red outdoor tile, paired square mosaic tables, ivory open umbrellas, three-tier fountain and blue/white basin.',
    '04': 'Two narrow black A-frame advertising stands outside entry. No invented prices or unreadable menu copy.',
    '05': 'Fountain basin wall and blue/white inner mosaic; three upper dishes; clear terrace screen behind; cafe chairs have curved woven red backs.',
    '06': 'Two square tables abut with a visible join; red curved backs carry narrow cream woven marks, champagne metal frame.',
    '11': 'Reverse terrace view: offset cantilever parasol mast, bolted feet, repeated paired tables, vase planter. Snow/seasonal decoration excluded.',
}


def _get(api, key, default=None):
    return api.get(key, default) if isinstance(api, dict) else getattr(api, key, default)


class Terrace:
    def __init__(self, api):
        self.api = api
        self.frame = _get(api, 'facade_frame')
        if self.frame is None:
            raise ValueError('The main architecture builder must supply facade_frame.')
        self.collection = _get(api, 'collection') or bpy.data.collections.get('background')
        self.parent = _get(api, 'parent') or bpy.data.objects.get('background')
        self.layout = dict(_get(api, 'terrace_layout', {}) or {})
        self.entry_layout = dict(_get(api, 'entry_layout', {}) or {})
        self.builders = {}
        self.objects = []
        self.anchors = []
        self.rng = random.Random(261104)
        self.materials = {}
        specs = {
            'black coated metal': ('292D2B', .58, .42),
            'champagne chair frames': ('A5956D', .53, .55),
            'red wicker': ('813B37', .82, .03),
            'woven cream filaments': ('C8B991', .88, .02),
            'terrace red grout': ('6D4940', .97, 0),
            'terrace warm brick': ('8C4F3D', .92, 0),
            'terrace brick variation': ('975C45', .93, 0),
            'table tile ochre': ('AA8155', .85, 0),
            'table tile deep red': ('6E4334', .88, 0),
            'table tile light grid': ('C2A57E', .9, 0),
            'fountain limestone': ('C4C2B2', .84, 0),
            'fountain blue tiles': ('354E83', .46, .01),
            'fountain pale tiles': ('CACFC5', .51, .01),
            'still basin water': ('5C7778', .27, .06),
            'beige parasol canvas': ('C3B18F', .97, 0),
            'parasol canvas seams': ('A7967E', .99, 0),
            'brushed fixing bolts': ('8D938E', .45, .68),
            'planter sage ceramic': ('747F73', .64, .08),
            'topiary leaves': ('485B40', .9, 0),
            'poster warm panel': ('A88769', .92, 0),
            'poster coffee panel': ('4B3C39', .93, 0),
            'poster red print': ('842F30', .91, 0),
            'poster pale print': ('C7BCA4', .92, 0),
            'host desk oak': ('A88C68', .86, 0),
            'host desk subtle grain': ('937758', .9, 0),
        }
        for name, (color, rough, metal) in specs.items():
            mat = pbr(PREFIX + '| ' + name, color, rough, metal)
            shader_for(mat).inputs['Emission Strength'].default_value = 0
            mat['r11_photo_evidence'] = True
            self.materials[name] = mat

    def batch(self, name, mat, smooth=False):
        if name not in self.builders:
            b = primitive.Batch(name, self.materials[mat], smooth)
            b.name = PREFIX + name
            self.builders[name] = b
        return self.builders[name]

    def point(self, face, u, offset, z):
        return Vector(self.frame(face, u, z, offset)[0])

    def place(self, local, target, face, u, offset, z=0, angle=0, label=None):
        p, n, t = (Vector(v) for v in self.frame(face, u, z, offset))
        up = Vector((0, 0, 1))
        ca, sa = math.cos(angle), math.sin(angle)
        a, b = t * ca + n * sa, n * ca - t * sa
        verts = [p + a * x + b * y + up * zz for x, y, zz in local.vertices]
        target.add(verts, local.faces)
        if label:
            self.anchors.append({'label': label, 'face': face, 'u': u, 'offset': offset,
                                 'z': z, 'local_bounds': bounds(local.vertices),
                                 'world_origin': list(p)})

    def local(self, name, mat, smooth=False):
        return primitive.Batch(name, self.materials[mat], smooth)

    def floor(self):
        u0, u1 = self.layout.get('u_range', (-4.65, 4.65))
        depth = self.layout.get('depth', 3.65)
        z = self.layout.get('ground_z', .034)
        grout = self.batch('warm red terrace grout bed', 'terrace red grout')
        # No raised slab: the new colour is confined to the restaurant terrace.
        steps = max(10, math.ceil((u1-u0)/.35))
        for i in range(steps):
            a=u0+(u1-u0)*i/steps; b=u0+(u1-u0)*(i+1)/steps
            grout.add([self.point('terrace',a,.03,z),self.point('terrace',b,.03,z),
                       self.point('terrace',b,depth,z),self.point('terrace',a,depth,z)],[(0,1,2,3)])
        tiles = [self.batch('warm red square terrace tiles', 'terrace warm brick'),
                 self.batch('warm red square terrace tile variants', 'terrace brick variation')]
        # Photo 01 shows a diagonally laid warm brick field, not white paving.
        pitch=.285; half=(pitch-.008)/math.sqrt(2)
        nu=math.ceil((u1-u0)/(.5*pitch*math.sqrt(2)))+2
        nv=math.ceil(depth/(pitch*math.sqrt(2)))+2
        for ix in range(nu):
            u=u0+ix*pitch/math.sqrt(2)
            for iy in range(nv):
                v=iy*pitch*math.sqrt(2)+(ix%2)*pitch/math.sqrt(2)
                points=[(u-half,v),(u,v-half),(u+half,v),(u,v+half)]
                # Whole diamonds only. Narrow boundary band stays red grout.
                if min(q[0] for q in points)<u0 or max(q[0] for q in points)>u1:continue
                if min(q[1] for q in points)<.06 or max(q[1] for q in points)>depth-.03:continue
                tiles[(ix+iy*3)%5==0].add([self.point('terrace',a,b,z+.0015) for a,b in points],[(0,1,2,3)])

    def table(self, u, offset, number, angle=0):
        # Two .70m square tables, each with its own pedestal, with an 8mm join.
        frame=self.local('table frame', 'black coated metal')
        grout=self.local('table mosaic grout', 'table tile light grid')
        ochre=self.local('table tile', 'table tile ochre')
        red=self.local('table alternate tile', 'table tile deep red')
        for xc in (-.354,.354):
            frame.box((xc,0,.748),(.700,.700,.040))
            grout.box((xc,0,.770),(.672,.672,.009))
            frame.rod((xc,0,.052),(xc,0,.728),.044,segments=12)
            frame.lathe((xc,0,0),[(0,.018),(.247,.018),(.255,.035),(.230,.054),(.06,.058)],28)
            for i in range(9):
                for j in range(9):
                    target=ochre if (i+j)%3 else red
                    target.box((xc+(i-4)*.073, (j-4)*.073, .776),(.067,.067,.006))
        for local,key,mat in ((frame,'square mosaic table black frames','black coated metal'),
                              (grout,'square mosaic table fine grout','table tile light grid'),
                              (ochre,'square mosaic table ochre inserts','table tile ochre'),
                              (red,'square mosaic table dark inserts','table tile deep red')):
            self.place(local,self.batch(key,mat),'terrace',u,offset,.034,angle,
                       f'paired-square-table-{number}' if local is frame else None)
        # Four seats, backs away from table, leave the joint visible.
        ca,sa=math.cos(angle),math.sin(angle)
        for i,(x,y,a) in enumerate(((-.35,-.60,math.pi),(.35,-.60,math.pi),(-.35,.60,0),(.35,.60,0))):
            self.chair(u+x*ca-y*sa,offset+x*sa+y*ca,angle+a,number*4+i)

    def chair(self, u, offset, angle, number):
        frame=self.local('chair bent metal', 'champagne chair frames')
        wicker=self.local('chair woven red shell', 'red wicker')
        cream=self.local('chair woven cream', 'woven cream filaments')
        # Local +Y is the back. Slightly splayed tubular legs and stretchers.
        for x in (-.178,.178):
            for y in (-.17,.16):
                frame.rod((x*1.15,y*1.16,.032),(x,y,.452),.0125,segments=7)
            frame.rod((x,-.15,.20),(x,.18,.20),.010,segments=6)
            frame.rod((x,.16,.40),(x,.228,.78),.011,segments=7)
        frame.rod((-.18,.12,.265),(.18,.12,.265),.010,segments=6)
        wicker.box((0,-.015,.452),(.394,.385,.033))
        for x in (-.203,.203):frame.rod((x,-.204,.443),(x,.184,.443),.011,segments=7)
        def back(x,z):
            # Curved, rounded-top upholstered/woven back, not horizontal bars.
            y=.19+.080*(1-(x/.218)**2)+.095*(z-.48)
            return (x,y,z)
        nx,nz=14,14
        def top(x):return .805+.095*math.sqrt(max(0,1-(x/.218)**2))
        vertices=[]
        for j in range(nz+1):
            for i in range(nx+1):
                x=-.218+.436*i/nx;z=.50+(top(x)-.50)*j/nz
                vertices.append(back(x,z))
        faces=[]
        for j in range(nz):
            for i in range(nx):
                k=j*(nx+1)+i;faces.append((k,k+1,k+nx+2,k+nx+1))
        wicker.add(vertices,faces)
        # Actual narrow diagonal cream weave marks across the red curved shell.
        # Both sides are modeled so the reverse terrace view also shows pattern.
        for side in (-1,1):
            for j in range(12):
                z=.515+j*.027
                for i in range(11):
                    x=-.192+i*.038+(j%2)*.007
                    if abs(x)>.20 or z+.011>top(x)-.012:continue
                    q=[]
                    for dx,dz in ((-.009,-.007),(-.005,-.009),(.009,.007),(.005,.009)):
                        xx,yy,zz=back(x+dx,z+dz);q.append((xx,yy+side*.0025,zz))
                    cream.add(q,[(0,1,2,3)])
        for i in range(18):
            x=-.216+.432*i/18;xx=-.216+.432*(i+1)/18
            frame.rod(back(x,top(x)),back(xx,top(xx)),.008,segments=5)
        for local,key,mat in ((frame,'curved chair champagne tube frames','champagne chair frames'),
                              (wicker,'curved chair woven red bodies','red wicker'),
                              (cream,'curved chair pale diagonal weave','woven cream filaments')):
            self.place(local,self.batch(key,mat,True),'terrace',u,offset,.034,angle,
                       f'woven-chair-{number}' if local is frame else None)

    def fountain(self):
        u=self.layout.get('fountain_u',.30);v=self.layout.get('fountain_offset',2.30)
        stone=self.local('tiered fountain stone','fountain limestone',True)
        blue=self.local('blue basin tesserae','fountain blue tiles')
        pale=self.local('pale basin tesserae','fountain pale tiles')
        water=self.local('still basin water','still basin water')
        stone.lathe((0,0,0),[(0,.02),(.655,.02),(.715,.05),(.73,.13),(.73,.455),
                    (.710,.488),(.653,.495),(.618,.474),(.601,.437),(.591,.14),(.15,.14)],72)
        # Fluted central stem and three bowls, proportions cross-checked 01/05/11.
        stem=[(.195,.13),(.195,.20),(.133,.27),(.11,.42),(.145,.55),(.12,.66),
              (.115,.77),(.098,.89),(.116,1.06),(.088,1.22),(.084,1.40),
              (.08,1.50),(.096,1.62),(.078,1.70),(.06,1.84),(0,1.94)]
        stone.lathe((0,0,0),stem,48)
        for zz,rr in ((.31,.137),(.38,.118),(.47,.124),(.60,.140),
                      (.91,.108),(1.02,.120),(1.36,.094),(1.47,.097),(1.75,.076)):
            stone.lathe((0,0,0),[(rr*.89,zz-.014),(rr,zz-.009),(rr*1.03,zz),
                                  (rr,zz+.010),(rr*.90,zz+.015)],48)
        for r,z in ((.398,.78),(.270,1.23),(.181,1.60)):
            # Shaped dish, rounded scalloped outside rim, open upper bowl.
            profile=[(.06,z-.17),(r*.28,z-.15),(r*.70,z-.087),(r*.96,z-.050),
                     (r,z-.018),(r,z+.022),(r*.94,z+.05),(r*.86,z+.043),(.09,z-.038)]
            vv=[];n=72
            for rr,zz in profile:
                for i in range(n):
                    a=2*math.pi*i/n
                    scallop=.009*math.cos(a*12)*(rr/r)**4
                    vv.append(((rr+scallop)*math.cos(a),(rr+scallop)*math.sin(a),zz))
            ff=[]
            for j in range(len(profile)-1):
                for i in range(n):
                    ff.append((j*n+i,j*n+(i+1)%n,(j+1)*n+(i+1)%n,(j+1)*n+i))
            stone.add(vv,ff)
        # Small blue/white physical tesserae on the inner wall (no blue pool blob).
        for row in range(8):
            z0=.175+row*.034;z1=z0+.030
            # Sit a millimetre INSIDE the stone inner surface, not behind it.
            radius=.590+(z0-.14)*.033
            for col in range(112):
                a0=2*math.pi*(col+.08)/112;a1=2*math.pi*(col+.92)/112
                target=blue if (row*7+col*3)%11<5 else pale
                target.add([(radius*math.cos(a0),radius*math.sin(a0),z0),
                            (radius*math.cos(a1),radius*math.sin(a1),z0),
                            ((radius+.001)*math.cos(a1),(radius+.001)*math.sin(a1),z1),
                            ((radius+.001)*math.cos(a0),(radius+.001)*math.sin(a0),z1)],[(0,1,2,3)])
        water.lathe((0,0,0),[(.14,.167),(.591,.167)],72)
        for local,key,mat in ((stone,'three tier fountain carved limestone','fountain limestone'),
                              (blue,'fountain small blue inner mosaic','fountain blue tiles'),
                              (pale,'fountain small pale inner mosaic','fountain pale tiles'),
                              (water,'fountain still recessed basin','still basin water')):
            local.vertices=[(x*1.13,y*1.13,z*1.083) for x,y,z in local.vertices]
            self.place(local,self.batch(key,mat,local is stone),'terrace',u,v,.034,0,
                       'three-tier-fountain' if local is stone else None)

    def umbrella(self,u,v,number,opened=True,angle=0):
        metal=self.local('cantilever umbrella frame','black coated metal')
        canvas=self.local('cantilever umbrella canvas','beige parasol canvas')
        seam=self.local('cantilever umbrella seams','parasol canvas seams')
        bolts=self.local('cantilever umbrella anchors','brushed fixing bolts')
        # Real off-centre mast and fixed floor flange, observed in image 11.
        metal.box((0,.80,.040),(.245,.245,.06))
        metal.box((0,.80,1.385),(.065,.078,2.66))
        for x in (-.083,.083):
            for y in (.717,.883):bolts.rod((x,y,.073),(x,y,.086),.015,segments=6)
        metal.rod((0,.80,2.67),(0,-.10,2.77),.028,segments=8)
        metal.rod((0,.80,2.20),(0,.08,2.70),.015,segments=7)
        if opened:
            # Four-panel square canopy (not a circular patio umbrella).
            corner=[(-1.08,-1.20,2.35),(1.08,-1.20,2.35),(1.08,.96,2.35),(-1.08,.96,2.35)]
            apex=(0,-.12,2.78)
            for i in range(4):
                a,b=corner[i],corner[(i+1)%4]
                canvas.add([apex,a,b],[(0,1,2)])
                canvas.add([a,b,(b[0],b[1],b[2]-.11),(a[0],a[1],a[2]-.11)],[(0,1,2,3)])
                seam.rod(apex,a,.006,segments=4)
                metal.rod((0,-.12,2.65),(a[0]*.94,a[1]*.94,a[2]-.03),.010,segments=6)
                mid=Vector(a).lerp(Vector(b),.5)
                metal.rod((0,-.12,2.65),mid+Vector((0,0,-.025)),.009,segments=6)
        else:
            # Winter views are used for mechanics only, without modeled snow.
            vv=[];n=20
            for r,z in ((.040,2.73),(.10,2.43),(.18,1.9),(.31,1.15),(.22,.88)):
                for i in range(n):
                    a=2*math.pi*i/n; rr=r*(1.12 if i%2 else .80)
                    vv.append((rr*math.cos(a),-.12+rr*math.sin(a),z))
            canvas.add(vv,[(j*n+i,j*n+(i+1)%n,(j+1)*n+(i+1)%n,(j+1)*n+i)
                           for j in range(4) for i in range(n)])
        for local,key,mat in ((metal,'parasol cantilever masts ribs and fixed feet','black coated metal'),
                              (canvas,'parasol beige summer canvas','beige parasol canvas'),
                              (seam,'parasol fine panel seams','parasol canvas seams'),
                              (bolts,'parasol visible floor anchors','brushed fixing bolts')):
            self.place(local,self.batch(key,mat,local is metal),'terrace',u,v,.034,angle,
                       f'cantilever-parasol-{number}' if local is metal else None)

    def planter(self,u,v):
        pot=self.local('vase planter','planter sage ceramic',True)
        leaves=self.local('topiary','topiary leaves')
        pot.lathe((0,0,0),[(0,.02),(.16,.02),(.19,.17),(.235,.48),(.255,.62),
                    (.253,.69),(.225,.705),(.214,.67)],28)
        # Broad, restrained round shrub shape from image 11, no seasonal baubles.
        for i in range(210):
            a=self.rng.uniform(0,2*math.pi); t=self.rng.uniform(-1,1)
            rr=math.sqrt(1-t*t)
            p=(.37*rr*math.cos(a),.37*rr*math.sin(a),.90+.33*t)
            leaves.leaf(p,.12,.055,a,self.rng.uniform(-.4,.4))
        self.place(pot,self.batch('sage vase planters','planter sage ceramic',True),'terrace',u,v,.034,label='vase-planter')
        self.place(leaves,self.batch('clipped planter foliage','topiary leaves'),'terrace',u,v,.034)

    def menu(self,u,v,kind,angle=0):
        frame=self.local('A-frame menu stand','black coated metal')
        panel=self.local('poster face','poster warm panel' if kind==0 else 'poster coffee panel')
        ink=self.local('restrained poster shapes','poster red print')
        pale=self.local('poster shape highlights','poster pale print')
        w=.52;z0=.17;z1=1.10
        # Two mechanically plausible hinged inclined panels with a spread foot.
        for sy in (-1,1):
            a=-sy*.035;b=sy*.205
            for x in (-w/2,w/2):frame.rod((x,b,.025),(x,a,1.16),.018,segments=7)
            frame.rod((-w/2,a,1.16),(w/2,a,1.16),.021,segments=7)
            panel.add([(-w/2+.019,sy*.185,z0),(w/2-.019,sy*.185,z0),
                       (w/2-.019,sy*-.025,z1),(-w/2+.019,sy*-.025,z1)],[(0,1,2,3)])
        frame.rod((-.24,-.19,.12),(-.24,.19,.12),.010,segments=6)
        frame.rod((.24,-.19,.12),(.24,.19,.12),.010,segments=6)
        # Broad drink/cup silhouettes observed in 04. No invented readable copy.
        def patch(builder,xx,zz,ww,hh):
            yz=lambda z:.185-(z-z0)*.21/(z1-z0)+.003
            builder.add([(xx-ww/2,yz(zz-hh/2),zz-hh/2),(xx+ww/2,yz(zz-hh/2),zz-hh/2),
                         (xx+ww/2,yz(zz+hh/2),zz+hh/2),(xx-ww/2,yz(zz+hh/2),zz+hh/2)],[(0,1,2,3)])
        patch(ink,0,.91,.37,.07)
        patch(pale,0,1.02,.08,.026)
        patch(pale,-.115,.53,.11,.17);patch(ink,.10,.50,.12,.22)
        patch(pale,0,.27,.34,.022)
        for local,key,mat in ((frame,'entry hinged menu stands','black coated metal'),
                              (panel,f'entry poster panel {kind}','poster warm panel' if kind==0 else 'poster coffee panel'),
                              (ink,'entry advertising broad red shapes','poster red print'),
                              (pale,'entry advertising broad pale shapes','poster pale print')):
            self.place(local,self.batch(key,mat),'entry',u,v,.025,angle,
                       f'entry-menu-board-{kind}' if local is frame else None)

    def entry_welcome(self):
        """Photo 02: sloped narrow menu lectern and a separate oak host cabinet."""
        u,v=self.entry_layout.get('lectern',(2.5,1.2))
        metal=self.local('sloped menu lectern frame','black coated metal')
        paper=self.local('sloped menu lectern page','poster pale print')
        ink=self.local('sloped menu lectern unlettered divisions','poster coffee panel')
        metal.box((0,0,.035),(.43,.34,.045))
        metal.rod((0,0,.045),(0,0,.99),.025,segments=10)
        # Readable silhouette only: two ivory menu pages, no fabricated prices.
        verts=[(-.265,-.185,1.115),(.265,-.185,1.115),(.265,.185,.995),(-.265,.185,.995)]
        metal.add(verts,[(0,1,2,3)])
        for side in (-1,1):
            x0=.010 if side>0 else -.248;x1=.248 if side>0 else -.010
            paper.add([(x0,-.17,1.114),(x1,-.17,1.114),(x1,.17,1.004),(x0,.17,1.004)],[(0,1,2,3)])
            for row in range(7):
                yy=-.125+row*.039;zz=1.114-(yy+.17)*.110/.34+.0015
                ink.add([(x0+.022,yy,zz),(x1-.022,yy,zz),
                         (x1-.022,yy+.004,zz-.0012),(x0+.022,yy+.004,zz-.0012)],[(0,1,2,3)])
        self.place(metal,self.batch('entry separate sloped menu lectern','black coated metal'),'entry',u,v,.025,label='entry-sloped-menu-lectern')
        self.place(paper,self.batch('entry lectern pale menu paper','poster pale print'),'entry',u,v,.025)
        self.place(ink,self.batch('entry lectern fine page divisions','poster coffee panel'),'entry',u,v,.025)
        u,v=self.entry_layout.get('host_desk',(3.25,.8))
        oak=self.local('wooden host desk','host desk oak')
        grain=self.local('wooden host desk narrow grain','host desk subtle grain')
        feet=self.local('host desk feet','black coated metal')
        oak.box((0,0,.575),(.75,.50,1.05))
        oak.box((0,0,1.11),(.78,.54,.035))
        oak.box((0,.258,.97),(.66,.018,.035))
        for x in (-.375,.375):oak.box((x,.264,.575),(.036,.023,1.07))
        for i in range(21):
            x=-.337+i*.0334
            grain.box((x,.251,.56),(.0014,.0015,.78+.09*(i%3)/2))
        for x in (-.31,.31):
            for y in (-.19,.19):
                feet.box((x,y,.055),(.045,.045,.07))
        self.place(oak,self.batch('entry oak welcome cabinet','host desk oak'),'entry',u,v,.025,label='entry-oak-host-desk')
        self.place(grain,self.batch('entry cabinet restrained wood grain','host desk subtle grain'),'entry',u,v,.025)
        self.place(feet,self.batch('entry cabinet small feet','black coated metal'),'entry',u,v,.025)

    def finish(self):
        for b in self.builders.values():
            if not b.vertices:continue
            mesh=bpy.data.meshes.new(b.name)
            mesh.from_pydata(b.vertices,[],b.faces);mesh.update()
            bm=bmesh.new();bm.from_mesh(mesh)
            bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
            bm.to_mesh(mesh);bm.free()
            mesh.materials.append(b.mat)
            obj=bpy.data.objects.new(b.name,mesh)
            self.collection.objects.link(obj);obj.parent=self.parent
            obj['layer']='background';obj['r11_chilis_terrace']=True
            obj['reference_images']='chilis-detail/01_新增原图: 01,04,05,06,11'
            obj['measurement_status']='Photo-derived scale and layout; no measured survey'
            obj['no_added_emission']=True
            for polygon in mesh.polygons:polygon.use_smooth=b.smooth
            self.objects.append(obj)
        all_vertices=[v for b in self.builders.values() for v in b.vertices]
        return {
            'revision':'R11', 'objects':[o.name for o in self.objects],
            'mesh_count':len(self.objects),'vertices':len(all_vertices),
            'triangles':sum(max(0,len(f)-2) for b in self.builders.values() for f in b.faces),
            'world_bounds':bounds(all_vertices),'anchors':self.anchors,
            'photo_evidence':EVIDENCE,'layout':self.layout,
            'entry_layout':self.entry_layout,
            'scale_status':'Relative photo reconstruction, metric dimensions inferred',
            'excluded':['snow','Christmas decorations','invented menu prices','emissive lighting'],
            'fountain_dimensions_m':{'basin_diameter':1.6498,'stone_height':2.10102,'three_dishes':3},
            'table_dimensions_m':{'each_square_width':.70,'pair_join':.008,'height':.779},
        }


def bounds(vertices):
    if not vertices:return None
    return {'min':[min(v[i] for v in vertices) for i in range(3)],
            'max':[max(v[i] for v in vertices) for i in range(3)]}


def build(api):
    """Return a report, leaving saving/rendering to the main building pipeline.

    Optional ``api.terrace_layout`` overrides: u_range, depth, ground_z,
    fountain_u, fountain_offset, tables [(u,offset,angle)], parasols
    [(u,offset,opened,angle)], planters [(u,offset)], menus [(u,offset)].
    """
    deleted=[]
    for obj in list(bpy.data.objects):
        if obj.name in OLD_NAMES or obj.name.startswith(PREFIX):
            deleted.append(obj.name);bpy.data.objects.remove(obj,do_unlink=True)
    t=Terrace(api)
    t.floor();t.fountain()
    tables=t.layout.get('tables',[(-2.30,1.22,0),(2.30,1.22,0),(-2.30,2.73,0),(2.30,2.73,0)])
    for i,(u,v,a) in enumerate(tables):t.table(u,v,i,a)
    for i,(u,v,a) in enumerate(t.layout.get('interior_tables',[]),len(tables)):
        t.table(u,v,i,a)
    parasols=t.layout.get('parasols',[(-2.90,1.92,True,math.pi/2),(2.90,1.92,True,-math.pi/2)])
    for i,(u,v,opened,a) in enumerate(parasols):t.umbrella(u,v,i,opened,a)
    for u,v in t.layout.get('planters',[(-4.15,2.75),(4.15,2.75)]):t.planter(u,v)
    for i,(u,v) in enumerate(t.entry_layout.get('menus',t.layout.get('menus',[]))):t.menu(u,v,i)
    if t.entry_layout.get('welcome',False):t.entry_welcome()
    report=t.finish();report['deleted_old_objects']=deleted
    return report
