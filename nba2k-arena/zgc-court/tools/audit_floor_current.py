"""Independently read the published R10 IFF ground, UVs and final DDS pixels.

This never writes source art, meshes or IFF files. The source-build report is
used only to locate the named court model, not as geometry or image evidence.
"""
from __future__ import annotations
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import zipfile
import numpy as np
from PIL import Image
from iff_codec import load_scne, decode_attribute, resolve_binary

ROOT = Path(__file__).resolve().parents[1]


def sha_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def indices(archive, model):
    spec = model['IndexBuffer']
    values = np.frombuffer(archive.read(resolve_binary(archive, spec['Binary'])),
                           {'R16_UINT': '<u2', 'R32_UINT': '<u4'}[spec['Format']])
    draws = []
    for primitive in model['Prim']:
        draw = (primitive.get('LodList') or [primitive])[0]
        tri = values[draw['Start']:draw['Start'] + draw['Count']].reshape(-1, 3)
        valid = (tri[:, 0] != tri[:, 1]) & (tri[:, 0] != tri[:, 2]) & (tri[:, 1] != tri[:, 2])
        draws.append(tri[valid])
    return np.concatenate(draws)


class GroundSampler:
    def __init__(self, positions, uvs, triangles, pixels):
        self.positions = positions
        self.uvs = uvs
        self.triangles = triangles
        self.pixels = pixels
        self.frames = []
        for ids in triangles:
            corners = positions[ids][:, [0, 2]]
            matrix = np.column_stack((corners[0] - corners[2], corners[1] - corners[2]))
            if abs(np.linalg.det(matrix)) > 1e-9:
                self.frames.append((ids, corners[2], np.linalg.inv(matrix)))

    def uv(self, game_x, game_z):
        q = np.array([game_x, game_z])
        for ids, origin, inverse in self.frames:
            a, b = inverse @ (q - origin)
            weights = np.array([a, b, 1-a-b])
            if weights.min() >= -1e-8:
                return weights @ self.uvs[ids]
        raise ValueError(f'No final-IFF court triangle at {q}')

    def color(self, game_x, game_z):
        uv = self.uv(game_x, game_z)
        image = self.pixels
        x, y = uv * [image.shape[1], image.shape[0]] - .5
        x0, y0 = int(np.floor(x)), int(np.floor(y))
        tx, ty = x-x0, y-y0
        if min(x0, y0) < 0 or x0+1 >= image.shape[1] or y0+1 >= image.shape[0]:
            raise ValueError('Sample outside final DDS')
        return ((1-tx)*(1-ty)*image[y0, x0] + tx*(1-ty)*image[y0, x0+1]
                + (1-tx)*ty*image[y0+1, x0] + tx*ty*image[y0+1, x0+1])

    def svg(self, x, y):
        return self.color(762-y, x-1432.56)


def bias_fields(value, path=''):
    result = []
    if isinstance(value, dict):
        for key, child in value.items():
            current = path + '.' + key
            if 'DEPTHBIAS' in key.upper():
                result.append({'path': current, 'value': child})
            result.extend(bias_fields(child, current))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(bias_fields(child, path + f'[{index}]'))
    return result


def as_color(value):
    return [round(float(component), 3) for component in value]


def main():
    publication = json.loads((ROOT/'validation/iff-current.json').read_text('utf-8'))
    if publication.get('revision') != 'R10':
        print(json.dumps({'status': 'waiting_for_R10', 'observed_revision': publication.get('revision')}))
        return
    path = ROOT/'output/arena_700_int.iff'
    actual_hash = sha_file(path)
    if actual_hash != publication['output_sha256']:
        raise RuntimeError('Final IFF does not match the published R10 hash')
    source = json.loads((ROOT/'validation/native-source-build.json').read_text('utf-8'))
    labels = {row['model']: row['source_object'] for row in source['models']}
    checks, errors = [], []

    def check(name, passed, **details):
        checks.append({'check': name, 'passed': bool(passed), **details})
        if not passed:
            errors.append(name)

    with zipfile.ZipFile(path) as archive:
        level = load_scne(archive.read('level.SCNE'))['level']
        names = [name for name in level['Model'] if labels.get(name) == 'court_surface']
        check('One named continuous court model in final IFF', len(names) == 1, models=names)
        if len(names) != 1:
            raise RuntimeError('Expected one final court model')
        model = level['Model'][names[0]]
        positions = decode_attribute(archive, model, 'POSITION0')[:, :3]
        uv = decode_attribute(archive, model, 'TEXCOORD0')[:, :2]
        triangles = indices(archive, model)
        check('Every decoded court vertex is at exact game Y=0', np.all(positions[:, 1] == 0),
              min_game_y_cm=float(positions[:, 1].min()), max_game_y_cm=float(positions[:, 1].max()))
        materials = {prim['Material']: level['Material'][prim['Material']] for prim in model['Prim']}
        biases = bias_fields(model, names[0])
        for name, material in materials.items():
            biases += bias_fields(material, 'Material.'+name)
            if material.get('Effect') in level.get('Effect', {}):
                biases += bias_fields(level['Effect'][material['Effect']], 'Effect.'+material['Effect'])
        check('Ground model/material/effect has no nonzero depth bias',
              all(isinstance(row['value'], (int, float)) and row['value'] == 0 for row in biases),
              fields=biases)
        material = next(iter(materials.values()))
        pixelmap = (material['Resource'].get('AlbedoMap') or material['Resource']['AlbedoMapBC3'])['Pixelmap']
        texture = level['Texture'][pixelmap]
        dds = str(PurePosixPath(texture['Binary']).with_suffix('.dds'))
        raw = archive.read(dds)
        dds_image = Image.open(io.BytesIO(raw)).convert('RGB')
        image = np.asarray(dds_image, dtype=np.uint8)
        sampler = GroundSampler(positions, uv, triangles, image)
        radius, corner, basket_z = 723.9, 670.56, -1272.54
        theta = np.arcsin(corner/radius)
        query = [(float(radius*np.sin(t)), float(basket_z+radius*np.cos(t)),
                  float(np.sin(t)), float(np.cos(t)), 'arc') for t in np.linspace(-theta, theta, 25)]
        query += [(sign*corner, z, sign, 0., 'corner') for sign in (-1, 1) for z in (-1400., -1200., -1050.)]
        yellow = []
        for x, z, nx, nz, kind in query:
            native_uv = sampler.uv(x, z)
            intended = np.array([(z+1800)/5600, (1800-x)/3600])
            mapping_error = float(np.linalg.norm((native_uv-intended)*[56000, 36000]))
            offsets = np.linspace(-2, 2, 161)
            chroma = [float((lambda c: c[1]-c[2])(sampler.color(x+nx*d, z+nz*d))) for d in offsets]
            crossing = [i for i in range(len(offsets)-1) if chroma[i] >= 50 > chroma[i+1]]
            edge = None
            if crossing:
                i = min(crossing, key=lambda i: abs(offsets[i]))
                fraction = (chroma[i]-50)/(chroma[i]-chroma[i+1])
                edge = float((offsets[i]+fraction*(offsets[i+1]-offsets[i]))*10)
            yellow.append({'kind': kind, 'game_xz_cm': [x, z], 'uv_error_mm': mapping_error,
                           'DDS_chroma_edge_offset_mm': edge})
        max_uv = max(row['uv_error_mm'] for row in yellow)
        edges = [abs(row['DDS_chroma_edge_offset_mm']) for row in yellow if row['DDS_chroma_edge_offset_mm'] is not None]
        texel_mm = np.array([56000/image.shape[1], 36000/image.shape[0]])
        pixel_tolerance_mm = float(np.linalg.norm(texel_mm)*2)
        check('NBA yellow boundary UVs agree within 3 mm', max_uv < 3, samples=len(yellow), max_error_mm=max_uv)
        check('DDS yellow transition is present at all arc/corner samples within two texel diagonals',
              len(edges) == len(yellow) and max(edges) <= pixel_tolerance_mm,
              found=len(edges), expected=len(yellow), max_edge_offset_mm=max(edges) if edges else None,
              threshold_tolerance_mm=pixel_tolerance_mm)
        # Corrected front plane. These probes read pixels from the packaged DDS.
        cx = 597 - 2*(762-517)/492
        angle = math.atan2(2, 492)
        rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])

        def key_point(x, y):
            return np.array([cx, 762]) + rotation @ [x, y]

        inside = []
        for sign in (-1, 1):
            for x in (-1.5, -4., -8., -12., -16.):
                for delta in (-1., 0., 1.):
                    point = key_point(x, sign*182.88+delta)
                    color = sampler.svg(*point)
                    inside.append({'svg_cm': point.tolist(), 'rgb': as_color(color)})
        inside_max = max(max(row['rgb']) for row in inside)
        check('No pale free-throw arc pixels 1.5–16 cm inside either black-key endpoint', inside_max < 100,
              sample_count=len(inside), maximum_channel=inside_max)
        arc = []
        for t in np.linspace(-math.pi/2, math.pi/2, 25):
            point = key_point(182.88*math.cos(t), 182.88*math.sin(t))
            color = sampler.svg(*point)
            arc.append({'svg_cm': point.tolist(), 'rgb': as_color(color)})
        # Endpoints have one-sided pixel coverage; interior points must be bright.
        visible_arc = [row for row in arc[1:-1] if row['rgb'][2] > 125]
        check('Reference-end faint semicircle follows the corrected black-key front plane', len(visible_arc) == 23,
              visible_interior_samples=len(visible_arc), expected=23)
        # Longitudinal centers are directly decoded native components; geometry
        # evidence is recorded separately. Photo-shaped lateral starts are intentional.
        lane_source = json.loads((ROOT/'validation/native-lane-tabs-current.json').read_text('utf-8'))
        tab_x = lane_source['negative_end_svg_x_centers_cm']
        tabs = []
        for x in tab_x:
            for side, y, sign in [('top', 509+8*x/597, -1), ('bottom', 1018-9*x/595, 1)]:
                center = sampler.svg(x, y+sign*10.16)
                before = sampler.svg(x-8, y+sign*10.16)
                after = sampler.svg(x+8, y+sign*10.16)
                contrast = float(center[2] - (before[2]+after[2])/2)
                tabs.append({'side': side, 'svg_x_cm': x, 'rgb': as_color(center), 'blue_contrast': contrast})
        check('Reference end retains four separate packaged white lane tabs per side', len(tabs) == 8 and all(t['blue_contrast'] > 60 for t in tabs),
              visible_counts={side: sum(t['side'] == side and t['blue_contrast'] > 60 for t in tabs) for side in ['top', 'bottom']})
        a_probes = [{'apex_side_svg_x_cm': x, 'apex_rgb': as_color(sampler.svg(x, 762)),
                     'opposite_svg_x_cm': 608-x, 'opposite_rgb': as_color(sampler.svg(608-x, 762))}
                    for x in (205, 215, 225)]
        check('Packaged A apex faces negative source X toward the reference basket',
              all(min(row['apex_rgb']) > 170 and max(row['opposite_rgb']) < 100 for row in a_probes))
        apron = {'back': [{'svg_cm': [x, y], 'rgb': as_color(sampler.svg(x, y))}
                           for x, y in [(-100, 250), (-100, 762), (-100, 1250)]],
                 'top_dark': [{'svg_cm': [x, -80], 'rgb': as_color(sampler.svg(x, -80))} for x in [100, 230, 430]],
                 'top_light': [{'svg_cm': [x, -80], 'rgb': as_color(sampler.svg(x, -80))} for x in [160, 330, 490]],
                 'bottom_dark': [{'svg_cm': [x, 1604], 'rgb': as_color(sampler.svg(x, 1604))} for x in [225, 380, 600]],
                 'bottom_light': [{'svg_cm': [x, 1604], 'rgb': as_color(sampler.svg(x, 1604))} for x in [120, 300, 500]],
                 'near_stone': [{'svg_cm': [x, y], 'rgb': as_color(sampler.svg(x, y))}
                                for x, y in [(400, -300), (400, 1820)]]}
        check('Packaged hoop-back apron is dark paint', all(max(row['rgb']) < 100 for row in apron['back']))
        for side in ('top', 'bottom'):
            check(f'Packaged {side} apron contains both black and white brush continuation',
                  all(max(row['rgb']) < 100 for row in apron[side+'_dark'])
                  and all(min(row['rgb']) > 180 for row in apron[side+'_light']))
        check('Packaged outside-fence stone is warm mid-grey, not pale blank apron',
              all(120 < min(row['rgb']) < max(row['rgb']) < 185 for row in apron['near_stone']))
        boundary = []
        queries = [(2.54, 762, 1., 0., 'reference_baseline'), (2862.58, 762, -1., 0., 'open_baseline')]
        queries += [(x, y, 0., normal, side) for x in (200., 600., 1200., 1800., 2400.)
                    for y, normal, side in [(2.54, 1., 'top_sideline'), (1521.46, -1., 'bottom_sideline')]]
        for x, y, nx, ny, kind in queries:
            center = sampler.svg(x, y)
            inner = sampler.svg(x+nx*7, y+ny*7)
            outer = sampler.svg(x-nx*7, y-ny*7)
            expected_rgb = np.array([229, 223, 202])*.92 + (inner+outer)*.04
            residual = float(np.max(np.abs(center-expected_rgb)))
            boundary.append({'kind': kind, 'svg_cm': [x, y], 'rgb': as_color(center),
                             'expected_blended_rgb': as_color(expected_rgb), 'max_channel_residual': residual})
        check('Packaged sideline/baseline centers match the gameplay rectangle',
              all(row['max_channel_residual'] < 18 for row in boundary), sample_count=len(boundary))
        # New open-end white lines, independently expressed in world/SVG units.
        # Exact curve/line centers come from native nominal court dimensions.
        open_queries = []
        for t in np.linspace(-theta, theta, 25):
            open_queries.append((2705.1-721.36*np.cos(t), 762+721.36*np.sin(t),
                                 -np.cos(t), np.sin(t), 'three_point_arc'))
        open_queries += [(x, y, 0., sign, 'three_point_corner') for x in (2500., 2670., 2800.)
                         for y, sign in [(93.98, -1.), (1430.02, 1.)]]
        open_queries += [(x, y, 0., sign, 'key_side') for x in (2400., 2600., 2800.)
                         for y, sign in [(520.7, -1.), (1003.3, 1.)]]
        open_queries += [(2288.54, y, -1., 0., 'free_throw_bar') for y in (540., 640., 762., 880., 980.)]
        open_queries += [(2286-180.34*np.cos(t), 762+180.34*np.sin(t), -np.cos(t), np.sin(t), 'free_throw_arc')
                         for t in np.linspace(-math.pi/2+.05, math.pi/2-.05, 23)]
        open_lines = []
        for x, y, nx, ny, kind in open_queries:
            center = sampler.svg(x, y)
            background = (sampler.svg(x-8*nx, y-8*ny)+sampler.svg(x+8*nx, y+8*ny))/2
            threshold = (float(background[2])+220.)/2
            deltas = np.linspace(-4., 4., 161)
            blues = [float(sampler.svg(x+nx*delta, y+ny*delta)[2]) for delta in deltas]
            crossings = [i for i in range(len(deltas)-1) if blues[i] >= threshold > blues[i+1]]
            outside_error = None
            if crossings:
                i = min(crossings, key=lambda i: abs(deltas[i]-2.54))
                fraction = (blues[i]-threshold)/(blues[i]-blues[i+1])
                actual_edge = deltas[i] + fraction*(deltas[i+1]-deltas[i])
                outside_error = float((actual_edge-2.54)*10)
            native_uv = sampler.uv(762-y, x-1432.56)
            expected_uv = np.array([(x+367.44)/5600, (y+1038)/3600])
            map_error = float(np.linalg.norm((native_uv-expected_uv)*[56000, 36000]))
            open_lines.append({'kind': kind, 'svg_cm': [float(x), float(y)],
                               'rgb': as_color(center), 'background_rgb': as_color(background),
                               'blue_contrast': float(center[2]-background[2]), 'uv_error_mm': map_error,
                               'DDS_outside_halfcontrast_edge_error_mm': outside_error})
        check('Open-end packaged three-point/key/free-throw lines have distinct white pixels at intended positions',
              all(min(row['rgb']) > 200 and row['blue_contrast'] > 40 for row in open_lines),
              sample_count=len(open_lines), minimum_blue_contrast=min(row['blue_contrast'] for row in open_lines))
        check('Open-end functional line UV position agrees within 3 mm',
              max(row['uv_error_mm'] for row in open_lines) < 3,
              max_error_mm=max(row['uv_error_mm'] for row in open_lines))
        open_edge_errors = [abs(row['DDS_outside_halfcontrast_edge_error_mm']) for row in open_lines
                            if row['DDS_outside_halfcontrast_edge_error_mm'] is not None]
        check('Open-end 5.08cm white stroke outer edges match within two texel diagonals',
              len(open_edge_errors) == len(open_lines) and max(open_edge_errors) <= pixel_tolerance_mm,
              found=len(open_edge_errors), expected=len(open_lines),
              max_edge_error_mm=max(open_edge_errors) if open_edge_errors else None,
              threshold_tolerance_mm=pixel_tolerance_mm)
        concrete = []
        for x in (1600., 1750., 1900., 2100., 2350., 2550., 2750.):
            for y in (180., 380., 680., 880., 1180., 1320.):
                # Exclude line geometry analytically, rather than selecting pixels
                # after observing whether they happen to be bright or dark.
                if abs(math.hypot(x-2705.1, y-762)-721.36) < 15:
                    continue
                if x > 2275 and min(abs(y-520.7), abs(y-1003.3)) < 15:
                    continue
                if abs(x-2288.54) < 15 and 505 < y < 1020:
                    continue
                if x <= 2290 and abs(math.hypot(x-2286, y-762)-180.34) < 15:
                    continue
                values = np.array([sampler.svg(x+dx, y+dy) for dx in (-.6, 0., .6) for dy in (-.6, 0., .6)])
                concrete.append({'svg_cm': [x, y], 'median_rgb': as_color(np.median(values, axis=0))})
        concrete_rgb = np.array([row['median_rgb'] for row in concrete])
        concrete_median = np.median(concrete_rgb, axis=0)
        check('Final DDS open-end cement is mid-grey with useful white-line contrast',
              120 < concrete_rgb.min() and concrete_rgb.max() < 180 and
              np.max(np.abs(concrete_median-[148, 153, 148])) < 15,
              sample_count=len(concrete), median_rgb=as_color(concrete_median),
              min_rgb=as_color(concrete_rgb.min(0)), max_rgb=as_color(concrete_rgb.max(0)))
        surroundings = [{'svg_cm': [x, y], 'rgb': as_color(sampler.svg(x, y))}
                        for x, y in [(3150, 400), (3200, 1000), (1800, -220), (2000, 1740)]]
        check('Final DDS adjoining garden paving also remains grey',
              all(115 < min(row['rgb']) <= max(row['rgb']) < 185 for row in surroundings))
        guard_samples = [image[y, x].astype(float) for x, y in
                         [(4, 4), (image.shape[1]//2, 4), (image.shape[1]-5, 4),
                          (4, image.shape[0]-5), (image.shape[1]//2, image.shape[0]-5),
                          (image.shape[1]-5, image.shape[0]-5)]]
        check('Final DDS outer guard uses the new grey base',
              max(np.abs(color-[148, 153, 148]).max() for color in guard_samples) < 5,
              RGB=[as_color(color) for color in guard_samples])
        texture_uv = sampler.uv(762-1080, 1800-1432.56)
        px, py = np.rint(texture_uv*[image.shape[1], image.shape[0]]).astype(int)
        texture_patch = image[py-32:py+33, px-32:px+33].astype(float)
        texture_variation = texture_patch.std(axis=(0, 1))
        check('Packaged grey cement retains subtle nonuniform mineral texture',
              .25 < float(texture_variation.mean()) < 12,
              patch_std_rgb=as_color(texture_variation), patch_svg_center_cm=[1800, 1080])
        # Readable evidence crops contain actual final DDS pixels, not SVG renders.
        crop_specs = [('floor-packaged-key-current.png', (80, 435, 850, 1090)),
                      ('floor-packaged-apron-current.png', (-200, -350, 1515, 1870)),
                      ('floor-packaged-open-current.png', (1515, 0, 2865.12, 1524))]
        for filename, (left, top, right, bottom) in crop_specs:
            def image_xy(x, y):
                u, v = sampler.uv(762-y, x-1432.56)
                return u*image.shape[1], v*image.shape[0]
            a, b = image_xy(left, top), image_xy(right, bottom)
            crop = dds_image.crop(tuple(map(int, [a[0], a[1], b[0], b[1]])))
            # DDS is square, while its world atlas covers 56 x 36 metres.
            # Restore the physical XY ratio for readable ground-plane evidence.
            scale = min(2., 1800/max(right-left, bottom-top))
            crop = crop.resize((round((right-left)*scale), round((bottom-top)*scale)), Image.Resampling.LANCZOS)
            crop.save(ROOT/'validation'/filename)
        floor = {'model': names[0], 'material_names': list(materials),
                 'decoded_bounds_game_cm': {'min': positions.min(0).tolist(), 'max': positions.max(0).tolist()},
                 'dds': dds, 'dds_sha256': hashlib.sha256(raw).hexdigest(), 'DDS_dimensions': list(dds_image.size),
                 'expected_uv_mapping': 'u=(gameZ+1800)/5600; v=(1800-gameX)/3600',
                 'one_top_mip_texel_world_mm': texel_mm.tolist(),
                 'yellow_outside_radius_cm': radius, 'yellow_corner_outside_offset_cm': corner,
                 'yellow_samples': yellow, 'max_uv_error_mm': max_uv,
                 'max_DDS_chroma_edge_offset_mm': max(edges) if edges else None,
                 'arc_inside_key_samples': inside, 'arc_path_samples': arc, 'lane_tabs': tabs,
                 'a_orientation_samples': a_probes, 'apron_material_samples': apron,
                 'boundary_samples': boundary,
                 'open_end_functional_lines': open_lines,
                 'open_end_concrete_samples': concrete,
                 'outside_garden_paving_samples': surroundings,
                 'open_end_max_DDS_stroke_edge_error_mm': max(open_edge_errors) if open_edge_errors else None,
                 'evidence_images': [filename for filename, _ in crop_specs],
                 'evidence_image_note': 'Crops are decoded final DDS pixels resized to the physical world XY aspect ratio; no source SVG pixels are substituted.'}
    report = {'revision': 'R10', 'status': 'passed' if not errors else 'failed',
              'iff_sha256': actual_hash, 'iff_bytes': path.stat().st_size, 'game_tested': False,
              'scope': 'Final-IFF native court geometry, UVs, material depth state and decoded packaged DDS pixels only.',
              'checks': checks, 'floor': floor, 'errors': errors,
              'limitations': ['Bilinear top-mip G-B=50 identifies a colour transition, not engine scoring or native line alpha.',
                             'Texture compression/filtering produces pixel-scale uncertainty beyond the numeric UV error.',
                             'Game lighting, live animation, actual loaded texture precedence and gameplay are not evaluated.',
                             'Photo reconstruction dimensions and colour samples are not calibrated site measurements.']}
    (ROOT/'validation/floor-alignment-current.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print(json.dumps({'status': report['status'], 'checks': len(checks), 'errors': errors,
                      'max_uv_error_mm': max_uv, 'max_DDS_edge_offset_mm': floor['max_DDS_chroma_edge_offset_mm']}))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
