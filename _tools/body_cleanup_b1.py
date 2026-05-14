#!/usr/bin/env python3
"""B1 机械清理：删 ==== artifact / 重复 H1 / 空 section / 多余空行。

只动 frontmatter 之后的 body。规则保守：
- ==== artifact：整行只有 = 且长度 >=10
- 重复 H1：first `##` 之前、且 strip 后精确等于 H1 名（去消歧义括号）的整行
- 空 section：H2/H3 标题后到下一个同级或更高级标题之间全是空行（下一个是更深标题则保留）
- 3+ 连续空行 → 2

用法：
    python body_cleanup_b1.py                  # dry-run，前 15 篇 diff
    python body_cleanup_b1.py --sample 30
    python body_cleanup_b1.py --filter "步非烟|素还真"
    python body_cleanup_b1.py --apply          # 全量（含 .pre_b1_backup/ 备份）
"""
from __future__ import annotations
import argparse
import difflib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs" / "角色"


def split_frontmatter(text: str) -> tuple[str, str]:
    m = re.match(r"^(---\n.*?\n---\n)", text, re.DOTALL)
    if m:
        return m.group(1), text[len(m.group(1)):]
    return "", text


def clean_body(body: str) -> str:
    lines = body.split("\n")

    # --- 1. 删 ==== artifact 整行 ---
    lines = [l for l in lines if not (l.strip() and set(l.strip()) == {"="} and len(l.strip()) >= 10)]

    # --- 2. 找 H1 名 + first ## 位置 ---
    h1_name = None
    first_h2_idx = len(lines)
    for i, l in enumerate(lines):
        if h1_name is None and l.startswith("# "):
            h1_name = re.sub(r"[（(].*$", "", l[2:].strip()).strip()
        if l.startswith("## "):
            first_h2_idx = i
            break

    # --- 3. 删重复 H1：first ## 之前、strip 精确等于 H1 名的整行 ---
    if h1_name:
        new = []
        for i, l in enumerate(lines):
            if i < first_h2_idx and not l.startswith("# ") and l.strip() == h1_name:
                continue
            new.append(l)
        lines = new

    # --- 4. 删空 section（排除来源接缝标记——那是 B2 的输入）---
    SEAM_MARKERS = ("【补充来源", "来自百度百科", "同一角色别名")
    result = []
    i = 0
    while i < len(lines):
        m = re.match(r"^(#{2,3})\s+\S", lines[i])
        if m and not any(s in lines[i] for s in SEAM_MARKERS):
            level = len(m.group(1))
            j = i + 1
            sec_body = []
            while j < len(lines):
                nm = re.match(r"^(#{1,6})\s+\S", lines[j])
                if nm:
                    break
                sec_body.append(lines[j])
                j += 1
            # 下一个标题是否更深（更深 = 本节有子节，不算空）
            next_deeper = False
            if j < len(lines):
                nm = re.match(r"^(#{1,6})\s+\S", lines[j])
                if nm and len(nm.group(1)) > level:
                    next_deeper = True
            if not next_deeper and all(not x.strip() for x in sec_body):
                i = j  # 跳过空 section 标题 + 空行
                continue
        result.append(lines[i])
        i += 1
    lines = result

    # --- 5. 收敛空行 ---
    body = "\n".join(lines)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = body.lstrip("\n")
    if not body.endswith("\n"):
        body += "\n"
    return body


def process(text: str) -> str:
    fm, body = split_frontmatter(text)
    return fm + clean_body(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=15)
    ap.add_argument("--filter", type=str, default=None)
    args = ap.parse_args()

    docs = []
    for brand in ["pili", "jinguang", "dongli"]:
        for p in sorted((DOCS_DIR / brand).glob("*.md")):
            if p.name == "index.md":
                continue
            docs.append((brand, p))
    if args.filter:
        rx = re.compile(args.filter)
        docs = [(b, p) for b, p in docs if rx.search(p.stem)]

    changed = 0
    shown = 0
    stats = {"==== removed": 0, "dup-H1 removed": 0, "empty-sec removed": 0}

    for brand, p in docs:
        orig = p.read_text(encoding="utf-8")
        new = process(orig)
        if new == orig:
            continue
        changed += 1

        # 统计改了什么
        ob, nb = split_frontmatter(orig)[1], split_frontmatter(new)[1]
        if any(set(l.strip()) == {"="} and len(l.strip()) >= 10 for l in ob.split("\n")):
            stats["==== removed"] += 1
        ol = ob.split("\n")
        nl = nb.split("\n")
        if len(ol) - len(nl) > 0:
            pass  # 行数变化笼统

        if args.apply:
            backup = p.parent / ".pre_b1_backup"
            backup.mkdir(exist_ok=True)
            (backup / p.name).write_text(orig, encoding="utf-8")
            p.write_text(new, encoding="utf-8")
        elif shown < args.sample:
            shown += 1
            diff = difflib.unified_diff(
                orig.split("\n"), new.split("\n"),
                fromfile=f"{brand}/{p.stem} (旧)", tofile=f"{brand}/{p.stem} (新)",
                lineterm="", n=1,
            )
            print("\n".join(diff))
            print()

    print("=" * 50)
    print(f"{'应用' if args.apply else 'dry-run'}：{changed}/{len(docs)} 篇有改动")
    if not args.apply and changed > shown:
        print(f"（只显示了前 {shown} 篇 diff，--sample N 看更多）")


if __name__ == "__main__":
    main()
