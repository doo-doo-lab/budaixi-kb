#!/usr/bin/env python3
"""把"无章节、含 播报编辑 噪音"的旧 raw_baidu 文件后处理成有章节结构的。

针对早期手抓的 MCP 文件，它们把整页内容堆在 `## 基本信息（来自百度百科）` 下，
内含 `{section_name}播报编辑{content}` 这种百度 UI 拼接形式但没拆成章节。

本脚本：
1. 找到 `## 基本信息（来自百度百科）` 段，提取 blob 内容
2. 在 blob 内找所有 `{section}播报编辑` 模式
3. 把 blob 按 section 边界拆开，输出多个 `## {section}` 章节
4. 保留 lead 段（第一个 section 之前的文字）

**全部内容仍是 baidu 原文，仅做格式拆分。**
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent / "raw_baidu"

# 已知 baidu 章节名候选 (常见 4 字 / 3 字 / 2 字)
# 按长度倒序，优先匹配长的（避免 "经历" 错配到 "角色经历"）
KNOWN_SECTIONS = [
    # 5 字
    "角色身世经历", "人物身世经历", "影视小说角色",
    # 4 字
    "角色设定", "人物设定", "形象设定", "角色简介", "人物简介",
    "角色能力", "人物能力", "角色经历", "人物经历", "角色背景",
    "人物背景", "角色关系", "人物关系", "人际关系", "角色形象",
    "人物形象", "角色配乐", "人物配乐", "角色评价", "人物评价",
    "角色发明", "角色身份", "人物身份", "相关作品", "再出诗词",
    "获奖记录", "人物影响", "角色影响", "技能专长", "基本信息",
    "故事背景", "角色历程", "人物历程", "登场剧集", "登场时间",
    "诗词列表", "出场剧集", "重要事件",
    # 3 字
    "经历篇", "招式表",
    # 2 字
    "经历", "能力", "关系", "背景", "形象", "配乐", "评价", "身份",
    "诗词", "武学", "技能",
]
# 转 regex alternative，按长度倒序
KNOWN_SECTIONS_SORTED = sorted(KNOWN_SECTIONS, key=len, reverse=True)
KNOWN_SECTIONS_PATTERN = re.compile(
    r"(" + "|".join(KNOWN_SECTIONS_SORTED) + r")播报编辑"
)
# 退路：通用 2-6 字汉字
FALLBACK_SECTION_PATTERN = re.compile(r"([一-龥]{2,6})播报编辑")


def split_blob_by_baoban(blob: str) -> tuple[str, list[tuple[str, str]]]:
    """把含 播报编辑 markers 的 blob 拆成 (lead, [(section, content)]).

    blob 形如:  "lead文字角色设定播报编辑设定内容角色能力播报编辑能力内容..."
    返回 lead="lead文字", sections=[("角色设定","设定内容"), ("角色能力","能力内容"), ...]
    """
    # 找所有 播报编辑 的位置，优先用 KNOWN_SECTIONS 匹配
    markers = []
    used_positions: set[int] = set()
    # Pass 1: 先用 known sections（高优先级）
    for m in KNOWN_SECTIONS_PATTERN.finditer(blob):
        if m.end() in used_positions:
            continue
        markers.append((m.group(1), m.start(1), m.end()))
        used_positions.add(m.end())
    # Pass 2: fallback 给没匹到 known 的 播报编辑
    for m in FALLBACK_SECTION_PATTERN.finditer(blob):
        if m.end() in used_positions:
            continue
        markers.append((m.group(1), m.start(1), m.end()))
        used_positions.add(m.end())
    # 按位置排序
    markers.sort(key=lambda x: x[1])

    if not markers:
        return blob, []

    # 第一个 marker 之前的是 lead
    first_name_start = markers[0][1]
    lead = blob[:first_name_start].strip()

    sections = []
    for i, (name, name_start, after_marker) in enumerate(markers):
        # content from after this marker to next marker's name_start
        if i + 1 < len(markers):
            content_end = markers[i + 1][1]
        else:
            content_end = len(blob)
        content = blob[after_marker:content_end].strip()
        sections.append((name, content))

    return lead, sections


def fix_file(path: Path) -> str:
    """处理单个 raw_baidu/{name}.md，原地写。返回操作描述。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 找 "## 基本信息（来自百度百科）" 的位置
    base_idx = None
    for i, line in enumerate(lines):
        if line.startswith("## 基本信息（来自百度百科）"):
            base_idx = i
            break
    if base_idx is None:
        return "skip_no_base_section"

    # 找该 section 的 blob 范围 (基本信息标题后 → 下一个 ## 或文件尾)
    blob_start = base_idx + 1
    blob_end = len(lines)
    for j in range(blob_start, len(lines)):
        if lines[j].startswith("## "):
            blob_end = j
            break

    blob = "\n".join(lines[blob_start:blob_end]).strip()

    # 检查是否需要修：blob 里有 "播报编辑" 才需要
    if "播报编辑" not in blob:
        return "skip_no_noise"

    # 拆分
    lead, sections = split_blob_by_baoban(blob)
    if not sections:
        return "skip_no_sections_found"

    # 重建文件：保留 base_idx 之前 + 新的拆分内容 + base_idx 之后未触及的部分（其实没有，blob_end 应该是文件尾或下一个 ##）
    header_lines = lines[:base_idx]  # 标题、来源、空行
    tail_lines = lines[blob_end:]    # base_idx 之后还有的章节（理论上 supplement script 加的 "### 基本信息表" 在这里，但它是 ### 子标题，不会被 blob_end 截断；除非它在另一个 ## 后）

    new_body = []
    new_body.append("## 基本信息（来自百度百科）")
    new_body.append("")
    if lead:
        new_body.append(lead)
        new_body.append("")
    for sec_name, sec_content in sections:
        if not sec_content.strip():
            continue
        new_body.append(f"## {sec_name}")
        new_body.append("")
        new_body.append(sec_content)
        new_body.append("")

    out = "\n".join(header_lines + new_body + tail_lines).rstrip() + "\n"
    path.write_text(out, encoding="utf-8")
    return f"fixed_{len(sections)}_sections"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="名字列表；不写则扫所有 raw_baidu/*.md")
    args = ap.parse_args()

    if args.names:
        targets = [(n, RAW_DIR / f"{n}.md") for n in args.names]
    else:
        targets = [(p.stem, p) for p in sorted(RAW_DIR.glob("*.md"))]

    counts = {"fixed": 0, "skip_no_noise": 0, "skip_other": 0, "missing": 0}
    for name, path in targets:
        if not path.exists():
            counts["missing"] += 1
            print(f"  ✗ {name}: missing")
            continue
        result = fix_file(path)
        if result.startswith("fixed"):
            counts["fixed"] += 1
            print(f"  ✓ {name}: {result}")
        elif result == "skip_no_noise":
            counts["skip_no_noise"] += 1
        else:
            counts["skip_other"] += 1
            if "skip" in result:
                pass  # too noisy
            else:
                print(f"  · {name}: {result}")

    print(f"\n汇总: fixed={counts['fixed']} no_noise={counts['skip_no_noise']} other_skip={counts['skip_other']} missing={counts['missing']}")


if __name__ == "__main__":
    main()
