# Donor Structure

## Protected source

- Donor: `arena_020_int.iff`
- Protected copy: `donor/original/arena_020_int_original.iff`
- Working copy: `donor/working/arena_020_int_working.iff`
- SHA-256: `42865ECAF8DD923C4D901509263AF3B242C00975F4284B917BA79CE8FBBCED46`
- Container: ZIP-compatible IFF with stored entries
- Original entries: 2,221

The root donor, protected copy and initial working copy were byte-identical when the project structure was created.

## Major resources

| Resource | Role | Modification policy |
|---|---|---|
| `level.SCNE` | Main arena scene, lights, 1,759 texture records, 69 materials, 67 models and 860 objects | Material and texture references only |
| `baskets.SCNE` | Basket models, materials, glass/rim references and gameplay basket attributes | Do not change |
| `baskets_collisions.Coll` | Basket collision | Do not change |
| `level_collisions.Coll` | Main arena collision | Do not change |
| `MAIN.Coll` | Additional critical collision | Do not change |
| `crowd.SCNE` / `crowd.CrowdData` | Crowd card geometry and crowd data | Preserve |
| `level_floor_lightmaps.SCNE` | Floor light-map bindings and `FLOOR` marker | Preserve |
| `PostEffect.FxTweakables` | Arena post effects | Preserve in the first pass |
| `*.shader` (1,132) | Compiled shaders | Preserve |
| `*.tld` (757 original) | Embedded texture/light-map data | Preserve; add new local BC1 resources only |
| `*.bin` (262) | Index and vertex buffers | Do not change |
| `*.script` (50) | Material/effect bytecode | Preserve |

## Court model

The gameplay court object is `__floor00__`, targeting:

`arena_clutchtime_int_master@GameObjects@CourtFloor:floor_clutchtime_court_low`

Its model bounds are:

- Min: `[-975.360352, 0.0, -1889.76001]`
- Max: `[975.360352, 0.000000476837158, 1889.76001]`
- Radius: `2126.62183`

The model includes the physical court surface and separate donor line meshes such as `NBA_full_court_floor_low1Shape`, `NBA_line_three_point_lowShape`, lane lines, mid-court lines, charge circles and four-point line geometry. These meshes, their buffers, dimensions and transforms remain unchanged.

## Gameplay-critical preservation set

- `baskets.SCNE`
- `baskets_collisions.Coll`
- `level_collisions.Coll`
- `MAIN.Coll`
- `level_floor_lightmaps.SCNE`
- `crowd.SCNE`
- `crowd.CrowdData`
- `level.SCNE` sections `Model`, `Object` and `Light`
- `FLOOR` marker and `__floor00__` object
- All vertex/index buffers

See the CSV inventories in this folder for the exhaustive texture, material, model primitive and object mappings.
