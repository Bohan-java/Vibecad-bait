#!/usr/bin/env python3
"""Create the local visual texture set derived from the chat references."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from tld_texture import write_bc1_tld


ROOT = Path(__file__).resolve().parents[1]
PNG_DIR = ROOT / "textures" / "final"
TLD_DIR = ROOT / "extracted" / "donor"
MANIFEST_PATH = PNG_DIR / "texture_manifest.json"


PALETTE = {
    "asphalt": (103, 108, 109),
    "concrete": (157, 160, 155),
    "grass": (67, 96, 46),
    "sky": (54, 125, 207),
    "aluminum": (143, 151, 155),
    "dark_metal": (38, 43, 45),
}


def srgb_to_linear(value: int) -> float:
    channel = value / 255.0
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def texture_filename(name: str, png_bytes: bytes) -> str:
    digest = hashlib.sha256(name.encode("utf-8") + png_bytes).hexdigest()[:16]
    return f"venice_{name}.{digest}.tld"


def make_asphalt(size: int = 512) -> Image.Image:
    rng = np.random.default_rng(20260905)
    base = np.array(PALETTE["asphalt"], dtype=np.float32)
    yy, xx = np.mgrid[0:size, 0:size]
    periodic = (
        np.sin(2 * np.pi * xx / size * 3.0 + 0.4)
        + np.sin(2 * np.pi * yy / size * 5.0 + 1.2)
        + np.sin(2 * np.pi * (xx + yy) / size * 7.0 + 2.1)
    )
    fine = rng.normal(0.0, 3.2, (size, size))
    luminance = periodic * 1.6 + fine
    array = base[None, None, :] + luminance[:, :, None]
    # Sparse aggregate flecks, kept subtle enough not to resemble painted marks.
    flecks = rng.random((size, size))
    array[flecks < 0.003] -= 18
    array[flecks > 0.997] += 14
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), "RGB")


def main() -> None:
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    TLD_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, object]] = {}

    images: dict[str, Image.Image] = {"asphalt": make_asphalt()}
    for name, color in PALETTE.items():
        if name != "asphalt":
            images[name] = Image.new("RGB", (1, 1), color)

    for name, image in images.items():
        png_path = PNG_DIR / f"venice_{name}.png"
        preview_path = PNG_DIR / f"venice_{name}_preview.png"
        image.save(png_path)
        if image.size == (1, 1):
            image.resize((256, 256), Image.Resampling.NEAREST).save(preview_path)
        else:
            image.save(preview_path)
        png_bytes = png_path.read_bytes()
        binary = texture_filename(name, png_bytes)
        metadata = write_bc1_tld(image, TLD_DIR / binary)
        pixels = np.asarray(image.convert("RGB"), dtype=np.uint8).reshape(-1, 3)
        min_rgb = pixels.min(axis=0).tolist()
        max_rgb = pixels.max(axis=0).tolist()
        manifest[name] = {
            "logical_name": f"local/venice/{name}_basecolor.png",
            "binary": binary,
            "png": str(png_path.relative_to(ROOT)).replace("\\", "/"),
            "width": metadata["width"],
            "height": metadata["height"],
            "mips": metadata["mips"],
            "format": metadata["format"],
            "pixel_data_size": metadata["pixel_data_size"],
            "min": [round(srgb_to_linear(v), 9) for v in min_rgb] + [1.0],
            "max": [round(srgb_to_linear(v), 9) for v in max_rgb] + [1.0],
        }

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(manifest)} texture assets and {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
