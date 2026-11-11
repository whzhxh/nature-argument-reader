# HTML 内容数据合同

生成脚本仅依赖 Python 标准库，UTF-8 JSON 输入，UTF-8 HTML 输出。
JSON 中所有正文都是纯文本，自动 HTML 转义；不要放 Markdown 或可执行 HTML。
正文中的特殊数学符号可用 Unicode，复杂公式用媒体截图。
ID 使用字母开头的 ASCII 字母、数字、下划线或短横线，全文件唯一。

## 根结构

```json
{
  "title": "Source paper title",
  "course": "课程信息未提供",
  "bibliography": "作者、年份、期刊或预印本版本（仅已知信息）",
  "source": {
    "description": "用户上传的 manuscript.pdf",
    "mode": "page-grounded",
    "scope": "full",
    "coverage": "用户提供的正文、图注及参考文献；不包含另行发布的补充材料",
    "expected_block_ids": ["S001"],
    "missing": [],
    "notes": []
  },
  "sections": [
    {
      "id": "introduction",
      "title": "1 Introduction / 引言",
      "collapsed": false,
      "blocks": []
    }
  ],
  "overview": {
    "chain": [],
    "one_sentence": {},
    "strongest": {},
    "weakest": {}
  }
}
```

`source.scope`：

- `full`：所声明范围全覆盖，`expected_block_ids` 非空且精确覆盖全部块，无 missing。
  该清单必须在提取阶段由原文建立，不能从生成的译文反向推定。
- `excerpt`：用户选择的节选；仍需精确清单，不分析未提供全文。
- `incomplete`：有缺页、缺块、未完成翻译等；missing 必须非空，清单可包含缺失 ID。

`source.mode`：

- `page-grounded`：每个块有正整数 `locator.pdf_page`，允许可选 `printed_page`。
- `structure-grounded`：每个块有真实章节/段落定位，禁止设置 `pdf_page`。
- `source-limited`：摘要或片段，禁止设置 `pdf_page`，scope 不得为 full。

`locator.label` 始终必需，供用户阅读，禁止把生成块号伪装成原刊的页码或行号。
`expected_block_ids` 保留提取阶段的完整块清单。缺失项在 missing 中解释。
如果只能确认节选就声明 excerpt，不把未知全文页数填成 1。

## 段落 / 图注块

```json
{
  "id": "S001",
  "kind": "paragraph",
  "locator": {"label": "PDF p. 2 · Introduction · ¶3", "pdf_page": 2},
  "en": "Exact source paragraph.",
  "zh": "信息完整、自然流畅的中文意译。",
  "highlights": [
    {"category": "thesis", "quote": "Exact source", "occurrence": 1}
  ],
  "author": [
    {
      "text": "忠实转述作者在原文中明确说出的内容。",
      "evidence": [{"ref": "S001", "quote": "Exact source paragraph."}]
    }
  ],
  "analysis": {
    "function": {
      "text": "引出研究问题。",
      "reason": "这一句先描述已有条件，再引出尚未解释的现象。",
      "refs": ["S001"]
    },
    "logic": {
      "text": "从研究背景推进到需要解决的空白。",
      "reason": "其范围限定为本研究考察的对象，后文贡献需要回应这个空白。",
      "refs": ["S001"]
    },
    "technique": null,
    "caveat": null
  },
  "uncertainty": ""
}
```

- 每块 `en`、`zh` 非空，`kind` 可为 `paragraph`、`caption`、`figure`、
  `table`、`equation`、`reference`、`statement`。
- `author` 必须存在，可为空数组，此时页面省略作者批注卡，不显示占位语。
- 每个 author 项含至少一条 evidence，短引必须逐字匹配对应 ref 块的 `en`。
  允许跨块引用，但不能用只含术语的孤立短引支持复杂转述。
- `analysis` 四个槽位必须存在。function 和 logic 为非空对象，
  technique、caveat 无有意义发现时为 null；null 项不生成标题、分隔线或占位文字。
  整张批注卡没有内容时省略，整栏为空时不预留空侧栏。
  缺失或不确定的信息仍通过 source.missing / uncertainty 明确保留。
- 非空分析项必须有 `text`（判断）、`reason`（推理/适用范围）、
  `refs`（一个或多个真实块 ID）。边界不确定时在 reason 中写明。
- `highlights` 可空。类别只有 thesis / term / evidence / concession / method。
  quote 按原文原样匹配，重复短语以 occurrence（1 起算）选择；
  同一字符不能被两个高亮覆盖。
- `uncertainty` 为可选字符串；保留原文未识别符号，明确不确定位置。
- 作者在图注中给出的解释仍是 Paper，而非自动变成模型推断。
  模型评价这段解释是否成立才属于 Analysis。

## 深入分析项（兼容既有四槽位）

`analysis` 可增加 `insights` 数组。缺省为空，不改变旧输入的有效性。
有深入分析时优先显示这些内容，原四槽位收进“段落作用与论证衔接”。
按 [deep-analysis.md](deep-analysis.md) 选择视角，不为每段强填相同数量。
默认只展开第一条判断；该条的推导、影响和核验可展开，其余视角收进“更多分析”。
没有深入项时只展示段落功能概述，四槽位详情仍可展开。作者短引默认折叠，
锚点仍可见；这只改变显示方式，不删除原文依据或分析。

```json
{
  "analysis": {
    "function": {"text": "提出机制。", "reason": "从设计目标进入状态更新过程。", "refs": ["S001"]},
    "logic": {"text": "连接设计与验证。", "reason": "后文实验要检验该机制的预期效果。", "refs": ["S001"]},
    "technique": null,
    "caveat": null,
    "insights": [
      {
        "lens": "mechanism",
        "title": "比较必须先于不可逆状态更新",
        "text": "此处的关键条件是第一次计算结果只进入影子状态。",
        "reason": "若第一次已更新被第二次读取的状态，两次结果差异也可能来自输入变化。",
        "implication": "是否在比较前隔离状态决定了机制解释是否成立。",
        "check": "沿状态写使能核对首次执行、比较与最终提交的先后顺序。",
        "refs": ["S001"]
      }
    ]
  }
}
```

每条必须有合法 `lens`、`title`、`text`、`reason`、`implication` 及非空真实
`refs`；`check` 可省略，有值时不得为空。可选 lens：
mechanism / evidence / assumption / comparison / quantitative / alternative /
boundary / reproducibility / connection。所有文本为纯文本并转义。
脚本验证字段和定位，不验证推导的科学正确性，也不自动生成分析。

Paper 和 Analysis 标题下的来源解释分别只在全文各自首张非空卡显示一次；
后续卡仍保留来源标签。每次生成独立计数，不以浏览器存储记忆。

## 正文引文与参考文献跳转

每条参考文献使用独立的 `kind: "reference"` 块和稳定 ID，例如 `R01`。
生成器从该块英文开头的 `[1]` 识别编号；其他编号格式需填写
`"reference_number": 1`。编号必须唯一且与原文方括号编号一致，
不按块的排列顺序猜测编号。作者—年份制不自动转换为数字引用。

英文及中文正文中 `[1]`、`[1, 3]`、`[1; 3]` 等数字引文自动链接到
对应参考文献。`[2–5]`（也支持短横线及长破折号）在 2 到 5 条均存在时，
链接到第 2 条，从该处查看连续条目；保留原有范围写法，不展开或改写原文。
缺失的编号保留纯文本，不生成失效链接。参考文献块内不再自动链接自身编号。

若某块含有容易与引文混淆的数字数组、区间等，可设置
`"link_citations": false` 关闭该块的自动识别；交付前核对正文数字方括号的用途。
识别不改变英文或译文的文字，英文高亮跨越引文时也保留原有高亮范围。
引文链接为普通 HTML 锚点；启用脚本时会自动展开折叠的参考文献节，
并在所到达条目提供“返回刚才的引文”按钮，回到最近点击的英文或中文引文处。

## 图表链接与悬浮预览

`figure` / `table` 块的英文开头为 `Fig. 2.`、`Figure 2.`、`Table 1.` 等时，
自动建立对应图表索引；带媒体的 caption 块也可作为目标。
非标准图注可填写 `"xref_label": "Fig. 2"` 或 `"xref_label": "Table 1"`，
标签须与 kind 相符，全文唯一，不能按图片文件名或出现次序猜编号。
支持 S1 等补充图号及带字母的子图号。

英中正文的 `Fig. 2b`、`Figure 2(b)`、`图2（b）`、`Table 1`、`表1` 等
会链接到已确认的图表块。若有独立的 2b 块则精确跳到该块；
只有图 2 的整图时跳到整图，并在预览中提示当前显示整图、正文引用子图 b，
不伪造子图裁切。无对应来源的图号保留纯文本。
`"link_figures": false` 仅关闭该块的图表自动链接，不影响参考文献链接。

鼠标悬浮或键盘聚焦图表/参考文献链接时，预览只展示已有原图、原文、
中文译文及来源定位，不混入模型批注，也不查询外部数据。
范围参考文献会逐条预览范围内的条目。点击标号仍跳转到相应来源位置。
鼠标可移入预览窗滚动、缩放图片；Esc 或关闭按钮退出。

定位优先使用当前段落英中正文结束后、同一行内可见且足够宽高的左栏空白；
没有可读空间则使用右侧批注列。悬浮窗不得覆盖任何英中正文，
图片不得为适配狭小空隙缩成缩略图；提供适宽、放大/缩小及原尺寸查看，
放大后在窗内滚动。窄屏或没有安全侧栏空间时改为文档流内展开，
不以覆盖正文的底部浮层替代。滚动、缩放窗口和图片加载后重新计算位置。

## 媒体与外部补充

图/表/公式块在上面字段基础上可增加：

```json
{
  "media": {
    "path": "assets/figure-1.png",
    "alt": "图 1，展示原文所述实验装置"
  }
}
```

路径相对于 JSON 所在目录解析，支持 PNG / JPEG / GIF / WebP / AVIF；
拒绝 URL、SVG、HTML 与不存在的资源。脚本读取媒体并内嵌 data URI，
单个 HTML 无需原目录存在。
媒体块的 en/zh 可放其图注，公式截图的 en/zh 放准确编号和说明。
不要把全部正文合并进一张图片。

必要的外部补充放在该块的可选 `external` 数组中：

```json
{
  "external": [
    {
      "text": "外部材料支持的有限补充；不是本文作者的结论。",
      "citation": "出处名称和年份",
      "url": "https://example.org/source"
    }
  ]
}
```

外部链接只作为可点击出处，不载入资源；没有确切出处就不写 External。

## 底部总览

总览每项的文本均为中文。模型的概括不是作者原句，默认使用 `analysis`。
`type: paper` 仅用于可由原文短引直接支持的忠实转述。

```json
{
  "chain": [
    {
      "stage": "问题",
      "type": "analysis",
      "text": "本文要解决的问题。",
      "reason": "从引言的问题陈述归纳。",
      "refs": ["S001"]
    },
    {
      "stage": "论点",
      "type": "paper",
      "text": "作者直接提出的中心主张。",
      "evidence": [{"ref": "S001", "quote": "Exact source paragraph."}]
    },
    {
      "stage": "证据",
      "type": "analysis",
      "text": "主要证据如何支撑主张。",
      "reason": "指出实验、比较或理论推导支持的具体范围。",
      "refs": ["S001"]
    },
    {
      "stage": "反驳",
      "type": "analysis",
      "text": "所提供材料未见明确反驳。",
      "reason": "在已列出的相关段落中未找到针对异议的直接回应；不据此断言全文不存在。",
      "refs": ["S001"]
    },
    {
      "stage": "结论",
      "type": "analysis",
      "text": "在已研究范围内得到的结论。",
      "reason": "保留实验与论证边界。",
      "refs": ["S001"]
    }
  ],
  "one_sentence": {
    "type": "analysis",
    "text": "作者核心主张的一句话概括。",
    "reason": "综合直接贡献陈述与结果段落。",
    "refs": ["S001"]
  },
  "strongest": {
    "type": "analysis",
    "text": "最强的一处论证。",
    "reason": "说明该证据为什么最直接回应主张，而非笼统赞扬。",
    "refs": ["S001"]
  },
  "weakest": {
    "type": "analysis",
    "text": "最薄弱的一处，或材料不足以确认。",
    "reason": "说明缺口的影响与核查范围；不确定时明确说明。",
    "refs": ["S001"]
  }
}
```

chain 固定五阶段按此顺序呈现，但每阶段据实际论文填写。
strongest / weakest 必须是 analysis，不能伪装成作者自行评定。
段落功能与逻辑角色都是 Analysis，哪怕使用“引出问题”等看似客观的标签。

## 人工验收中不能由脚本替代的部分

脚本检查可引用性、字段和资源，不判断短引是否足以支持中文转述，
不识别译文是否漏掉限定语，不保证提取块清单真的覆盖原文，
也不证明潜在漏洞成立。交付前需逐项核对这些语义条件。

## 随包字体的来源与许可

Lora 与 IBM Plex Sans 的可变字体及各自 OFL 许可于 2026-11-11 取自
Google Fonts 官方仓库 `google/fonts` 的 `ofl/lora` 与 `ofl/ibmplexsans` 目录。
字体仅用于内嵌显示，不修改其内容；许可文本在 `assets/fonts/` 中逐字体保留，
生成 HTML 时一并内嵌。模板为中文配置系统后备字体，无需下载额外中文字体。
