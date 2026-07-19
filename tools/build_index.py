# -*- coding: utf-8 -*-
"""预编译 ModSDK 索引文件。

读取 interface.json / events.json / Markdown 文档 / 枚举值，
把原 docs_reader + server 的解析与格式化逻辑在构建时跑完，
输出 api_index.json（按名查全量文本）和 api_listings.txt（grep 式搜索）。

用法：
    python build_index.py [--source D:\\netease-modsdk-wiki] [--output ..\\data]
"""
import argparse
import json
import re
from pathlib import Path

DEFAULT_SOURCE = r"D:\netease-modsdk-wiki"
DEFAULT_OUTPUT = str(Path(__file__).resolve().parent.parent / "data")


# ============================================================
# Markdown 章节解析（移植自 docs_reader._parse_sections）
# ============================================================

class Section(object):
    def __init__(self, title, level):
        self.title = title
        self.level = level
        self.content = ""


def parse_sections(content):
    """解析 Markdown 章节（代码块围栏内不解析标题）。"""
    sections = []
    lines = content.split("\n")
    current_section = None
    current_content = []
    in_code_block = False

    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            current_content.append(line)
            continue
        header_match = None if in_code_block else re.match(r"^(#{1,6})\s+(.+)$", line)
        if header_match:
            if current_section:
                current_section.content = "\n".join(current_content).strip()
                sections.append(current_section)
            level = len(header_match.group(1))
            title = header_match.group(2).strip()
            current_section = Section(title, level)
            current_content = []
        else:
            current_content.append(line)

    if current_section:
        current_section.content = "\n".join(current_content).strip()
        sections.append(current_section)

    return sections


def load_markdown_docs(docs_path):
    """加载接口/事件目录下的所有 Markdown 文档，返回 {rel_path: [Section...]}。"""
    documents = {}
    for subdir in ("接口", "事件"):
        search_dir = docs_path / subdir
        if not search_dir.exists():
            continue
        for md_file in sorted(search_dir.rglob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            # 去掉 YAML front matter
            if content.startswith("---"):
                end_idx = content.find("---", 3)
                if end_idx != -1:
                    content = content[end_idx + 3:].strip()
            rel_path = str(md_file.relative_to(docs_path))
            documents[rel_path] = parse_sections(content)
    return documents


# ============================================================
# notes / example 提取（移植自 docs_reader._parse_notes_and_example）
# ============================================================

def parse_notes_and_example(content):
    """从文档 section 内容中提取备注和示例。

    文档有两种段标记格式：
      A) "- 备注" / "- 示例"（连写，备注条目缩进4空格 "    - "）
      B) "-" 单行 + 空行 + "备注"（分隔，备注条目顶格 "- "）
    """
    notes = []
    example = ""

    SEC_NAMES = r'(?:描述|参数|返回值|备注|示例|成员变量|继承关系|状态)(?=\s|$)'
    SEC_MARK = r'(?:^- ' + SEC_NAMES + r'|^-\s*\n\s*' + SEC_NAMES + r')'

    # 备注段
    notes_start = re.search(r'(?:- 备注|^-\s*\n\s*备注)', content, re.MULTILINE)
    if notes_start:
        rest = content[notes_start.end():]
        next_sec = re.search(SEC_MARK, rest, re.MULTILINE)
        notes_text = rest[:next_sec.start()] if next_sec else rest
        items = []
        for line in notes_text.split('\n'):
            if not line.strip():
                continue
            if line.lstrip().startswith('- '):
                items.append(line.lstrip()[2:])
            elif items:
                items[-1] += '\n' + line
        notes = items

    # 示例段
    example_start = re.search(r'(?:- 示例|^-\s*\n\s*示例)', content, re.MULTILINE)
    if example_start:
        rest = content[example_start.end():]
        code_match = re.search(r'```(?:python)?\n(.*?)(?:```|$)', rest, re.DOTALL)
        if code_match:
            example = code_match.group(1).strip()

    return notes, example


# ============================================================
# 枚举值加载 + 内联展开（移植自 docs_reader 的三个函数）
# ============================================================

def load_enum_data(docs_path):
    """扫描 枚举值/*.md，返回 (enum_data, enum_descs)。
    enum_data: {name: [(name, value, comment), ...]}
    enum_descs: {name: 描述文字}
    """
    enum_dir = docs_path / "枚举值"
    if not enum_dir.exists():
        return {}, {}

    enum_data = {}
    enum_descs = {}
    for md_file in enum_dir.glob("*.md"):
        if md_file.name == "索引.md":
            continue
        enum_name = md_file.stem
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue

        # 提取描述段（兼容两种格式：A: "- 描述"，B: "-\n\n描述"）
        desc = extract_enum_desc(content)
        if desc:
            enum_descs[enum_name] = desc

        entries = []
        in_code_block = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("```python"):
                in_code_block = True
                continue
            if stripped.startswith("```") and in_code_block:
                break
            if not in_code_block:
                continue
            if stripped.startswith("class ") or not stripped:
                continue
            match = re.match(
                r'([A-Za-z_]\w*)\s*=\s*([^#\n]+?)(?:\s*#\s*(.*))?$', stripped)
            if match:
                name = match.group(1).strip()
                value = match.group(2).strip().strip('"\'')
                comment = (match.group(3) or "").strip()
                entries.append((name, value, comment))

        if entries:
            enum_data[enum_name] = entries
    return enum_data, enum_descs


def extract_enum_desc(content):
    """从枚举 md 提取描述段文字，兼容两种段标记格式。"""
    SEC_NAMES = r'(?:描述|参数|返回值|备注|示例|成员变量|继承关系|状态)(?=\s|$)'
    SEC_MARK = r'(?:^- ' + SEC_NAMES + r'|^-\s*\n\s*' + SEC_NAMES + r')'
    desc_start = re.search(r'(?:- 描述|^-\s*\n\s*描述)', content, re.MULTILINE)
    if not desc_start:
        return ""
    rest = content[desc_start.end():]
    next_sec = re.search(SEC_MARK, rest, re.MULTILINE)
    desc_text = rest[:next_sec.start()] if next_sec else rest
    # 取第一段非空行（描述通常就一行）
    for line in desc_text.strip().splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def get_enum_inline(enum_data, enum_name):
    """紧凑内联字符串：≤20 全列，>20 摘要提示（用 get_api_detail 查）。"""
    entries = enum_data.get(enum_name)
    if not entries:
        return None
    if len(entries) <= 20:
        return ", ".join("{}={}".format(name, value) for name, value, _ in entries)
    else:
        preview = ", ".join("{}={}".format(name, value) for name, value, _ in entries[:10])
        return "{}, ... (共{}个，用 get_api_detail '{}' 查看完整列表)".format(
            preview, len(entries), enum_name)


def try_inline_enum(enum_data, text):
    """检测文本中的枚举引用，返回内联字符串。"""
    if not text:
        return None
    patterns = [
        r'\[([A-Za-z]\w+?)枚举\]',
        r'枚举值文档的\[([A-Za-z]\w+?)\]',
        r'\[([A-Za-z]\w+?)\]\([^)]*枚举值',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            enum_name = match.group(1)
            inline = get_enum_inline(enum_data, enum_name)
            if inline:
                return "  - {}: {}".format(enum_name, inline)
    return None


# ============================================================
# 加载结构化 API/事件数据 + notes/example 回填
# ============================================================

def load_api_entries(docs_path, documents):
    """加载 interface.json / events.json，回填 notes/example。

    返回 {name_lower: [entry_dict, ...]}，entry_dict 含格式化所需的全部字段。
    """
    entries_by_name = {}

    def add_entry(method, class_path, entry_type):
        name = method["name"]
        entry = {
            "name": name,
            "type": entry_type,
            "side": method.get("side", ""),
            "category": "/".join(method.get("doc_class_path", [])),
            "desc": method.get("desc", ""),
            "params": method.get("param", []),
            "return": method.get("return", {}),
            "class_path": class_path,
            "notes": None,   # 待回填
            "example": "",   # 待回填
        }
        entries_by_name.setdefault(name, []).append(entry)

    interface_path = docs_path / "interface.json"
    if interface_path.exists():
        data = json.loads(interface_path.read_text(encoding="utf-8"))
        for class_path, methods in data.items():
            for method in methods:
                add_entry(method, class_path, "api")

    events_path = docs_path / "events.json"
    if events_path.exists():
        data = json.loads(events_path.read_text(encoding="utf-8"))
        for event_path, events in data.items():
            for event in events:
                add_entry(event, event_path, "event")

    # 构建 name_lower -> [entries] 映射（同名单端会有多个）
    name_lower_map = {}
    for entries in entries_by_name.values():
        for entry in entries:
            name_lower_map.setdefault(entry["name"].lower(), []).append(entry)

    # 从文档 sections 回填 notes/example
    # 移植自 docs_reader._load_structured_data 第 453-488 行
    for sections in documents.values():
        for i, sec in enumerate(sections):
            keys = name_lower_map.get(sec.title.lower())
            if not keys:
                continue
            sub_blocks = []
            for j in range(i + 1, len(sections)):
                if sections[j].level <= sec.level:
                    break
                sub_blocks.append((sections[j].title, sections[j].content))
            for entry in keys:
                if entry["notes"] is not None:
                    continue
                if entry["type"] == "event":
                    target = sec.content
                    for title, block in sub_blocks:
                        if entry["side"] and entry["side"][:2] in title:
                            target = block
                            break
                    entry["notes"], entry["example"] = parse_notes_and_example(target)
                    continue
                if entry["class_path"]:
                    blocks = sub_blocks or [("", sec.content)]
                    for title, block in blocks:
                        if entry["class_path"] in block:
                            entry["notes"], entry["example"] = parse_notes_and_example(block)
                            break

    return entries_by_name


# ============================================================
# 格式化（严格复刻 server.py 第 1594-1635 行 get_api_detail 拼接）
# ============================================================

def format_api_entry(entry, enum_data):
    """格式化单条 API/事件，与原 get_api_detail 输出逐字一致。"""
    output = ""
    side = entry.get("side", "")
    output += "### {} ({})\n".format(entry["name"], side)
    output += "- 类型: {} | 分类: {}\n".format(entry["type"], entry.get("category") or "无")
    output += "- 描述: {}\n".format(entry["desc"])

    if entry.get("params"):
        param_strs = []
        enum_notes = []
        for p in entry["params"]:
            pname = p.get("param_name", "")
            ptype = p.get("param_type", "")
            pcomment = p.get("param_comment", "")
            param_strs.append("  - `{}`({}){}".format(
                pname, ptype, " — " + pcomment if pcomment else ""))
            inline = try_inline_enum(enum_data, pcomment)
            if inline:
                enum_notes.append(inline)
        output += "- 参数:\n" + "\n".join(param_strs) + "\n"
        if enum_notes:
            output += "- 枚举值:\n" + "\n".join(enum_notes) + "\n"

    ret = entry.get("return", {})
    if ret:
        rtype = ret.get("return_type", "")
        rcomment = ret.get("return_comment", "")
        if rtype:
            output += "- 返回: `{}`{}\n".format(rtype, " — " + rcomment if rcomment else "")

    notes = entry.get("notes") or []
    if notes:
        output += "- 备注:\n"
        for note in notes:
            output += "  - {}\n".format(note)

    example = entry.get("example", "")
    if example:
        output += "- 示例:\n```python\n{}\n```\n".format(example)

    output += "\n"
    return output


def format_enum_entry(enum_name, entries):
    """格式化枚举值完整列表（全量，无压缩）。"""
    lines = ["{}（枚举值，共{}个）".format(enum_name, len(entries))]
    for name, value, comment in entries:
        if comment:
            lines.append("    {} = {}    # {}".format(name, value, comment))
        else:
            lines.append("    {} = {}".format(name, value))
    return "\n".join(lines) + "\n"


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="预编译 ModSDK 索引")
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="输入根目录（默认 {}）".format(DEFAULT_SOURCE))
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help="输出目录（默认 {}）".format(DEFAULT_OUTPUT))
    args = parser.parse_args()

    docs_path = Path(args.source) / "docs"
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("加载 Markdown 文档 ...")
    documents = load_markdown_docs(docs_path)
    print("  {} 个文档".format(len(documents)))

    print("加载枚举值 ...")
    enum_data, enum_descs = load_enum_data(docs_path)
    print("  {} 个枚举".format(len(enum_data)))

    print("加载 API/事件数据并回填 notes/example ...")
    entries_by_name = load_api_entries(docs_path, documents)
    total_entries = sum(len(v) for v in entries_by_name.values())
    print("  {} 个名称，{} 条记录".format(len(entries_by_name), total_entries))

    # 构建 api_index.json
    print("格式化索引 ...")
    index = {}
    for name, entries in entries_by_name.items():
        if len(entries) > 1:
            text = "## `{}` 详情\n\n".format(name)
        else:
            text = ""
        text += "".join(format_api_entry(e, enum_data) for e in entries)
        index[name] = [text]

    # 枚举值也加入索引（key=枚举名，value=[完整列表文本]）
    for enum_name, entries in enum_data.items():
        index[enum_name] = [format_enum_entry(enum_name, entries)]

    # 构建 api_listings.txt：名称<TAB>类型<TAB>端侧<TAB>描述
    listings = []
    for name, entries in entries_by_name.items():
        for entry in entries:
            listings.append("{}\t{}\t{}\t{}".format(
                name, "接口" if entry["type"] == "api" else "事件",
                entry["side"], entry["desc"]))
    for enum_name, entries in enum_data.items():
        listings.append("{}\t枚举\t\t{}".format(
            enum_name, enum_descs.get(enum_name, "枚举值定义")))

    # 写出
    index_path = output_dir / "api_index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print("写出 {} ({} KB)".format(index_path, index_path.stat().st_size // 1024))

    listings_path = output_dir / "api_listings.txt"
    listings_path.write_text("\n".join(listings), encoding="utf-8")
    print("写出 {} ({} KB, {} 行)".format(
        listings_path, listings_path.stat().st_size // 1024, len(listings)))

    print("完成。")


if __name__ == "__main__":
    main()
