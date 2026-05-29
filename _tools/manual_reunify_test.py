#!/usr/bin/env python3
"""手动 reunify 一篇 doc，套 ai_reunify.validate() 校验，写到 reunify_preview/。

策略：从原文做 surgical 删除——只删跟 frontmatter 重复的字段 dump
+ 重复的次级章节，保留所有叙事/列表/诗号 + 独有信息。
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_reunify import validate


def reunify_huaipomeng(orig: str) -> str:
    """对 槐破梦.md 做 surgical 删除，保留 swatch（用户明示）。"""
    lines = orig.split("\n")
    h2_idx = next(i for i, l in enumerate(lines) if l.startswith("## 【补充来源:霹雳官网"))
    bg_idx = next(i for i, l in enumerate(lines[h2_idx:], h2_idx) if l == "### 角色背景")
    # 找 swatch 块（**代表颜色** 起 / 含 bdx-swatch 的行止）
    swatch_label = next((i for i, l in enumerate(lines[bg_idx:], bg_idx)
                         if l == "**代表颜色**"), None)
    swatch_lines: list[str] = []
    if swatch_label is not None:
        i = swatch_label + 1
        while i < len(lines):
            ls = lines[i].strip()
            if "bdx-swatch" in ls:
                swatch_lines.append(lines[i])
                i += 1
            elif not ls:
                i += 1
            else:
                break
    # 笑战诗号
    poem_idx = next(i for i, l in enumerate(lines[bg_idx:], bg_idx)
                    if l.startswith("槐破梦笑看圣魔之战"))
    poem_end_idx = next(i for i, l in enumerate(lines[poem_idx:], poem_idx)
                        if l.startswith("### 人物关系"))

    # 输出：L1 到 ### 角色背景 之前 + 保留 swatch（带 **代表颜色** 标签）+ 笑战诗号
    keep = lines[:bg_idx]
    if swatch_lines:
        keep.append("")
        keep.append("**代表颜色**")
        keep.append("")
        keep.extend(swatch_lines)
    keep.append("")
    keep.extend(lines[poem_idx:poem_end_idx])
    while keep and not keep[-1].strip():
        keep.pop()
    return "\n".join(keep) + "\n"


def main():
    src = Path("docs/角色/pili/槐破梦.md")
    orig = src.read_text(encoding="utf-8")
    new = reunify_huaipomeng(orig)

    preview_dir = Path("_tools/reunify_preview")
    preview_dir.mkdir(exist_ok=True)
    out_path = preview_dir / "槐破梦.md"
    out_path.write_text(new, encoding="utf-8")

    print(f"原文: {len(orig)} 字 / 输出: {len(new)} 字 / 删: {len(orig)-len(new)} ({(len(orig)-len(new))/len(orig)*100:.1f}%)")

    ok, reason = validate(orig, new)
    print(f"校验: {'✓ PASS' if ok else '✗ FAIL'} — {reason}")
    print(f"\n预览路径: {out_path}")


if __name__ == "__main__":
    main()
