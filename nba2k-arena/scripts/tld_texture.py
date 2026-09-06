#!/usr/bin/env python3
"""Minimal local TLD/BC1 utilities for the arena material workflow.

The donor stores ordinary BC1 blocks behind a 32-byte ``TLD `` header.  This
module intentionally supports only that verified subset; unsupported formats
are rejected rather than guessed.
"""

from __future__ import annotations

import argparse
import math
import struct
from pathlib import Path

import numpy as np
from PIL import Image


TLD_MAGIC = b"TLD "
TLD_HEADER = struct.Struct("<4sIHBBIHHHHII")
BC1_FORMAT_CODE = 0x47


def _rgb_to_565(rgb: np.ndarray) -> int:
    r, g, b = (int(v) for v in rgb)
    return ((r * 31 + 127) // 255 << 11) | ((g * 63 + 127) // 255 << 5) | ((b * 31 + 127) // 255)


def _rgb_from_565(value: int) -> np.ndarray:
    r = (value >> 11) & 31
    g = (value >> 5) & 63
    b = value & 31
    return np.array(((r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31), dtype=np.int16)


def _encode_bc1_block(block: np.ndarray) -> bytes:
    pixels = block.reshape(-1, 3).astype(np.int16)
    # Pick endpoints along the principal color direction. This remains small,
    # deterministic and more stable than independent channel extrema.
    centered = pixels - pixels.mean(axis=0, keepdims=True)
    covariance = centered.T @ centered
    try:
        values, vectors = np.linalg.eigh(covariance.astype(np.float64))
        axis = vectors[:, int(np.argmax(values))]
        projection = pixels @ axis
        high = pixels[int(np.argmax(projection))]
        low = pixels[int(np.argmin(projection))]
    except np.linalg.LinAlgError:
        high = pixels.max(axis=0)
        low = pixels.min(axis=0)

    color0 = _rgb_to_565(high)
    color1 = _rgb_to_565(low)
    if color0 == color1:
        color1 = color0 - 1 if color0 > 0 else 0
        color0 = color1 + 1
    elif color0 < color1:
        color0, color1 = color1, color0

    c0 = _rgb_from_565(color0)
    c1 = _rgb_from_565(color1)
    palette = np.stack((c0, c1, (2 * c0 + c1) // 3, (c0 + 2 * c1) // 3), axis=0)
    distances = ((pixels[:, None, :].astype(np.int32) - palette[None, :, :].astype(np.int32)) ** 2).sum(axis=2)
    indices = np.argmin(distances, axis=1)
    packed_indices = 0
    for index, palette_index in enumerate(indices.tolist()):
        packed_indices |= int(palette_index) << (2 * index)
    return struct.pack("<HHI", color0, color1, packed_indices)


def encode_bc1_level(image: Image.Image) -> bytes:
    array = np.asarray(image.convert("RGB"), dtype=np.uint8)
    height, width, _ = array.shape
    padded_h = math.ceil(height / 4) * 4
    padded_w = math.ceil(width / 4) * 4
    if padded_h != height or padded_w != width:
        array = np.pad(array, ((0, padded_h - height), (0, padded_w - width), (0, 0)), mode="edge")
    chunks: list[bytes] = []
    for y in range(0, padded_h, 4):
        for x in range(0, padded_w, 4):
            chunks.append(_encode_bc1_block(array[y : y + 4, x : x + 4]))
    return b"".join(chunks)


def build_mips(image: Image.Image) -> list[Image.Image]:
    mips = [image.convert("RGB")]
    while mips[-1].width > 1 or mips[-1].height > 1:
        current = mips[-1]
        size = (max(1, current.width // 2), max(1, current.height // 2))
        mips.append(current.resize(size, Image.Resampling.LANCZOS))
    return mips


def write_bc1_tld(image: Image.Image, destination: Path) -> dict[str, int | str]:
    mips = build_mips(image)
    payload = b"".join(encode_bc1_level(mip) for mip in mips)
    header = TLD_HEADER.pack(
        TLD_MAGIC,
        0,
        4,
        BC1_FORMAT_CODE,
        len(mips),
        0x1F,
        image.width,
        image.height,
        1,
        1,
        len(payload),
        len(payload),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(header + payload)
    return {
        "width": image.width,
        "height": image.height,
        "mips": len(mips),
        "pixel_data_size": len(payload),
        "file_size": len(header) + len(payload),
        "format": "BC1_UNORM",
    }


def read_header(path: Path) -> dict[str, int | str]:
    raw = path.read_bytes()
    if len(raw) < TLD_HEADER.size:
        raise ValueError(f"{path} is too small to be a TLD")
    magic, zero, kind, fmt, mips, flags, width, height, depth, block_words, size_a, size_b = TLD_HEADER.unpack_from(raw)
    if magic != TLD_MAGIC:
        raise ValueError(f"{path} has invalid magic {magic!r}")
    return {
        "zero": zero,
        "kind": kind,
        "format_code": fmt,
        "mips": mips,
        "flags": flags,
        "width": width,
        "height": height,
        "depth": depth,
        "block_words": block_words,
        "pixel_data_size": size_a,
        "pixel_data_size_copy": size_b,
        "file_size": len(raw),
    }


def _decode_bc1_level(payload: bytes, width: int, height: int) -> Image.Image:
    output = np.zeros((height, width, 3), dtype=np.uint8)
    offset = 0
    for by in range(math.ceil(height / 4)):
        for bx in range(math.ceil(width / 4)):
            color0, color1, indices = struct.unpack_from("<HHI", payload, offset)
            offset += 8
            c0 = _rgb_from_565(color0)
            c1 = _rgb_from_565(color1)
            if color0 > color1:
                palette = np.stack((c0, c1, (2 * c0 + c1) // 3, (c0 + 2 * c1) // 3), axis=0)
            else:
                palette = np.stack((c0, c1, (c0 + c1) // 2, np.zeros(3, dtype=np.int16)), axis=0)
            for py in range(4):
                for px in range(4):
                    x, y = bx * 4 + px, by * 4 + py
                    if x < width and y < height:
                        palette_index = (indices >> (2 * (py * 4 + px))) & 3
                        output[y, x] = palette[palette_index]
    return Image.fromarray(output, "RGB")


def decode_bc1_tld(source: Path, destination: Path) -> None:
    header = read_header(source)
    if header["format_code"] != BC1_FORMAT_CODE:
        raise ValueError(f"Only BC1 format code 0x47 is supported, got 0x{header['format_code']:02X}")
    raw = source.read_bytes()
    image = _decode_bc1_level(raw[TLD_HEADER.size :], int(header["width"]), int(header["height"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    encode = sub.add_parser("encode-bc1")
    encode.add_argument("source", type=Path)
    encode.add_argument("destination", type=Path)
    decode = sub.add_parser("decode-bc1")
    decode.add_argument("source", type=Path)
    decode.add_argument("destination", type=Path)
    header = sub.add_parser("header")
    header.add_argument("source", type=Path)
    args = parser.parse_args()

    if args.command == "encode-bc1":
        print(write_bc1_tld(Image.open(args.source), args.destination))
    elif args.command == "decode-bc1":
        decode_bc1_tld(args.source, args.destination)
    else:
        print(read_header(args.source))


if __name__ == "__main__":
    main()
