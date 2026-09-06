"""Regression tests for real donor floor offsets and malformed SCNE records."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import struct
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from scene_primitives import iter_primitives


def model_with(*records, index_count=12):
    return {
        "Prim": list(records),
        "IndexBuffer": {"Format": "R16_UINT", "Size": index_count * 2},
    }


def first(**updates):
    result = {"Count": 3, "Material": "floor", "Type": "TRIANGLE_LIST"}
    result.update(updates)
    return result


class PrimitiveTests(unittest.TestCase):
    def test_real_donor_floor_implicit_offsets_and_inheritance(self):
        donor = ROOT / "donor/original/arena_020_int_original.iff"
        with zipfile.ZipFile(donor) as archive:
            level = json.loads(b"{" + archive.read("level.SCNE") + b"}")["level"]
            model = level["Model"][level["Object"]["__floor00__"]["Target"]]
            original = deepcopy(model)
            raw = archive.read(model["IndexBuffer"]["Binary"])
        indices = struct.unpack(f"<{len(raw) // 2}H", raw)
        records = list(iter_primitives(model, indices=indices))
        self.assertTrue(all("Start" not in record for record in model["Prim"]))
        self.assertEqual(
            [record["Start"] for record in records],
            [0, 2010, 2034, 2178, 2202, 2298, 2334, 2346, 3642, 4878, 7686, 9102],
        )
        self.assertEqual(records[-1]["Start"] + records[-1]["Count"], len(indices))
        self.assertEqual(len(indices), 9126)
        self.assertTrue(all(record["Type"] == "TRIANGLE_LIST" for record in records))
        for ordinal in (3, 4, 5, 10):
            self.assertNotIn("Material", model["Prim"][ordinal])
            self.assertEqual(records[ordinal]["Material"], "floor_clutchtime_court:floor_line_mat1")
        self.assertEqual(records[8]["Mesh"], "line_four_point_lowShape")
        self.assertEqual(records[8]["Start"], 3642)
        self.assertEqual(records[8]["Count"], 1236)
        self.assertEqual(model, original)

    def test_explicit_start_resets_cursor_in_both_directions(self):
        model = model_with(first(), {"Start": 9, "Count": 3}, {"Count": 3},
                           {"Start": 3, "Count": 3, "Material": "line"}, {"Count": 3}, index_count=15)
        records = list(iter_primitives(model))
        self.assertEqual([p["Start"] for p in records], [0, 9, 12, 3, 6])
        self.assertEqual([p["Material"] for p in records], ["floor", "floor", "floor", "line", "line"])

    def test_returned_nested_fields_are_independent(self):
        model = model_with(first(LodList=[{"Start": 0, "Count": 3}]))
        original = deepcopy(model)
        records = list(iter_primitives(model))
        records[0]["LodList"][0]["Count"] = 0
        records[0]["Material"] = "other"
        self.assertEqual(model, original)

    def test_missing_or_invalid_count_start(self):
        for field in ("Count", "Start"):
            for invalid in (-1, 1.5, True, "3", None):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaisesRegex(ValueError, field):
                        list(iter_primitives(model_with(first(**{field: invalid}))))
        record = first()
        del record["Count"]
        with self.assertRaisesRegex(ValueError, "Count is required"):
            list(iter_primitives(model_with(record)))

    def test_missing_or_invalid_inherited_fields(self):
        for field in ("Material", "Type"):
            record = first()
            del record[field]
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, field):
                    list(iter_primitives(model_with(record)))
            for invalid in (None, "", 1):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaisesRegex(ValueError, field):
                        list(iter_primitives(model_with(first(), {"Count": 3, field: invalid})))

    def test_triangle_count_and_index_buffer_bounds(self):
        with self.assertRaisesRegex(ValueError, "divisible by 3"):
            list(iter_primitives(model_with(first(Count=4))))
        for record in (first(Start=12), first(Start=13, Count=0), first(Count=15)):
            with self.subTest(record=record):
                with self.assertRaisesRegex(ValueError, "exceeds index buffer count"):
                    list(iter_primitives(model_with(record)))
        self.assertEqual(list(iter_primitives(model_with(first(Start=12, Count=0))))[0]["Start"], 12)

    def test_decoded_index_bounds_and_integer_values(self):
        model = model_with(first(), index_count=3)
        for invalid in (-1, 3, 1.5, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, r"index\[2\]"):
                    list(iter_primitives(model, indices=[0, 1, invalid], vertex_count=3))
        source = [0, 1, 2]
        list(iter_primitives(model, indices=source, vertex_count=3))
        self.assertEqual(source, [0, 1, 2])

    def test_size_disagreement_and_raw_bytes_are_rejected(self):
        model = model_with(first(), index_count=3)
        for kwargs in ({"indices": [0, 1]}, {"index_count": 4},
                       {"index_count": 3, "indices": [0, 1, 2, 0]}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, "differs from index buffer count"):
                    list(iter_primitives(model, **kwargs))
        with self.assertRaisesRegex(ValueError, "decoded integer indices"):
            list(iter_primitives(model, indices=b"\x00" * 6))

    def test_r32_and_implicit_sizes(self):
        model = model_with(first(), index_count=3)
        model["IndexBuffer"] = {"Size": 12, "Format": "R32_UINT"}
        self.assertEqual(len(list(iter_primitives(model, indices=[0, 1, 2], vertex_count=3))), 1)
        del model["IndexBuffer"]
        self.assertEqual(len(list(iter_primitives(model, index_count=3))), 1)
        with self.assertRaisesRegex(ValueError, "exceeds index buffer count"):
            list(iter_primitives(model, indices=[0, 1]))

    def test_invalid_buffer_metadata(self):
        model = model_with(first())
        model["IndexBuffer"]["Size"] = 7
        with self.assertRaisesRegex(ValueError, "not divisible"):
            list(iter_primitives(model))
        model["IndexBuffer"] = {"Size": 12, "Format": "unknown"}
        with self.assertRaisesRegex(ValueError, "Unsupported IndexBuffer.Format"):
            list(iter_primitives(model))

    def test_vertex_count_uses_position_stream(self):
        model = model_with(first(), index_count=3)
        model["VertexFormat"] = {"POSITION0": {"Stream": 1}}
        model["VertexStream"] = [{"Size": 4, "Stride": 4}, {"Size": 36, "Stride": 12}]
        list(iter_primitives(model, indices=[0, 1, 2]))
        with self.assertRaisesRegex(ValueError, "outside vertex count 3"):
            list(iter_primitives(model, indices=[0, 1, 3]))
        with self.assertRaisesRegex(ValueError, "differs from POSITION0 count"):
            list(iter_primitives(model, indices=[0, 1, 2], vertex_count=4))

    def test_type_carries_forward_and_unused_indices_are_allowed(self):
        model = model_with(first(Type="LINE_LIST", Count=2), {"Count": 2}, index_count=6)
        records = list(iter_primitives(model, indices=[0, 1, 0, 1, 999, 999], vertex_count=2))
        self.assertEqual(records[1]["Type"], "LINE_LIST")
        self.assertEqual(records[1]["Start"], 2)

    def test_empty_model_and_malformed_prim(self):
        self.assertEqual(list(iter_primitives({})), [])
        for model in ({"Prim": {}}, {"Prim": [None]}):
            with self.subTest(model=model):
                with self.assertRaisesRegex(ValueError, "Prim"):
                    list(iter_primitives(model))


if __name__ == "__main__":
    unittest.main()
