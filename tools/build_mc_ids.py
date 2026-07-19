# -*- coding: utf-8 -*-
"""自动从 Minecraft Wiki 更新方块/物品/实体/状态效果/附魔的 ID 映射。

数据源：https://zh.minecraft.wiki 的 MediaWiki API（api.php?action=parse）
  - 方块：子页面「基岩版数据值/方块ID」
  - 物品：子页面「基岩版数据值/物品ID/1.16.100后」
  - 实体：子页面「基岩版数据值/实体ID」
  - 状态效果 + 附魔：主页面「基岩版数据值」内嵌（无需懒加载）

输出 data/mc_ids.txt，每行：ID<TAB>类型<TAB>中文名
顺序：方块 → 物品 → 实体 → 状态效果 → 附魔

运行：python build_mc_ids.py
"""
import json
import re
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

API_URL = "https://zh.minecraft.wiki/api.php"
USER_AGENT = "mod-debug-bridge/1.0 (contact@example.com)"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "mc_ids.txt"

# 子页面：API 直接返回完整 HTML 表格
SUBPAGES = [
    ("方块", "基岩版数据值/方块ID"),
    ("物品", "基岩版数据值/物品ID/1.16.100后"),
    ("实体", "基岩版数据值/实体ID"),
]
# 主页面 section：状态效果/附魔内嵌在主页，按 h3 id 切片
MAIN_PAGE = "基岩版数据值"


def fetch_page_html(page_title):
    """通过 api.php?action=parse 获取页面解析后的 HTML。"""
    params = urllib.parse.urlencode({
        "action": "parse",
        "page": page_title,
        "format": "json",
        "prop": "text",
        "disablelimitreport": 1,
    })
    url = API_URL + "?" + params
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if "error" in result:
        raise RuntimeError("API 错误（{}）：{}".format(
            page_title, result["error"].get("info", result["error"])))
    return result["parse"]["text"]["*"]


def strip_tags(html):
    text = re.sub(r"<[^>]+>", "", html)
    return unescape(text).strip()


def extract_name(cell_html):
    """从表格单元格提取中文名：优先 sprite-text > <a> > 纯文本。"""
    m = re.search(r'<span class="sprite-text">(.*?)</span>', cell_html, re.S)
    if m:
        return strip_tags(m.group(1))
    m = re.search(r"<a\b[^>]*>(.*?)</a>", cell_html, re.S)
    if m:
        return strip_tags(m.group(1))
    return strip_tags(cell_html)


def parse_5col(html):
    """图标|Dec|Hex|命名空间ID|名称 五列表格。跳过 colspan 占位行。"""
    results = []
    for tr in re.finditer(r"<tr>(.*?)</tr>", html, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr.group(1), re.S)
        if len(cells) < 5:
            continue
        ns_id = strip_tags(cells[3])
        name = extract_name(cells[4])
        if ns_id and name:
            results.append((ns_id, name))
    return results


def parse_effect(html):
    """状态效果：效果名|ID|命名空间ID|粒子。"""
    results = []
    for tr in re.finditer(r"<tr>(.*?)</tr>", html, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr.group(1), re.S)
        if len(cells) < 3:
            continue
        name = extract_name(cells[0])
        ns_id = strip_tags(cells[2])
        if ns_id and name:
            results.append((ns_id, name))
    return results


def parse_enchant(html):
    """魔咒：中文名|名称(code)|数字ID。"""
    results = []
    for tr in re.finditer(r"<tr>(.*?)</tr>", html, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr.group(1), re.S)
        if len(cells) < 3:
            continue
        name = extract_name(cells[0])
        ns_id = strip_tags(cells[1])
        if ns_id and name:
            results.append((ns_id, name))
    return results


def slice_section(html, start_id, end_id):
    s = html.find('id="{}"'.format(start_id))
    e = html.find('id="{}"'.format(end_id))
    return html[s:e]


def main():
    lines = []

    # 方块/物品/实体：独立子页面
    for type_name, page_title in SUBPAGES:
        print("获取 {} ...".format(page_title))
        html = fetch_page_html(page_title)
        for ns_id, name in parse_5col(html):
            lines.append("{}\t{}\t{}".format(ns_id, type_name, name))

    # 状态效果/附魔：主页面内嵌 section
    print("获取 {} ...".format(MAIN_PAGE))
    main_html = fetch_page_html(MAIN_PAGE)

    effect_chunk = slice_section(main_html, "状态效果ID", "魔咒ID")
    for ns_id, name in parse_effect(effect_chunk):
        lines.append("{}\t状态效果\t{}".format(ns_id, name))

    enchant_chunk = slice_section(main_html, "魔咒ID", "方块状态")
    for ns_id, name in parse_enchant(enchant_chunk):
        lines.append("{}\t附魔\t{}".format(ns_id, name))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    counts = {}
    for line in lines:
        t = line.split("\t")[1]
        counts[t] = counts.get(t, 0) + 1
    print("\n写入 {}（共 {} 行）".format(OUTPUT, len(lines)))
    for t in ("方块", "物品", "实体", "状态效果", "附魔"):
        print("  {}: {}".format(t, counts.get(t, 0)))


if __name__ == "__main__":
    main()
