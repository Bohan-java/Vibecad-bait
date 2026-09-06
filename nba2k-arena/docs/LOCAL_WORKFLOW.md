# Local Build Workflow

This project is self-contained and does not require GitHub, cloud storage or online conversion.

## Rebuild

Use the bundled local Python runtime or another Python installation with Pillow and NumPy:

```powershell
python scripts/create_visual_textures.py
python scripts/apply_visual_pass.py
python scripts/build_mod.py
python scripts/validate_mod.py
```

The main output is `output/arena_020_int_venice_material_pass.iff`. A second byte-identical copy is staged with the game-expected filename at `output/install/levels/arena_020_int.iff`.

## Guarded install

The local NBA 2K26 mod directory was detected at `D:\steam\steamapps\common\NBA 2K26\mods\levels`. Its current `arena_020_int.iff` matches the protected donor hash exactly, so it is deliberately not overwritten during an ordinary build.

Preview the install operation without writing to the game directory:

```powershell
python scripts/install_mod.py
```

Install only when ready for an in-game test:

```powershell
python scripts/install_mod.py --install
```

The installer first preserves the active file under `backups/002_game_mod_before_install/`, refuses an ambiguous mismatch, copies the staged build, and verifies the installed SHA-256.

Restore the protected donor to the active mod slot:

```powershell
python scripts/install_mod.py --restore
```

## Restore the extracted scene

```powershell
python scripts/apply_visual_pass.py --restore
```

This restores `extracted/donor/level.SCNE` from the local pre-edit backup. It does not touch the root donor or protected original.

## Validation gates

The validator checks:

- protected donor SHA-256;
- ZIP CRC integrity;
- no original entry was removed;
- only `level.SCNE` changed among original entries;
- all new entries match the local texture manifest;
- `Light`, `Model` and `Object` scene sections remain semantically identical;
- basket, collision and crowd resources remain byte-identical;
- local TLD headers and payload sizes are consistent.

An actual NBA 2K load test remains the final external validation step because no running game or 2K arena preview tool was found in this workspace.
