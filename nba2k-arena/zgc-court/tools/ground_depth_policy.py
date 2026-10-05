"""Restore unbiased ground depth after R07 occluded player indicators."""
from __future__ import annotations



CAMERA_PASSES = {
    'Default': ('Default', 'DepthOnlyPrepass'),
    'AssetHires': ('GBuffer', 'DepthOnlyPrepass', 'DepthVelocityPrepass'),
    'AssetLores': ('GBuffer', 'DepthOnlyPrepass', 'DepthVelocityPrepass'),
    'AssetHiresLightmap': ('GBuffer', 'DepthOnlyPrepass', 'DepthVelocityPrepass'),
    'AssetLoresLightmap': ('GBuffer', 'DepthOnlyPrepass', 'DepthVelocityPrepass'),
}
BIAS_FIELDS = ('DEPTHBIAS', 'SLOPESCALEDEPTHBIAS')
NATIVE_LINE_BOUNDS_CM = {
    'min': [-1140.45471, 0.0, -1634.51465],
    'max': [1140.49133, 0.0, 1634.52478],
}


def _is_court_plane(model):
    lo, hi = model.get('Min'), model.get('Max')
    return (lo is not None and hi is not None and len(lo) == len(hi) == 3
            and abs(lo[1]) < .1 and abs(hi[1]) < .1
            and abs(hi[1] - lo[1]) < 1e-4
            and 1500 < hi[0] - lo[0] < 3000
            and 2500 < hi[2] - lo[2] < 4500
            and lo[0] < -700 and hi[0] > 700
            and lo[2] < -1000 and hi[2] > 1000)


def _materials(model):
    result = set()
    inherited = None
    for primitive in model.get('Prim', []):
        inherited = primitive.get('Material', inherited)
        if inherited is None:
            raise ValueError('Primitive material cannot be resolved')
        result.add(inherited)
    return result


def _discover(level, source_models):
    if source_models is not None:
        if isinstance(source_models, dict):
            source_models = source_models['models']
        candidates = [x['model'] for x in source_models
                      if x.get('source_object') == 'court_surface']
        selection = 'source_object court_surface with native geometry validation'
    else:
        candidates = [name for name, model in level['Model'].items()
                      if name.startswith('zgc_r03:') and _is_court_plane(model)]
        selection = 'unique centered horizontal court-sized model at Y=0'
    if len(candidates) != 1 or candidates[0] not in level['Model']:
        raise ValueError('Expected one explicit court_surface model: ' + repr(candidates))
    name = candidates[0]
    model = level['Model'][name]
    if not name.startswith('zgc_r03:') or not _is_court_plane(model):
        raise ValueError('Source court does not match the audited flat-ground geometry')
    materials = _materials(model)
    if len(materials) != 1:
        raise ValueError('Court must have one isolated opaque material')
    material_name = next(iter(materials))
    users = [key for key, value in level['Model'].items()
             if material_name in _materials(value)]
    if users != [name]:
        raise ValueError('Court material is shared with other geometry: ' + repr(users))
    instances = [obj for obj in level['Object'].values()
                 if obj.get('Type') == 'OBJECT' and obj.get('Target') == name]
    identity = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.]
    if len(instances) != 1 or instances[0].get('Matrix', identity) != identity:
        raise ValueError('Court has a non-identity or repeated visible instance')
    return name, material_name, selection


def restore_ground_depth(level, source_models=None):
    model_name, material_name, selection = _discover(level, source_models)
    material = level['Material'][material_name]
    removed=[]
    for tn, passes in CAMERA_PASSES.items():
        for pn in passes:
            state=material['Technique'][tn]['Pass'][pn]
            for field in BIAS_FIELDS:
                if field in state:
                    removed.append({'technique':tn,'pass':pn,'field':field,'value':state.pop(field)})
    return {'policy':'R08 restore unbiased native opaque floor depth',
            'model':model_name,'material':material_name,'selection':selection,
            'removed':removed,'biased_camera_fields_remaining':0,
            'r07_feedback':'Player indicator disappears depending on position; -5 slope bias is withdrawn.',
            'geometry_unchanged':True,'game_tested':False,
            'limitations':['External native court lines are independent; removing depth bias alone does not remove them.']}

