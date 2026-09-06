"""Planar paint regions with actual native marking triangles cut out.

The region geometry never relies on a later draw overwriting white markings.
Convex polygon differences need only NumPy; no geometry package is installed.
Dimensions follow the already preserved court, not photo-derived measurements.
"""
from __future__ import annotations

import math
import numpy as np

from revision3_court import FOOT, HALF_LENGTH, LANE_HALF_OUTSIDE, FREE_THROW_CENTER


def area(poly):
    p = np.asarray(poly, float)
    return float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - p[:, 1] * np.roll(p[:, 0], -1)) / 2)


def clean(poly, *, min_area=1e-7):
    p = np.asarray(poly, float).reshape(-1, 2)
    if len(p) < 3:
        return None
    keep = np.linalg.norm(p - np.roll(p, 1, axis=0), axis=1) > 1e-8
    p = p[keep]
    # Clipping adjacent native triangles often leaves many collinear points.
    # Removing only sub-nanometer deviations preserves actual circle chords
    # while avoiding thousands of redundant triangle fans.
    while len(p) >= 3:
        before, after = np.roll(p, 1, axis=0), np.roll(p, -1, axis=0)
        u, v = p-before, after-p
        distance = np.abs(u[:, 0]*v[:, 1]-u[:, 1]*v[:, 0]) / np.maximum(np.linalg.norm(after-before, axis=1), 1e-30)
        keep = (distance > 1e-8) | ((u*v).sum(1) < 0)
        if keep.all():
            break
        p = p[keep]
    if len(p) < 3 or abs(area(p)) < min_area:
        return None
    return p if area(p) > 0 else p[::-1]


def halfplane(poly, origin, edge, *, inside=True, offset=0.):
    """Clip to one oriented edge; positive distance is the left half-plane."""
    p = np.asarray(poly, float)
    q = p - origin
    distance = edge[0] * q[:, 1] - edge[1] * q[:, 0] - offset
    if not inside:
        distance = -distance
    accepted = distance >= 0
    if accepted.all():
        return p
    if not accepted.any():
        return None
    output = []
    for i in range(len(p)):
        previous = i - 1
        if accepted[previous] != accepted[i]:
            fraction = distance[previous] / (distance[previous] - distance[i])
            output.append(p[previous] + fraction * (p[i] - p[previous]))
        if accepted[i]:
            output.append(p[i])
    return clean(output)


def subtract_triangle(poly, triangle):
    """Return disjoint convex pieces of a convex polygon minus one triangle."""
    inside = clean(poly)
    if inside is None:
        return []
    t = clean(triangle)
    if t is None:
        return [inside]
    return _subtract_normalized(inside, t)


def _subtract_normalized(inside, t):
    """Internal fast path: both polygons were already cleaned and oriented."""
    outside = []
    for i in range(len(t)):
        origin, edge = t[i], t[(i+1) % len(t)] - t[i]
        piece = halfplane(inside, origin, edge, inside=False)
        if piece is not None:
            outside.append(piece)
        inside = halfplane(inside, origin, edge)
        if inside is None:
            break
    return outside


def expand_triangle_square(triangle, clearance_cm):
    """Convex Minkowski sum with a tiny square, with no acute miter spikes.

    Each output point lies within sqrt(2)*clearance of the original triangle.
    A bevelled hull avoids long extrapolated corners on thin marking wedges.
    """
    if not math.isfinite(clearance_cm) or clearance_cm < 0:
        raise ValueError('Clearance must be finite and nonnegative')
    triangle = clean(triangle)
    if triangle is None or clearance_cm == 0:
        return triangle
    offsets = clearance_cm*np.array([[-1,-1], [-1,1], [1,-1], [1,1]])
    points = sorted(set(map(tuple, (triangle[:,None,:]+offsets).reshape(-1,2))))

    def chain(sequence):
        result = []
        for point in sequence:
            while len(result) >= 2:
                a, b = result[-2], result[-1]
                cross = (b[0]-a[0])*(point[1]-b[1])-(b[1]-a[1])*(point[0]-b[0])
                if cross > 0:
                    break
                result.pop()
            result.append(point)
        return result

    return clean(chain(points)[:-1]+chain(points[::-1])[:-1])


def domains():
    """Center disk, each full-width lane, and its forward semicircle.

    The current 16 ft lane is wider than its 12 ft circle. Painting both follows
    the existing line geometry and leaves the resulting shoulders explicit.
    """
    radius = 6 * FOOT
    circle_angle = np.linspace(0, math.tau, 721)[:-1]
    result = [('center_disk', clean(radius*np.column_stack((np.cos(circle_angle), np.sin(circle_angle)))))]
    angle = np.linspace(0, math.pi, 361)
    for side in (-1, 1):
        local = np.array([[-LANE_HALF_OUTSIDE, 0], [LANE_HALF_OUTSIDE, 0],
                          [LANE_HALF_OUTSIDE, FREE_THROW_CENTER], [-LANE_HALF_OUTSIDE, FREE_THROW_CENTER]])
        rectangle = local.copy(); rectangle[:, 1] = side * (HALF_LENGTH - local[:, 1])
        result.append((f'paint_lane_{side}', clean(rectangle)))
        cap = radius*np.column_stack((np.cos(angle), np.sin(angle))) + [0, FREE_THROW_CENTER]
        cap[:, 1] = side * (HALF_LENGTH - cap[:, 1])
        result.append((f'paint_semicircle_{side}', clean(cap)))
    return result


def clip_domains(marking_triangles, *, clearance_cm=0., clearance_mask=None):
    """Cut all actual marking projections out of five non-overlapping regions."""
    markings = np.asarray(marking_triangles, float)
    if markings.ndim != 3 or markings.shape[1:] != (3, 2) or not np.isfinite(markings).all():
        raise ValueError('Expected finite Nx3x2 marking projections')
    if not math.isfinite(clearance_cm) or clearance_cm < 0:
        raise ValueError('Clearance must be finite and nonnegative')
    if clearance_mask is None:
        clearance_mask = np.ones(len(markings), dtype=bool)
    clearance_mask = np.asarray(clearance_mask, dtype=bool)
    if clearance_mask.shape != (len(markings),):
        raise ValueError('Expected one clearance-mask value per marking triangle')
    boxes = np.stack((markings.min(1)-clearance_cm, markings.max(1)+clearance_cm), axis=1)
    reports, outputs = [], []
    for name, domain in domains():
        lo, hi = domain.min(0), domain.max(0)
        candidate_ids = np.flatnonzero(np.all(boxes[:, 1] > lo, axis=1) & np.all(boxes[:, 0] < hi, axis=1))
        candidates = markings[candidate_ids]
        pieces = [domain]
        bounds = np.array([[domain.min(0), domain.max(0)]])
        clipped_pairs = 0
        for mark_id, triangle in zip(candidate_ids, candidates):
            triangle = expand_triangle_square(triangle, clearance_cm if clearance_mask[mark_id] else 0.)
            if triangle is None:
                continue
            tlo, thi = triangle.min(0), triangle.max(0)
            mask = np.all(bounds[:, 1] > tlo, axis=1) & np.all(bounds[:, 0] < thi, axis=1)
            if not mask.any():
                continue
            next_pieces = [p for i, p in enumerate(pieces) if not mask[i]]
            next_bounds = list(bounds[~mask])
            for index in np.flatnonzero(mask):
                poly = pieces[index]
                clipped_pairs += 1
                for piece in _subtract_normalized(poly, triangle):
                    next_pieces.append(piece); next_bounds.append((piece.min(0), piece.max(0)))
            pieces, bounds = next_pieces, np.asarray(next_bounds).reshape(-1, 2, 2)
        triangles = []
        kept_area = 0.
        for piece in pieces:
            kept_area += area(piece)
            for i in range(1, len(piece)-1):
                tri = np.array([piece[0], piece[i], piece[i+1]])
                if abs(area(tri)) > 1e-7:
                    triangles.append(tri)
        array = np.asarray(triangles).reshape(-1, 3, 2)
        reports.append({'name': name, 'domain_area_cm2': area(domain),
                        'visible_paint_area_cm2': kept_area,
                        'markings_cut_out_cm2': area(domain)-kept_area,
                        'marking_triangle_candidates': len(candidates),
                        'clipped_pairs': clipped_pairs, 'triangles': len(array)})
        outputs.append(array)
    return reports, outputs
