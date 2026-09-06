"""Resolve the stateful primitive records in a 2K SCNE model.

Start is an *index* offset, not a byte offset. When omitted, it resumes at
the previous primitive's end (including when that primitive had an explicit
Start). Material and Type carry forward until another value is specified.
This module only reads metadata / decoded indices; it never edits a scene.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from numbers import Integral
from typing import Any, Iterator


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer, got {value!r}")
    return int(value)


def _declared_index_count(model: Mapping[str, Any]) -> int | None:
    buffer = model.get("IndexBuffer")
    if buffer is None:
        return None
    if not isinstance(buffer, Mapping):
        raise ValueError("IndexBuffer must be a mapping")
    if "Size" not in buffer:
        return None
    size = _integer(buffer["Size"], "IndexBuffer.Size")
    width = {"R16_UINT": 2, "R32_UINT": 4}.get(buffer.get("Format"))
    if width is None:
        raise ValueError(f"Unsupported IndexBuffer.Format: {buffer.get('Format')!r}")
    if size % width:
        raise ValueError(f"IndexBuffer.Size {size} is not divisible by index width {width}")
    return size // width


def _declared_vertex_count(model: Mapping[str, Any]) -> int | None:
    position = model.get("VertexFormat", {}).get("POSITION0")
    streams = model.get("VertexStream")
    if position is None or streams is None:
        return None
    stream_index = _integer(position.get("Stream", 0), "POSITION0.Stream")
    if stream_index >= len(streams):
        raise ValueError(f"POSITION0.Stream {stream_index} is outside VertexStream")
    stream = streams[stream_index]
    size = _integer(stream["Size"], f"VertexStream[{stream_index}].Size")
    stride = _integer(stream["Stride"], f"VertexStream[{stream_index}].Stride")
    if stride == 0 or size % stride:
        raise ValueError(f"VertexStream[{stream_index}] has invalid Size / Stride: {size} / {stride}")
    return size // stride


def iter_primitives(
    model: Mapping[str, Any],
    *,
    indices: Sequence[int] | None = None,
    index_count: int | None = None,
    vertex_count: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield independent primitive dictionaries with Start/Material/Type set.

    Validate Count/Start and TRIANGLE_LIST divisibility. The index-buffer size
    bounds each primitive if IndexBuffer metadata, ``index_count``, or decoded
    ``indices`` are provided; independent sizes must agree. With ``indices``,
    validate every referenced index against ``vertex_count`` or the POSITION0
    stream's declared vertex count, if available. Only indices used by a Prim
    are checked, so unused buffer regions are allowed. Explicit overlapping or
    out-of-order Start offsets are legal and reset the running cursor.

    Type is inherited verbatim; topologies other than TRIANGLE_LIST receive
    range validation only. No topology conversion is performed. Errors are
    ValueError and may occur during iteration, so use list(...) before any
    consumer makes changes. Input dictionaries and index arrays are untouched.
    """
    available = _declared_index_count(model)
    supplied_counts = []
    if index_count is not None:
        supplied_counts.append(("index_count", _integer(index_count, "index_count")))
    if indices is not None:
        if isinstance(indices, (bytes, bytearray, memoryview)):
            raise ValueError("indices must be decoded integer indices, not raw bytes")
        supplied_counts.append(("len(indices)", len(indices)))
    for label, count in supplied_counts:
        if available is not None and count != available:
            raise ValueError(f"{label} {count} differs from index buffer count {available}")
        available = count

    vertices = _declared_vertex_count(model) if indices is not None else None
    if vertex_count is not None:
        supplied_vertices = _integer(vertex_count, "vertex_count")
        if vertices is not None and vertices != supplied_vertices:
            raise ValueError(f"vertex_count {supplied_vertices} differs from POSITION0 count {vertices}")
        vertices = supplied_vertices

    records = model.get("Prim", [])
    if not isinstance(records, (list, tuple)):
        raise ValueError("Prim must be a list or tuple")
    cursor = 0
    material = topology = None
    for ordinal, original in enumerate(records):
        label = f"Prim[{ordinal}]"
        if not isinstance(original, Mapping):
            raise ValueError(f"{label} must be a mapping")
        if "Count" not in original:
            raise ValueError(f"{label}.Count is required")
        start = _integer(original.get("Start", cursor), f"{label}.Start")
        count = _integer(original["Count"], f"{label}.Count")
        material = original.get("Material", material)
        topology = original.get("Type", topology)
        if not isinstance(material, str) or not material:
            raise ValueError(f"{label}.Material is missing or invalid; no valid value to inherit")
        if not isinstance(topology, str) or not topology:
            raise ValueError(f"{label}.Type is missing or invalid; no valid value to inherit")
        if topology == "TRIANGLE_LIST" and count % 3:
            raise ValueError(f"{label}.Count {count} is not divisible by 3 for TRIANGLE_LIST")
        end = start + count
        if available is not None and end > available:
            raise ValueError(f"{label} index range [{start}, {end}) exceeds index buffer count {available}")
        if indices is not None:
            for offset in range(start, end):
                value = _integer(indices[offset], f"{label} index[{offset}]")
                if vertices is not None and value >= vertices:
                    raise ValueError(f"{label} index[{offset}]={value} is outside vertex count {vertices}")
        resolved = deepcopy(dict(original))
        resolved.update(Start=start, Count=count, Material=material, Type=topology)
        yield resolved
        cursor = end
