"""Source-grounding and self-contained rendering checks; standard library only."""
import base64
import copy
import importlib.util
import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("reader", ROOT / "scripts" / "build_reader.py")
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


class OutputParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.anchors, self.resources, self.originals = [], [], [], []
        self.stack = []
        self.capturing = False
        self.current = []
        self.translation_marks = 0
        self.script_count = 0
        self.citations = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.anchors.append(attrs["href"][1:])
            if "citation-link" in attrs.get("class", "").split():
                self.citations.append(attrs)
        if "src" in attrs:
            self.resources.append(attrs["src"])
        if tag == "script":
            self.script_count += 1
        classes = attrs.get("class", "").split()
        if "original" in classes:
            self.capturing = True
            self.current = []
        if tag == "mark" and any("translation" in cs for _, cs in self.stack):
            self.translation_marks += 1
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, classes))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            _, classes = self.stack.pop()
            if "original" in classes:
                self.originals.append("".join(self.current))
                self.capturing = False

    def handle_data(self, value):
        if self.capturing:
            self.current.append(value)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "assets" / "demo-content.json").read_text(encoding="utf-8"))

    def test_originals_anchors_translation_and_offline_fonts(self):
        output = reader.build(self.data, ROOT)
        parsed = OutputParser()
        parsed.feed(output)
        originals = [b["en"] for s in self.data["sections"] for b in s["blocks"]]
        self.assertEqual(parsed.originals, originals)
        self.assertEqual(len(parsed.ids), len(set(parsed.ids)))
        self.assertTrue(set(parsed.anchors).issubset(parsed.ids))
        self.assertEqual(parsed.translation_marks, 0)
        self.assertEqual(parsed.script_count, 1)
        self.assertTrue(all(src.startswith("data:") for src in parsed.resources))
        self.assertEqual(output.count("data:font/ttf;base64,"), 2)
        self.assertNotIn("@@BODY@@", output)

    def test_reject_unsupported_or_misrepresented_source_content(self):
        mutations = {
            "invented quotation": lambda d: d["sections"][0]["blocks"][0]["author"][0]["evidence"][0].update(quote="Universal superiority is proven."),
            "unknown source": lambda d: d["sections"][0]["blocks"][0]["analysis"]["logic"].update(refs=["S999"]),
            "missing reasoning": lambda d: d["sections"][0]["blocks"][0]["analysis"]["logic"].update(reason=""),
            "overlap": lambda d: d["sections"][0]["blocks"][0]["highlights"].append({"category": "method", "quote": "selective replication"}),
            "incomplete inventory": lambda d: d["source"]["expected_block_ids"].append("S004"),
            "partial as full": lambda d: d["source"].update(scope="full"),
            "invented page": lambda d: d["sections"][0]["blocks"][0]["locator"].update(pdf_page=1),
            "assessment as Paper": lambda d: d["overview"]["strongest"].update(type="paper"),
            "duplicate ID": lambda d: d["sections"][1]["blocks"][0].update(id="S001"),
            "missing author": lambda d: d["sections"][0]["blocks"][0].pop("author"),
            "executable URL": lambda d: d["sections"][0]["blocks"][0].update(external=[{"text": "x", "citation": "x", "url": "javascript:alert(1)"}]),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                candidate = copy.deepcopy(self.data)
                mutate(candidate)
                with self.assertRaises(ValueError):
                    reader.validate(candidate)

    def test_content_cannot_inject_markup_or_template_values(self):
        self.data["title"] = '<script>alert("test")</script> @@BODY@@'
        output = reader.build(self.data, ROOT)
        self.assertNotIn('<script>alert("test")</script>', output)
        self.assertIn("&lt;script&gt;", output)
        self.assertIn("@@BODY@@", output)

    def test_embeds_media_and_rejects_active_format(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "pixel.png").write_bytes(base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN3sAAAAASUVORK5CYII="))
            block = self.data["sections"][0]["blocks"][0]
            block["media"] = {"path": "pixel.png", "alt": "Synthetic test pixel"}
            output = reader.build(self.data, directory)
            self.assertIn('src="data:image/png;base64,', output)
            block["media"]["path"] = "test.svg"
            with self.assertRaises(ValueError):
                reader.build(self.data, directory)

    def test_page_grounded_mode_requires_positive_page_numbers(self):
        self.data["source"]["mode"] = "page-grounded"
        with self.assertRaises(ValueError):
            reader.validate(self.data)
        for section in self.data["sections"]:
            for block in section["blocks"]:
                block["locator"]["pdf_page"] = 1
        reader.validate(self.data)
        self.data["sections"][0]["blocks"][0]["locator"]["pdf_page"] = 0
        with self.assertRaises(ValueError):
            reader.validate(self.data)

    def with_references(self):
        self.data["sections"] = [s for s in self.data["sections"] if s["id"] != "references"]
        self.data["source"]["expected_block_ids"].remove("R001")
        first = self.data["sections"][0]["blocks"][0]
        first["en"] = first["en"].split(" A synthetic background reference")[0]
        first["zh"] = first["zh"].split("合成的背景文献见")[0]
        for number in range(1, 5):
            block = copy.deepcopy(self.data["sections"][0]["blocks"][0])
            block.update(id=f"R{number}", kind="reference", en=f"[{number}] Synthetic reference.",
                         zh=f"[{number}] 合成参考文献。", highlights=[])
            self.data["source"]["expected_block_ids"].append(block["id"])
            if number == 1:
                self.data["sections"].append({"id": "references", "title": "References",
                                              "collapsed": True, "blocks": []})
            self.data["sections"][-1]["blocks"].append(block)

    def test_citation_groups_ranges_highlights_and_text_preservation(self):
        self.with_references()
        block = self.data["sections"][0]["blocks"][0]
        block["en"] += " Cited [1], [2, 4] and [2–4]; unknown [99], DOI [10.123/a]."
        block["zh"] += " 引文 [1]、[2, 4] 与 [2–4]；未知 [99]。"
        block["highlights"].append({"category": "evidence", "quote": "Cited [1], [2,"})
        output = reader.build(self.data, ROOT)
        parsed = OutputParser()
        parsed.feed(output)
        self.assertEqual(parsed.originals, [b["en"] for s in self.data["sections"] for b in s["blocks"]])
        self.assertEqual([a["href"] for a in parsed.citations], ["#R1", "#R2", "#R4", "#R2"] * 2)
        self.assertEqual(len(parsed.ids), len(set(parsed.ids)))
        self.assertTrue(set(parsed.anchors).issubset(parsed.ids))
        self.assertEqual(parsed.translation_marks, 0)
        self.assertNotIn('href="#R99"', output)
        # Citation anchors contain even a partially overlapping highlight without splitting the link.
        self.assertIn('title="查看参考文献 1"><mark class="evidence"', output)

    def test_reference_mapping_is_explicit_and_unambiguous(self):
        self.with_references()
        refs = self.data["sections"][-1]["blocks"]
        refs[0].update(en="One. Synthetic reference.", reference_number=1)
        self.assertEqual(reader.bibliography_index(reader.validate(self.data))[1], "R1")
        for changes in ({"reference_number": True}, {"reference_number": 2},
                        {"en": "[2] Duplicate reference.", "reference_number": 2}):
            with self.subTest(changes=changes):
                candidate = copy.deepcopy(self.data)
                candidate["sections"][-1]["blocks"][0].update(changes)
                with self.assertRaises(ValueError):
                    reader.validate(candidate)

    def test_citation_opt_out_missing_targets_and_generated_id_collision(self):
        self.with_references()
        block = self.data["sections"][0]["blocks"][0]
        block["en"] += " Array [1, 2]; absent [8]; partial [3–9]; reverse [4–2]."
        block["zh"] += " 数组 [1, 2]。"
        block["link_citations"] = False
        parsed = OutputParser()
        parsed.feed(reader.build(self.data, ROOT))
        self.assertEqual(parsed.citations, [])
        block["link_citations"] = True
        self.data["sections"][-1]["id"] = "citation-S001-en-1"
        parsed = OutputParser()
        parsed.feed(reader.build(self.data, ROOT))
        self.assertEqual([a["href"] for a in parsed.citations], ["#R1", "#R2"] * 2)
        self.assertEqual(len(parsed.ids), len(set(parsed.ids)))
        self.assertTrue(set(parsed.anchors).issubset(parsed.ids))


if __name__ == "__main__":
    unittest.main()
