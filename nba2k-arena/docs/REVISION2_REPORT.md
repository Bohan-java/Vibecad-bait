# Revision 2

Static checks passed. Game loading and visual behavior have not been tested in NBA 2K.

- Adds 14 non-colliding fan-palm instances using three geometry variants.
- All added palm bounds are outside the donor court footprint.
- Adds a reference-derived palm/ocean panorama to the existing mural surfaces.
- Replaces the opaque asphalt Logo0Texture with a zero-alpha BC3 texture.
- Separates matte asphalt, white line shading, and correctly packed normal/roughness maps.
- Embeds the exact original donor floor vertex resource resolved from the local game manifest.
- Preserves every original donor model, object, transform, light, compiled effect, collision and basket resource.
- Supplies arena_700_int_floor.iff to override the independently loaded stock 700 floor scene; the main donor remains the only floor.
- Game directories were only read; nothing was installed.

Use both same-number IFF files together. If using another slot, both filenames must use that slot number.
