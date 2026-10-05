"""Sensitivity analysis of the reference floor badge on a ground plane.

This is a read-only measurement, not a texture generator. Board dimensions and
camera focal lengths are stated assumptions; the photograph has no calibration.
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def homography(source, destination):
    rows = []
    for (x, y), (u, v) in zip(source, destination):
        rows += [[x, y, 1, 0, 0, 0, -u*x, -u*y, -u],
                 [0, 0, 0, x, y, 1, -v*x, -v*y, -v]]
    _, _, vh = np.linalg.svd(rows)
    result = vh[-1].reshape(3, 3)
    return result/result[2, 2]


def rotate(v):
    a = np.linalg.norm(v)
    skew = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + (np.sin(a)/a if a else 1)*skew + ((1-np.cos(a))/(a*a) if a else .5)*(skew@skew)


def camera(f, points):
    k = np.array([[f, 0, 288], [0, f, 512], [0, 0, 1.]])
    xy = np.array([[-.9144, 3.81], [.9144, 3.81], [.9144, 2.7432], [-.9144, 2.7432]])
    xyz = np.column_stack([xy, np.zeros(4)])
    h = np.linalg.inv(k)@homography(xy, points)
    scale = (np.linalg.norm(h[:, 0])+np.linalg.norm(h[:, 1]))/2
    r = np.column_stack([h[:, 0]/scale, h[:, 1]/scale, np.cross(h[:, 0]/scale, h[:, 1]/scale)])
    u, _, vh = np.linalg.svd(r); r = u@vh; t = h[:, 2]/scale
    def residual(rr, tt):
        q = (xyz@rr.T+tt)@k.T
        return (q[:, :2]/q[:, 2, None]-points).reshape(-1)
    damping = .001
    for _ in range(80):
        base = residual(r, t); j = np.zeros((8, 6)); epsilon = 1e-6
        for i in range(6):
            d = np.zeros(6); d[i] = epsilon
            j[:, i] = (residual(rotate(d[:3])@r, t+d[3:])-base)/epsilon
        delta = np.linalg.solve(j.T@j+np.eye(6)*damping, -j.T@base)
        nr, nt = rotate(delta[:3])@r, t+delta[3:]
        if np.sum(residual(nr, nt)**2) < np.sum(base**2):
            r, t = nr, nt; damping = max(1e-9, damping/2)
        else:
            damping *= 10
        if np.linalg.norm(delta) < 1e-9:
            break
    return k@np.column_stack([r[:, 0], r[:, 2], t]), -r.T@t, float(np.sqrt(np.mean(residual(r, t)**2)))


def main():
    photo = ROOT/'references/part1/04_远端篮架与边界_00-22.15.png'
    pixels = np.asarray(Image.open(photo).convert('RGB')).astype(float)
    crop = pixels[622:700, 132:449]
    mask = (crop.mean(2) > 159) & (np.ptp(crop, axis=2) < 45)
    y, x = np.where(mask); observed = np.column_stack([x+132, y+622, np.ones(len(x))])
    board = np.array([[167.,273.], [317.,287.], [314.,378.], [162.,365.]])
    samples = []
    for f in (550, 650, 750, 850, 950, 1050):
        h, center, error = camera(f, board)
        ground = observed@np.linalg.inv(h).T
        ground = ground[:, :2]/ground[:, 2, None]
        low, high = np.quantile(ground, [.005, .995], axis=0)
        size = high-low
        samples.append({'assumed_focal_pixels': f, 'board_reprojection_rms_pixels': error,
                        'camera_height_m': float(center[1]), 'badge_width_m': float(size[0]),
                        'badge_length_m': float(size[1]), 'length_to_width': float(size[1]/size[0])})
    result = {'method': 'Fit camera rotation/translation to a known-size vertical backboard at fixed focal lengths, then invert the ground-plane homography for the white badge pixels.',
              'reference': str(photo.relative_to(ROOT)), 'image_dimensions': [576, 1024],
              'board_corners_pixels_clockwise_from_top_left': board.tolist(),
              'assumptions': ['Backboard outer reference rectangle 1.8288 x 1.0668 m, bottom 2.7432 m above ground.',
                              'Square pixels; principal point at image centre; no lens distortion.',
                              'Focal length is unknown; samples are sensitivity estimates, not recovered camera calibration.'],
              'limitations': ['Frame edges are manually placed within approximately 2 pixels.',
                              'The board is nearly frontal and the photograph may be cropped, making focal length/ground aspect poorly constrained.',
                              'Ratios cannot be called measured real-world dimensions; compare other photographs and brand plaque silhouette.'],
              'samples': samples}
    (ROOT/'validation/floor-badge-perspective-current.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(samples))


if __name__ == '__main__':
    main()
