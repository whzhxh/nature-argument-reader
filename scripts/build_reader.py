#!/usr/bin/env python3
"""Validate source-grounded content and render a self-contained bilingual reader."""
import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

SKILL_DIR = Path(__file__).resolve().parent.parent
CATEGORIES = {
    "thesis": "核心论点", "term": "关键概念", "evidence": "实证证据",
    "concession": "让步/反驳", "method": "方法论",
}
SLOTS = {"function": "段落功能", "logic": "逻辑角色", "technique": "论证技巧", "caveat": "潜在漏洞 / 边界"}
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif"}
RESERVED = {"top", "argument-overview", "highlights-toggle"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), f"{name} 必须为非空文本")
    return value


def esc(value):
    return html.escape(str(value), quote=True)


def valid_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value))


def highlight_ranges(block):
    ranges = []
    require(isinstance(block.get("highlights", []), list), f"{block['id']}: highlights 必须为数组")
    for mark in block.get("highlights", []):
        require(isinstance(mark, dict), f"{block['id']}: 高亮项必须为对象")
        category = mark.get("category")
        require(category in CATEGORIES, f"{block['id']}: 未知高亮类别 {category}")
        quote = text(mark.get("quote"), f"{block['id']}.highlight.quote")
        occurrence = mark.get("occurrence", 1)
        require(type(occurrence) is int and occurrence >= 1, "occurrence 必须是正整数")
        matches = [m.start() for m in re.finditer(re.escape(quote), block["en"])]
        require(len(matches) >= occurrence, f"{block['id']}: 原文中找不到高亮短语 {quote!r} 第 {occurrence} 次出现")
        start = matches[occurrence - 1]
        ranges.append((start, start + len(quote), category))
    ranges.sort()
    require(all(a[1] <= b[0] for a, b in zip(ranges, ranges[1:])),
            f"{block['id']}: 高亮重叠，请选择主要类别")
    return ranges


def validate_evidence(items, blocks, name):
    require(isinstance(items, list) and bool(items), f"{name}: 缺少原文证据")
    for item in items:
        require(isinstance(item, dict), f"{name}: evidence 项必须为对象")
        ref = item.get("ref")
        require(isinstance(ref, str) and ref in blocks, f"{name}: 未知来源 ID {ref}")
        quote = text(item.get("quote"), f"{name}.quote")
        require(quote in blocks[ref]["en"], f"{name}: 短引不在 {ref} 原文中")


def validate_analysis(item, blocks, name):
    require(isinstance(item, dict), f"{name}: 必须为分析对象")
    text(item.get("text"), f"{name}.text")
    text(item.get("reason"), f"{name}.reason")
    refs = item.get("refs")
    require(isinstance(refs, list) and bool(refs), f"{name}: 缺少依据段落")
    require(all(isinstance(ref, str) and ref in blocks for ref in refs),
            f"{name}: 包含未知依据 ID")


def validate_summary(item, blocks, name, only_analysis=False):
    require(isinstance(item, dict), f"{name}: 必须为对象")
    label = item.get("type")
    require(label in {"paper", "analysis"}, f"{name}: type 必须为 paper 或 analysis")
    require(not only_analysis or label == "analysis", f"{name}: 强弱评价属于模型分析")
    if label == "paper":
        text(item.get("text"), name)
        validate_evidence(item.get("evidence"), blocks, name)
    else:
        validate_analysis(item, blocks, name)


def bibliography_index(blocks):
    """Use bibliography labels, never block order, to resolve numeric citations."""
    result = {}
    for block in blocks.values():
        number = block.get("reference_number")
        if number is not None:
            require(block["kind"] == "reference" and type(number) is int and number > 0,
                    f"{block['id']}: reference_number 只允许参考文献使用正整数")
        if block["kind"] != "reference":
            continue
        label = re.match(r"^\s*\[([1-9][0-9]*)\]", block["en"])
        if label:
            inferred = int(label[1])
            require(number is None or number == inferred,
                    f"{block['id']}: reference_number 与原文编号冲突")
            number = inferred
        if number is not None:
            require(number not in result, f"参考文献编号重复: {number}")
            result[number] = block["id"]
    return result


def validate(data):
    require(isinstance(data, dict), "根必须为对象")
    text(data.get("title"), "title")
    text(data.get("course"), "course")
    text(data.get("bibliography"), "bibliography")
    source = data.get("source")
    require(isinstance(source, dict), "缺少 source")
    text(source.get("description"), "source.description")
    text(source.get("coverage"), "source.coverage")
    mode, scope = source.get("mode"), source.get("scope")
    require(mode in {"page-grounded", "structure-grounded", "source-limited"}, "未知来源定位模式")
    require(scope in {"full", "excerpt", "incomplete"}, "未知覆盖范围")
    require(not (mode == "source-limited" and scope == "full"), "仅片段来源不能标记全文")
    for key in ("missing", "notes"):
        require(isinstance(source.get(key), list) and all(isinstance(x, str) and x.strip() for x in source[key]),
                f"source.{key} 必须为文本数组")
    require(scope != "full" or not source["missing"], "有缺失时不能标记全文")
    require(scope != "incomplete" or bool(source["missing"]), "不完整文件必须解释缺失")
    sections = data.get("sections")
    require(isinstance(sections, list) and bool(sections), "sections 必须非空")
    ids, blocks = set(RESERVED), {}
    for section in sections:
        require(isinstance(section, dict), "section 必须为对象")
        sid = section.get("id")
        require(valid_id(sid) and sid not in ids, f"章节 ID 无效或重复: {sid}")
        ids.add(sid)
        text(section.get("title"), f"{sid}.title")
        require(type(section.get("collapsed", False)) is bool, f"{sid}.collapsed 必须为布尔值")
        rows = section.get("blocks")
        require(isinstance(rows, list) and bool(rows), f"{sid}: 章节不能空")
        for block in rows:
            require(isinstance(block, dict), "block 必须为对象")
            bid = block.get("id")
            require(valid_id(bid) and bid not in ids, f"块 ID 无效或重复: {bid}")
            ids.add(bid)
            blocks[bid] = block
            text(block.get("en"), f"{bid}.en")
            text(block.get("zh"), f"{bid}.zh")
            require(block.get("kind") in {"paragraph", "caption", "figure", "table", "equation", "reference", "statement"},
                    f"{bid}: 缺少有效 kind")
            locator = block.get("locator")
            require(isinstance(locator, dict), f"{bid}: 缺少 locator")
            text(locator.get("label"), f"{bid}.locator.label")
            page = locator.get("pdf_page")
            if mode == "page-grounded":
                require(type(page) is int and page > 0, f"{bid}: 缺少可靠 PDF 物理页码")
            else:
                require("pdf_page" not in locator, f"{bid}: 当前模式不得填 PDF 页码")
            require(isinstance(block.get("uncertainty", ""), str), f"{bid}: uncertainty 必须为文本")
            require(type(block.get("link_citations", True)) is bool, f"{bid}: link_citations 必须为布尔值")
            highlight_ranges(block)
    bibliography_index(blocks)
    expected = source.get("expected_block_ids")
    require(isinstance(expected, list) and bool(expected) and all(valid_id(x) for x in expected),
            "必须提供提取阶段的 expected_block_ids 清单")
    require(len(expected) == len(set(expected)), "expected_block_ids 包含重复项")
    require(set(blocks).issubset(expected), "存在未登记在来源清单中的块")
    if scope in {"full", "excerpt"}:
        require(set(blocks) == set(expected), "覆盖清单与实际段落不符，请补齐或标记 incomplete")
    for bid, block in blocks.items():
        authors = block.get("author")
        require(isinstance(authors, list), f"{bid}: author 必须为数组")
        for item in authors:
            require(isinstance(item, dict), f"{bid}: 作者陈述必须为对象")
            text(item.get("text"), f"{bid}.author.text")
            validate_evidence(item.get("evidence"), blocks, f"{bid}.author")
        analysis = block.get("analysis")
        require(isinstance(analysis, dict) and set(SLOTS).issubset(analysis),
                f"{bid}: 缺少四个分析槽位")
        for key in SLOTS:
            item = analysis[key]
            if key in {"function", "logic"} or item is not None:
                validate_analysis(item, blocks, f"{bid}.{key}")
        media = block.get("media")
        if media is not None:
            require(isinstance(media, dict), f"{bid}: media 必须为对象")
            text(media.get("path"), f"{bid}.media.path")
            text(media.get("alt"), f"{bid}.media.alt")
        external = block.get("external", [])
        require(isinstance(external, list), f"{bid}: external 必须为数组")
        for item in external:
            require(isinstance(item, dict), f"{bid}: external 项必须为对象")
            text(item.get("text"), "external.text")
            text(item.get("citation"), "external.citation")
            url = urlsplit(text(item.get("url"), "external.url"))
            require(url.scheme in {"https", "http"} and bool(url.netloc),
                    "外部出处仅允许 HTTP(S) 链接")
    overview = data.get("overview")
    require(isinstance(overview, dict), "缺少 overview")
    chain = overview.get("chain")
    require(isinstance(chain, list) and all(isinstance(x, dict) for x in chain),
            "overview.chain 必须为对象数组")
    require([x.get("stage") for x in chain] == ["问题", "论点", "证据", "反驳", "结论"],
            "论证链必须依次为问题、论点、证据、反驳、结论")
    for item in chain:
        validate_summary(item, blocks, f"chain.{item['stage']}")
    for key in ("one_sentence", "strongest", "weakest"):
        validate_summary(overview.get(key), blocks, key, only_analysis=key != "one_sentence")
    return blocks


def reference_links(ids):
    return '<div class="refs">' + "".join(
        f'<a href="#{esc(ref)}" aria-label="查看依据 {esc(ref)}">↗ {esc(ref)}</a>'
        for ref in dict.fromkeys(ids)) + "</div>"


def evidence_html(items):
    return "".join(
        f'<blockquote class="source-quote" lang="en">{esc(item["quote"])}</blockquote>'
        + reference_links([item["ref"]]) for item in items)


def analysis_html(item):
    return (f'<p>{esc(item["text"])}</p><p class="reason">推理 / 边界：{esc(item["reason"])}</p>'
            + reference_links(item["refs"]))


def summary_html(item, show_label=True):
    label = "Paper" if item["type"] == "paper" else "Analysis"
    prefix = f'<span class="tag">[{label}]</span>' if show_label else ""
    if item["type"] == "paper":
        return prefix + f'<p>{esc(item["text"])}</p>' + evidence_html(item["evidence"])
    return prefix + analysis_html(item)


def marked_slice(value, start, end, ranges):
    out, position = [], 0
    position = start
    for left, right, category in ranges:
        left, right = max(left, start), min(right, end)
        if left >= right:
            continue
        out.append(esc(value[position:left]))
        out.append(f'<mark class="{category}" title="{CATEGORIES[category]}">{esc(value[left:right])}</mark>')
        position = right
    out.append(esc(value[position:end]))
    return "".join(out)


CITATION_GROUP = re.compile(
    r"\[(?P<items>[1-9][0-9]*(?:\s*[-–—]\s*[1-9][0-9]*)?"
    r"(?:\s*[,;，；]\s*[1-9][0-9]*(?:\s*[-–—]\s*[1-9][0-9]*)?)*)\]")
CITATION_ITEM = re.compile(r"([1-9][0-9]*)(?:\s*[-–—]\s*([1-9][0-9]*))?")


def linked_text(block, language, references, used_ids):
    value = block[language]
    marks = highlight_ranges(block) if language == "en" else []
    if block["kind"] == "reference" or not block.get("link_citations", True):
        return marked_slice(value, 0, len(value), marks)
    out, position, count = [], 0, 0
    for group in CITATION_GROUP.finditer(value):
        for item in CITATION_ITEM.finditer(group["items"]):
            first = int(item[1])
            last = int(item[2]) if item[2] else first
            # Bound range length by the actual bibliography before enumerating.
            if last < first or last - first >= len(references):
                continue
            if not all(number in references for number in range(first, last + 1)):
                continue
            start = group.start("items") + item.start()
            end = group.start("items") + item.end()
            count += 1
            cid = f"citation-{block['id']}-{language}-{count}"
            while cid in used_ids:
                cid += "-x"
            used_ids.add(cid)
            label = f"查看参考文献 {value[start:end]}"
            if first != last:
                label += f"（从第 {first} 条开始）"
            out.append(marked_slice(value, position, start, marks))
            out.append(f'<a class="citation-link" id="{cid}" href="#{references[first]}" '
                       f'aria-label="{esc(label)}" title="{esc(label)}">'
                       + marked_slice(value, start, end, marks) + "</a>")
            position = end
    out.append(marked_slice(value, position, len(value), marks))
    return "".join(out)


def media_html(media, content_dir):
    raw = media["path"]
    require(not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw), "媒体必须为本地文件")
    path = Path(raw)
    if not path.is_absolute():
        path = content_dir / path
    path = path.resolve()
    suffix = path.suffix.lower()
    require(suffix in MEDIA_TYPES, f"不支持媒体格式: {suffix}")
    require(path.is_file(), f"媒体不存在: {path}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return (f'<figure><img src="data:{MEDIA_TYPES[suffix]};base64,{encoded}" alt="{esc(media["alt"])}">'
            f'<figcaption>{esc(media["alt"])}</figcaption></figure>')


def render_block(block, content_dir, references, used_ids):
    bid = block["id"]
    original = linked_text(block, "en", references, used_ids)
    translation = linked_text(block, "zh", references, used_ids)
    return_control = ('<div class="citation-return" hidden><button type="button">'
                      '↩ 返回刚才的引文</button></div>' if block["kind"] == "reference" else "")
    media = media_html(block["media"], content_dir) if block.get("media") else ""
    uncertainty = (f'<div class="uncertainty">提取 / 来源提示：{esc(block["uncertainty"])}</div>'
                   if block.get("uncertainty") else "")
    paper_items = "".join(
        f'<li><p>{esc(item["text"])}</p>{evidence_html(item["evidence"])}</li>'
        for item in block["author"])
    paper = (f'''<div class="note-card paper-card" data-provenance="paper">
<h3 class="note-title">作者明确说的 <span class="tag">[Paper]</span></h3>
<p class="note-explainer">原文中的明确陈述或忠实转述；不代表已被独立核实。</p>
<ol>{paper_items}</ol></div>''' if paper_items else "")
    analysis_items = ""
    for key, label in SLOTS.items():
        item = block["analysis"][key]
        if item is not None:
            analysis_items += f'<div class="analysis-item"><strong>{label}</strong>{analysis_html(item)}</div>'
    analysis = (f'''<div class="note-card analysis-card" data-provenance="analysis">
<h3 class="note-title">模型推断的 <span class="tag">[Analysis]</span></h3>
<p class="note-explainer">下列功能、逻辑角色及评价为模型解读，并非作者原话。</p>
{analysis_items}</div>''' if analysis_items else "")
    external = ""
    if block.get("external"):
        external = '<div class="note-card external-card"><h3 class="note-title">外部补充 <span class="tag">[External]</span></h3>'
        for item in block["external"]:
            external += (f'<p>{esc(item["text"])}</p><a href="{esc(item["url"])}" target="_blank" '
                         f'rel="noopener noreferrer">{esc(item["citation"])}</a>')
        external += "</div>"
    cards = paper + analysis + external
    notes = f'<aside class="notes" aria-label="{bid} 的逐段批注">{cards}</aside>' if cards else ""
    row_class = "paragraph-row" if cards else "paragraph-row no-notes"
    return f'''<article class="{row_class}" id="{bid}" data-kind="{esc(block['kind'])}">
<div class="bilingual"><div class="source-locator"><a href="#{bid}">{bid}</a><span>{esc(block['locator']['label'])}</span></div>
{return_control}<div class="original" lang="en">{original}</div>{media}
<div class="translation" lang="zh-CN"><span class="lang-label">中文译文</span>{translation}</div>{uncertainty}</div>
{notes}</article>'''


def font_css(font_path, family):
    path = Path(font_path).resolve()
    require(path.is_file(), f"字体不存在: {path}")
    formats = {".ttf": ("font/ttf", "truetype"), ".otf": ("font/otf", "opentype"),
               ".woff": ("font/woff", "woff"), ".woff2": ("font/woff2", "woff2")}
    require(path.suffix.lower() in formats, f"不支持字体格式: {path.suffix}")
    mime, fmt = formats[path.suffix.lower()]
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return (f'@font-face{{font-family:"{family}";font-style:normal;font-weight:100 900;'
            f'font-display:swap;src:url("data:{mime};base64,{b64}") format("{fmt}");}}', path)


def build(data, content_dir, lora_font=None, plex_font=None):
    blocks = validate(data)
    references = bibliography_index(blocks)
    used_ids = set(blocks) | RESERVED | {s["id"] for s in data["sections"]}
    styles, font_notes, licenses, seen_licenses = [], [], [], set()
    for family, override, filename in [
        ("Lora", lora_font, "Lora.ttf"), ("IBM Plex Sans", plex_font, "IBMPlexSans.ttf")
    ]:
        path = Path(override) if override else SKILL_DIR / "assets" / "fonts" / filename
        if override or path.is_file():
            css, resolved = font_css(path, family)
            styles.append(css)
            font_notes.append(f"{family} 已内嵌")
            for license_name in ("OFL.txt", "LICENSE.txt", filename + ".license.txt"):
                license_path = resolved.parent / license_name
                if license_path.is_file() and license_path not in seen_licenses:
                    licenses.append(f'<details><summary>{esc(family)} 字体许可</summary><pre class="font-license">'
                                    + esc(license_path.read_text(encoding="utf-8")) + "</pre></details>")
                    seen_licenses.add(license_path)
        else:
            font_notes.append(f"{family} 未内嵌；优先使用本机字体，否则回退系统字体")
    nav, body = [], []
    for section in data["sections"]:
        nav.append(f'<a href="#{section["id"]}">{esc(section["title"])}</a>')
        rows = "".join(render_block(b, content_dir, references, used_ids) for b in section["blocks"])
        if section.get("collapsed"):
            inner = f'<details><summary class="section-heading">{esc(section["title"])}</summary>{rows}</details>'
        else:
            inner = f'<h2 class="section-heading">{esc(section["title"])}</h2>{rows}'
        body.append(f'<section class="reading-section" id="{section["id"]}">{inner}</section>')
    source = data["source"]
    scope_label = {"full": "所声明全文范围已覆盖", "excerpt": "节选阅读 · 不代表全文", "incomplete": "不完整阅读稿 · 存在缺失"}[source["scope"]]
    source_note = (f'<p class="status">{scope_label}</p><p>{esc(data["bibliography"])}</p>'
                   f'<p><strong>来源：</strong>{esc(source["description"])} · {esc(source["mode"])}</p>'
                   f'<p><strong>覆盖范围：</strong>{esc(source["coverage"])}</p>'
                   f'<p>已处理 {len(blocks)} / 清单 {len(source["expected_block_ids"])} 个来源块。'
                   '作者陈述与模型分析分区显示。</p>')
    for title, values in [("来源说明", source["notes"]), ("缺失 / 待核验", source["missing"]), ("字体", font_notes)]:
        if values:
            source_note += f'<p><strong>{title}</strong></p><ul>' + "".join(f"<li>{esc(v)}</li>" for v in values) + "</ul>"
    overview = data["overview"]
    chain = "".join(
        f'<div class="chain-card" data-provenance="{item["type"]}">'
        f'<div class="chain-stage">{index:02d} · {esc(item["stage"])}</div>{summary_html(item)}</div>'
        for index, item in enumerate(overview["chain"], 1))
    values = {
        "TITLE": esc(data["title"]), "COURSE": esc(data["course"]),
        "FONT_CSS": "\n".join(styles), "NAV": "".join(nav), "SOURCE_NOTE": source_note,
        "BODY": "\n".join(body), "CHAIN": chain,
        "ONE_ATTR": f'data-provenance="{overview["one_sentence"]["type"]}"',
        "ONE": summary_html(overview["one_sentence"]),
        "STRONGEST": summary_html(overview["strongest"], False),
        "WEAKEST": summary_html(overview["weakest"], False), "LICENSES": "\n".join(licenses),
    }
    template = (SKILL_DIR / "assets" / "reader.html").read_text(encoding="utf-8")
    require(set(re.findall(r"@@([A-Z_]+)@@", template)) == set(values), "模板字段与生成器不一致")
    return re.sub(r"@@([A-Z_]+)@@", lambda match: values[match[1]], template)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--lora-font", type=Path)
    parser.add_argument("--plex-font", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.content.read_text(encoding="utf-8-sig"))
        blocks = validate(data)
        if args.validate_only:
            build(data, args.content.resolve().parent, args.lora_font, args.plex_font)
            print(f"PASS: {len(blocks)} blocks; source references and renderer inputs valid.")
            return 0
        require(args.output is not None, "请指定 --output 或 --validate-only")
        rendered = build(data, args.content.resolve().parent, args.lora_font, args.plex_font)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"PASS: {len(blocks)} blocks; wrote {args.output.resolve()}")
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
