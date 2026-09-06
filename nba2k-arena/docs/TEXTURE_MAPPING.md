# Texture and Material Mapping

## First-pass replacements

| Photo feature | Donor material/surface | Local visual resource | Notes |
|---|---|---|---|
| Medium-gray outdoor asphalt | `floor_clutchtime_court:area_1_mat` | `local/venice/asphalt_basecolor.png` | Replaces wood detail and donor logo texture; court mesh and UVs stay unchanged |
| Asphalt outside the line geometry | `clutchtime_floor_apron:floor_mat` | Asphalt | Preserves apron geometry |
| White painted court lines | `floor_clutchtime_court:floor_line_mat*` | Existing donor line texture | Preserved because the photos show white lines |
| Silver metal bleachers | `clutchtime_crowd_seating:chair` | Aluminum gray | Uses existing chair/stand geometry |
| Concrete terrace edges | `clutchtime_balcony_b:balcony_mat`, `balcony4_mat` | Concrete gray | Existing roughness/normal behavior remains |
| Grass terraces | `clutchtime_balcony_b:balcony2_amt` | Muted coastal grass green | Maps visible lawn onto the closest donor terrace surface |
| Metal rails | `clutchtime_balcony_railing:railing_mat` | Aluminum gray | Existing metal response remains |
| Low walls, stairs and tunnels | wall, stair and tunnel materials | Concrete gray | Conservative continuation for unseen sides |
| Open blue sky impression | five mural panels and broad ceiling surfaces | Sky blue | Visual continuation only; ceiling geometry is not deleted or moved |
| Dark basket/structural metal | ceiling ribs and existing basket materials | Dark gray where safe | Basket scene itself remains untouched |
| No prominent arena LED identity | 13 dorna LED materials and score-cube screens | Dark metal | Geometry preserved and screens visually neutralized |

## Local TLD set

The first pass adds six BC1 textures using the donor's verified 32-byte TLD header and full mip chains:

- `venice_asphalt`: 512×512, 10 mips, procedural low-contrast aggregate texture
- `venice_concrete`: 1×1 base color; donor normal/roughness maps retain surface detail
- `venice_grass`: 1×1 base color; donor roughness supplies conservative texture response
- `venice_sky`: 1×1 base color for distant mural/ceiling continuation
- `venice_aluminum`: 1×1 base color for bleachers and rails
- `venice_dark_metal`: 1×1 base color for neutralized screens and dark structure

Exact filenames, hashes, dimensions and linear min/max values are recorded in `textures/final/texture_manifest.json`.

## External donor references

The donor scene declares some source textures that are not embedded in this single IFF, including the original 8,192×4,096 BC7 court logo texture and 4,096×4,096 wood texture. These are game/shared-library references. The first pass avoids requiring their extraction or re-encoding by redirecting the corresponding material slots to new embedded local BC1 resources.

## Atlas status

No donor texture atlas was blindly replaced. No UV data was changed. Baked BC6H surface/light data and BC4 line-light visibility maps remain byte-identical.
