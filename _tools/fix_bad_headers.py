#!/usr/bin/env python3
"""修 raw_baidu/{name}.md 里 "## 前缀+已知section名" 的错误 header。

例：`## 戒珠角色关系` → 把 `戒珠` 移回上段尾，header 改为 `## 角色关系`。
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent / "raw_baidu"

KNOWN_SECTIONS = [
    "角色设定", "人物设定", "形象设定", "角色简介", "人物简介",
    "角色能力", "人物能力", "角色经历", "人物经历", "角色背景",
    "人物背景", "角色关系", "人物关系", "人际关系", "角色形象",
    "人物形象", "角色配乐", "人物配乐", "角色评价", "人物评价",
    "角色发明", "角色身份", "人物身份", "相关作品", "再出诗词",
    "获奖记录", "人物影响", "角色影响", "基本信息", "故事背景",
    "登场剧集", "登场时间", "诗词列表", "出场剧集", "重要事件",
    "基本介绍", "武学招式", "武学列表", "所属组织", "人物诗号",
    "重要事迹", "武学一览", "武学绝技",
]
KS_SORTED = sorted(KNOWN_SECTIONS, key=len, reverse=True)


def fix_file(path: Path) -> int:
    """处理单个文件，返回修复的 header 数量。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    fixed = 0
    new_lines = list(lines)

    for i, line in enumerate(new_lines):
        if not line.startswith("## "):
            continue
        s = line[3:].strip()
        if s == "基本信息（来自百度百科）":
            continue
        if s in KS_SORTED:
            continue
        # 检查是否 endswith 已知 section
        for ks in KS_SORTED:
            if s.endswith(ks) and len(s) > len(ks):
                prefix = s[:-len(ks)]
                # 修 header
                new_lines[i] = f"## {ks}"
                # 把 prefix 移回上一段内容尾
                # 找上一个非空行
                for j in range(i - 1, -1, -1):
                    if new_lines[j].strip():
                        new_lines[j] = new_lines[j].rstrip() + prefix
                        break
                fixed += 1
                break

    if fixed > 0:
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="名字列表；不写则扫所有 raw_baidu/*.md")
    args = ap.parse_args()

    if args.names:
        targets = [RAW_DIR / f"{n}.md" for n in args.names]
    else:
        targets = sorted(RAW_DIR.glob("*.md"))

    total = 0
    for p in targets:
        if not p.exists():
            print(f"  ✗ {p.name}: missing")
            continue
        n = fix_file(p)
        if n:
            print(f"  ✓ {p.stem}: fixed {n} headers")
            total += n
    print(f"\n汇总: fixed {total} headers across {len(targets)} files")


if __name__ == "__main__":
    main()
