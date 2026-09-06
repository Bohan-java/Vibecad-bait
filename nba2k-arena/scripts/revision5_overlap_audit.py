"""Independent triangle-overlap audit for actual exported float32 floor positions.

Uses contained vertices plus all nine segment intersections, angle-sorted around
their centroid. This is deliberately independent of the paint half-plane clipper.
An XZ spatial grid and exact bbox tests avoid the full paint x marking product.

Coordinates are centimeters. Default area tolerance 1e-5 cm^2 corresponds to a
0.0316 mm square: well below a millimeter, but above float64 area-roundoff after
centering. Float32 ULP near 1500 cm is ~0.000122 cm. Long thin overlaps of even one
such ULP can exceed the area threshold and are intentionally reported, not erased
with a generous linear clipping epsilon. Threshold is explicit/configurable.
"""
from __future__ import annotations
from collections import defaultdict
import math

import numpy as np

DEFAULT_AREA_THRESHOLD_CM2 = 1e-5


def _cross(a, b):
    return a[..., 0]*b[..., 1]-a[..., 1]*b[..., 0]


def triangle_intersection_areas(first, second):
    """Vectorized independent oracle for equally sized M x 3 x 2 pairs.

    Zero-area inputs yield zero intersection. Inputs are evaluated as supplied
    (float32 values promoted exactly to float64); no expanded tolerances move
    vertices across edges. Both winding directions are accepted.
    """
    a, b = np.asarray(first, dtype=np.float64), np.asarray(second, dtype=np.float64)
    if a.shape != b.shape or a.ndim != 3 or a.shape[1:] != (3, 2):
        raise ValueError('Expected equally sized finite Mx3x2 triangle arrays')
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('Triangle coordinates must be finite')
    if len(a) == 0:
        return np.empty(0, dtype=np.float64)
    edge_a, edge_b = np.roll(a, -1, axis=1)-a, np.roll(b, -1, axis=1)-b
    area_a = _cross(edge_a[:, 0], a[:, 2]-a[:, 0])
    area_b = _cross(edge_b[:, 0], b[:, 2]-b[:, 0])
    valid_pair = (area_a != 0) & (area_b != 0)
    # Test all vertices against the other triangle's three directed edges.
    side_a = _cross(edge_b[:, :, None, :], a[:, None, :, :]-b[:, :, None, :])
    side_b = _cross(edge_a[:, :, None, :], b[:, None, :, :]-a[:, :, None, :])
    a_inside = np.all(side_a* np.sign(area_b)[:, None, None] >= 0, axis=1)
    b_inside = np.all(side_b* np.sign(area_a)[:, None, None] >= 0, axis=1)
    r, s = edge_a[:, :, None, :], edge_b[:, None, :, :]
    difference = b[:, None, :, :]-a[:, :, None, :]
    denominator = _cross(r, s)
    nonparallel = denominator != 0
    t = np.zeros_like(denominator); u = np.zeros_like(denominator)
    np.divide(_cross(difference, s), denominator, out=t, where=nonparallel)
    np.divide(_cross(difference, r), denominator, out=u, where=nonparallel)
    intersects = nonparallel & (t >= 0) & (t <= 1) & (u >= 0) & (u <= 1)
    intersection = a[:, :, None, :] + t[:, :, :, None]*r
    points = np.concatenate((a, b, intersection.reshape(-1, 9, 2)), axis=1)
    accepted = np.concatenate((a_inside, b_inside, intersects.reshape(-1, 9)), axis=1)
    accepted &= valid_pair[:, None]
    count = accepted.sum(1)
    center = (points*accepted[:, :, None]).sum(1)/np.maximum(count, 1)[:, None]
    relative = points-center[:, None, :]
    angle = np.arctan2(relative[:, :, 1], relative[:, :, 0])
    angle[~accepted] = np.inf
    order = np.argsort(angle, axis=1, kind='stable')
    ordered = np.take_along_axis(relative, order[:, :, None], axis=1)
    j = np.arange(15)[None, :]
    successor = np.mod(j+1, np.maximum(count, 1)[:, None])
    following = np.take_along_axis(ordered, successor[:, :, None], axis=1)
    contribution = _cross(ordered, following)
    contribution[j >= count[:, None]] = 0
    areas = np.abs(contribution.sum(1))/2
    areas[count < 3] = 0
    return areas


def _triangles(value, name):
    result = np.asarray(value, dtype=np.float64)
    if result.ndim != 3 or result.shape[1:] != (3, 2) or not np.isfinite(result).all():
        raise ValueError(f'{name} must be finite Nx3x2 triangles')
    return result


def audit_overlap(paint_triangles, markings, *, area_threshold_cm2=DEFAULT_AREA_THRESHOLD_CM2,
                  grid_cell_cm=64., batch_size=16384):
    """Return JSON overlap metrics without changing inputs or running any builder.

    Total is a SUM OF PAIR INTERSECTIONS, not the union area. Overlapping marking
    triangles may count a paint overlap more than once; this is conservative for
    detecting forbidden coverage. ``over_threshold_pair_count`` is unambiguous.
    """
    paint, marks = _triangles(paint_triangles, 'paint'), _triangles(markings, 'markings')
    if not math.isfinite(area_threshold_cm2) or area_threshold_cm2 < 0:
        raise ValueError('Area threshold must be finite and nonnegative')
    if not math.isfinite(grid_cell_cm) or grid_cell_cm <= 0:
        raise ValueError('Grid cell size must be finite and positive')
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
        raise ValueError('Batch size must be a positive integer')
    maximum_coordinate = max(float(np.abs(paint).max()) if paint.size else 0,
                             float(np.abs(marks).max()) if marks.size else 0)
    if maximum_coordinate > np.finfo(np.float32).max:
        raise ValueError('Floor coordinates exceed finite float32 range')
    mark_lo, mark_hi = marks.min(1), marks.max(1)
    paint_lo, paint_hi = paint.min(1), paint.max(1)
    grid = defaultdict(list); large_markings = []
    # Oversize triangles go in a shared fallback list instead of allocating an
    # unbounded grid. Broad paint bboxes use one vectorized bbox query likewise.
    max_grid_cells_per_triangle = 4096

    def cells(low, high):
        # Python integers also handle finite float32 coordinates outside int64's
        # grid range. Such enormous bboxes normally use the vectorized fallback.
        scaled = [float(value)/grid_cell_cm for value in (*low, *high)]
        if not all(math.isfinite(value) for value in scaled):
            return (0, 0), (0, 0), max_grid_cells_per_triangle+1
        first, last = tuple(map(math.floor, scaled[:2])), tuple(map(math.floor, scaled[2:]))
        count = (last[0]-first[0]+1)*(last[1]-first[1]+1)
        return first, last, count

    for index, (low, high) in enumerate(zip(mark_lo, mark_hi)):
        first, last, count = cells(low, high)
        if count > max_grid_cells_per_triangle:
            large_markings.append(index)
            continue
        for x in range(int(first[0]), int(last[0])+1):
            for z in range(int(first[1]), int(last[1])+1):
                grid[(x, z)].append(index)
    pending_paint, pending_mark = [], []
    maximum, total, over_count, tested = 0., 0., 0, 0
    over_paint = set(); over_mark = set(); worst = None

    def consume():
        nonlocal maximum, total, over_count, tested, worst
        if not pending_paint:
            return
        p_ids, m_ids = np.asarray(pending_paint, int), np.asarray(pending_mark, int)
        values = triangle_intersection_areas(paint[p_ids], marks[m_ids])
        tested += len(values); total += float(values.sum())
        which = int(values.argmax())
        if float(values[which]) > maximum:
            maximum = float(values[which])
            worst = {'paint_triangle': int(p_ids[which]), 'marking_triangle': int(m_ids[which]),
                     'overlap_area_cm2': maximum,
                     'paint_triangle_xz_cm': paint[p_ids[which]].tolist(),
                     'marking_triangle_xz_cm': marks[m_ids[which]].tolist()}
        exceeded = values > area_threshold_cm2
        over_count += int(exceeded.sum()); over_paint.update(p_ids[exceeded].tolist())
        over_mark.update(m_ids[exceeded].tolist())
        pending_paint.clear(); pending_mark.clear()

    for p_index, (low, high) in enumerate(zip(paint_lo, paint_hi)):
        first, last, count = cells(low, high)
        if count > max_grid_cells_per_triangle:
            candidates = np.arange(len(marks))
        else:
            found = set(large_markings)
            for x in range(int(first[0]), int(last[0])+1):
                for z in range(int(first[1]), int(last[1])+1):
                    found.update(grid.get((x,z), ()))
            if not found:
                continue
            candidates = np.array(sorted(found), dtype=int)
        intersects_box = np.all(mark_hi[candidates] > low, axis=1) & np.all(mark_lo[candidates] < high, axis=1)
        candidates = candidates[intersects_box]
        cursor = 0
        while cursor < len(candidates):
            take = min(batch_size-len(pending_paint), len(candidates)-cursor)
            pending_paint.extend([p_index]*take)
            pending_mark.extend(candidates[cursor:cursor+take].tolist())
            cursor += take
            if len(pending_paint) == batch_size:
                consume()
    consume()
    coordinate32 = np.float32(maximum_coordinate)
    ulp = (float(coordinate32)-float(np.nextafter(coordinate32, np.float32(0)))
           if coordinate32 == np.finfo(np.float32).max else float(np.spacing(coordinate32)))
    return {'paint_triangle_count': len(paint), 'marking_triangle_count': len(marks),
            'max_overlap_area_cm2': maximum, 'total_overlap_area_cm2': total,
            'total_area_semantics': 'sum_of_pair_intersections_not_union; overlapping_markings_may_double_count',
            'area_threshold_cm2': float(area_threshold_cm2), 'over_threshold_pair_count': over_count,
            'paint_triangles_over_threshold_count': len(over_paint),
            'marking_triangles_over_threshold': sorted(over_mark),
            'worst_pair': worst, 'bbox_candidate_pairs_audited': tested,
            'full_cartesian_pair_count': len(paint)*len(marks),
            'grid_cell_cm': float(grid_cell_cm), 'occupied_grid_cells': len(grid),
            'oversized_marking_triangles': len(large_markings),
            'max_coordinate_float32_ulp_cm': ulp,
            'intersection_method': 'independent_contained_vertices_and_segment_intersections',
            'inputs_modified': False, 'all_pairs_below_threshold': over_count == 0}
