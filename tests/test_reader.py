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
        self.figures = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.anchors.append(attrs["href"][1:])
            if "citation-link" in attrs.get("class", "").split():
                self.citations.append(attrs)
            if "figure-link" in attrs.get("class", "").split():
                self.figures.append(attrs)
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
        self.assertEqual(parsed.citations[-1]["data-preview-targets"], "R2 R3 R4")
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

    def with_figures(self):
        for bid, kind, en in [("F002", "figure", "Fig. 2. Synthetic figure."),
                               ("F002b", "figure", "Fig. 2b. Separate synthetic panel."),
                               ("T001", "table", "Table 1. Synthetic table.")]:
            block = copy.deepcopy(self.data["sections"][0]["blocks"][0])
            block.update(id=bid, kind=kind, en=en, zh="合成图表测试。", highlights=[])
            self.data["sections"][-1]["blocks"].append(block)
            self.data["source"]["expected_block_ids"].append(bid)

    def test_figure_table_panel_links_preserve_source_and_resolve_exact_targets(self):
        self.with_figures()
        block = self.data["sections"][0]["blocks"][0]
        block["en"] += " See Fig. 2a, Figure 2(b), Table 1 and Fig. 99."
        block["zh"] += " 见图 2a、图2（b）、表1和图99。"
        block["highlights"].append({"category": "evidence", "quote": "See Fig. 2a, Figure 2(b), Table"})
        parsed = OutputParser()
        parsed.feed(reader.build(self.data, ROOT))
        self.assertEqual(parsed.originals, [b["en"] for s in self.data["sections"] for b in s["blocks"]])
        self.assertEqual([a["href"] for a in parsed.figures], ["#F002", "#F002b", "#T001"] * 2)
        self.assertEqual([a["data-preview-panel"] for a in parsed.figures], ["a", "", ""] * 2)
        self.assertTrue(set(parsed.anchors).issubset(parsed.ids))
        self.assertEqual(parsed.translation_marks, 0)
        block["link_figures"] = False
        parsed = OutputParser()
        parsed.feed(reader.build(self.data, ROOT))
        self.assertEqual(parsed.figures, [])

    def test_figure_labels_are_unambiguous_and_cannot_create_unrelated_targets(self):
        self.with_figures()
        candidate = self.data["sections"][-1]["blocks"][-1]
        candidate.update(en="Synthetic table with a nonstandard caption.", xref_label="表 1")
        self.assertEqual(reader.figure_index(reader.validate(self.data))[("table", "1", "")], "T001")
        for changes in ({"xref_label": "Fig. 2"}, {"xref_label": "<img onerror=alert(1)>"},
                        {"kind": "paragraph"}, {"xref_label": "Table 1", "kind": "figure"}):
            with self.subTest(changes=changes):
                data = copy.deepcopy(self.data)
                data["sections"][-1]["blocks"][-1].update(changes)
                with self.assertRaises(ValueError):
                    reader.validate(data)

    def test_deep_insights_require_grounding_impact_and_known_lens(self):
        block = self.data["sections"][0]["blocks"][0]
        block["analysis"]["insights"] = [{
            "lens": "mechanism", "title": "A testable mechanism",
            "text": "A bounded interpretation.", "reason": "Based on the supplied description.",
            "implication": "Limits what can be concluded.", "refs": ["S001"],
            "check": "Compare the stated conditions.",
        }]
        reader.validate(self.data)
        for change in ({"lens": "made-up"}, {"refs": ["missing"]},
                       {"implication": ""}, {"reason": ""}, {"check": ""}):
            with self.subTest(change=change):
                candidate = copy.deepcopy(self.data)
                candidate["sections"][0]["blocks"][0]["analysis"]["insights"][0].update(change)
                with self.assertRaises(ValueError):
                    reader.validate(candidate)
        block["analysis"]["insights"][0]["text"] = '<img src=x onerror="alert(1)">'
        output = reader.build(self.data, ROOT)
        self.assertNotIn('<img src=x', output)
        self.assertIn("&lt;img src=x", output)

    def test_source_explainers_reset_per_document_and_details_are_progressive(self):
        output = reader.build(self.data, ROOT)
        self.assertEqual(output.count('class="note-explainer"'), 2)
        self.assertEqual(reader.build(self.data, ROOT).count('class="note-explainer"'), 2)
        # The first block can legitimately have no author card.
        self.data["sections"][0]["blocks"][0]["author"] = []
        output = reader.build(self.data, ROOT)
        self.assertEqual(output.count('class="note-explainer"'), 2)
        first = self.data["sections"][0]["blocks"][0]
        item = dict(lens="comparison", title="Same budget", text="A specific interpretation.",
                    reason="The source holds this budget fixed.", implication="Bounds the comparison.",
                    refs=["S001", "S002"])
        first["analysis"]["insights"] = [item, copy.deepcopy(item)]
        output = reader.build(self.data, ROOT)
        self.assertIn('<details class="extra-insights">', output)
        self.assertIn('<details class="insight-details">', output)
        self.assertIn('<details class="quote-details">', output)
        self.assertNotIn('<details class="insight-details" open', output)
        self.assertNotIn('<details class="extra-insights" open', output)
        parsed = OutputParser()
        parsed.feed(output)
        self.assertTrue(set(parsed.anchors).issubset(parsed.ids))
        self.assertEqual(parsed.originals, [b["en"] for s in self.data["sections"] for b in s["blocks"]])

    def test_terms_match_longest_alias_with_boundaries_and_preserve_text(self):
        entries = [
            dict(id="G_TL", term="TL", aliases=["时间锁步"], text="Time redundancy."),
            dict(id="G_NC", term="Non-Commit", text="First execution."),
            dict(id="G_C", term="Commit", text="Second execution."),
        ]
        markup = ('<p>TL / ATL / TL_extra; 时间锁步与Non-Commit和Commit。 &amp; &lt;x&gt;</p>'
                  '<a href="#S001">TL</a><blockquote class="source-quote">TL</blockquote>'
                  '<summary>TL</summary><h3 class="note-title">TL</h3>')
        rendered = reader.NoteTerms(entries).annotate(markup)
        self.assertEqual(rendered.count('data-term-id="G_TL"'), 2)
        self.assertEqual(rendered.count('data-term-id="G_NC"'), 1)
        self.assertEqual(rendered.count('data-term-id="G_C"'), 1)
        self.assertIn('<a href="#S001">TL</a>', rendered)
        self.assertIn('<blockquote class="source-quote">TL</blockquote>', rendered)
        self.assertIn('<summary>TL</summary>', rendered)
        self.assertIn('ATL / TL_extra', rendered)
        class Text(HTMLParser):
            def __init__(self, value):
                super().__init__()
                self.values = []
                self.feed(value)
            def handle_data(self, value):
                self.values.append(value)
        self.assertEqual("".join(Text(markup).values), "".join(Text(rendered).values))

    def test_glossary_provenance_unique_aliases_and_safe_rendering(self):
        self.data["glossary"] = [
            dict(id="G_policy", term="策略", aliases=["policy"], text="A bounded explanation.",
                 type="analysis", reason="Grounded in the stated comparison.", refs=["S001"])
        ]
        reader.validate(self.data)
        for change in (
            {"id": "S001"}, {"id": "term-popover"}, {"aliases": [""]},
            {"type": "external"}, {"reason": ""}, {"refs": ["missing"]},
            {"type": "paper"}, {"context": ""},
        ):
            with self.subTest(change=change):
                candidate = copy.deepcopy(self.data)
                candidate["glossary"][0].update(change)
                with self.assertRaises(ValueError):
                    reader.validate(candidate)
        candidate = copy.deepcopy(self.data)
        candidate["glossary"].append(dict(candidate["glossary"][0], id="G_other"))
        with self.assertRaises(ValueError):
            reader.validate(candidate)
        self.data["glossary"][0]["text"] = '<script>alert("term")</script>'
        output = reader.build(self.data, ROOT)
        self.assertIn('&lt;script&gt;alert', output)
        self.assertNotIn('<script>alert("term")', output)
        self.assertIn('data-term-id="G_policy"', output)
        parsed = OutputParser()
        parsed.feed(output)
        self.assertEqual(parsed.originals, [b["en"] for s in self.data["sections"] for b in s["blocks"]])
        self.assertEqual(len(parsed.ids), len(set(parsed.ids)))
        self.assertTrue(set(parsed.anchors).issubset(parsed.ids))
        item = self.data["glossary"][0]
        item.update(type="paper", evidence=[dict(ref="S001", quote="Invented definition.")])
        with self.assertRaises(ValueError):
            reader.validate(self.data)
        item["evidence"][0]["quote"] = self.data["sections"][0]["blocks"][0]["en"]
        reader.validate(self.data)

    def test_connections_require_other_blocks_and_remain_collapsed(self):
        block = self.data["sections"][1]["blocks"][0]
        block["analysis"]["connections"] = {
            "before": dict(text="Operationalizes the budget in S001.", refs=["S001"]),
            "after": dict(text="The limitation in S003 bounds this result.", refs=["S003"]),
        }
        reader.validate(self.data)
        for connection in (
            {"before": dict(text="Only self.", refs=["S002"])},
            {"after": dict(text="No source.", refs=[])},
            {"after": dict(text="Unknown source.", refs=["unknown"])},
            {"after": dict(text="Invalid flag.", refs=["S003"], closure="yes")},
        ):
            with self.subTest(connection=connection):
                candidate = copy.deepcopy(self.data)
                candidate["sections"][1]["blocks"][0]["analysis"]["connections"].update(connection)
                with self.assertRaises(ValueError):
                    reader.validate(candidate)
        output = reader.build(self.data, ROOT)
        self.assertIn('class="local-argument-chain"', output)
        self.assertNotIn('<details class="argument-details" open', output)
        rendered = reader.connections_html(block["analysis"])
        self.assertIn('href="#S001"', rendered)
        self.assertIn('href="#S003"', rendered)
        self.assertEqual(rendered.count('class="argument-step"'), 4)
        block["analysis"]["connections"]["after"]["closure"] = True
        self.assertIn("闭合论证", reader.connections_html(block["analysis"]))


if __name__ == "__main__":
    unittest.main()
