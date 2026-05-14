#!/usr/bin/env python3
"""B2：字段 dump section 合并进 frontmatter + 删纯字段 section。

只处理已有 frontmatter 的 doc（B1 yaml_extract 跳过的 172 篇不碰）。

流程：
1. 重解析 body 所有字段（含 B2 修好的单字 bug），merge 进 frontmatter
   —— 已有 frontmatter 标量优先；body 补缺字段；list/人际 取并集
2. 走 H2 section：
   - 字段 dump section（角色背景/基本信息/人物设定/...）且"结构纯净"（无散文）→ 删
   - 含散文的 → 保留（宁留勿删，避免丢叙述）
   - 叙述/未知 section → 保留
   - 空接缝标记（## 来自百度百科 / ## 【补充来源】内容全空）→ 删
3. 重建 frontmatter + body

用法：
    python body_cleanup_b2.py                  # dry-run，前 12 篇 diff
    python body_cleanup_b2.py --sample 30
    python body_cleanup_b2.py --filter "步非烟|九幽"
    python body_cleanup_b2.py --apply
"""
from __future__ import annotations
import argparse
import difflib
import re
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[!] 缺 pyyaml：pip install pyyaml")
    raise SystemExit(1)

import yaml_extract as Y

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs" / "角色"

# 字段 dump section：纯净则删，含散文则留
FIELD_DUMP_SECTIONS = {
    "角色背景", "基本信息", "基本资料", "角色设定", "人物设定",
    "技能专长", "角色能力", "人物能力", "武器", "所持有物",
    "人物关系", "人际关系", "角色关系",
}
SEAM_MARKERS = ("【补充来源", "来自百度百科", "同一角色别名")


def split_fm(text: str) -> tuple[str, str]:
    m = re.match(r"^(---\n.*?\n---\n)", text, re.DOTALL)
    if m:
        return m.group(1), text[len(m.group(1)):]
    return "", text


def is_prose(line: str) -> bool:
    """值行里是否夹了散文（长 + 带句末标点）。"""
    s = line.strip()
    if not s:
        return False
    if s.startswith("|") or "bdx-swatch" in s:
        return False
    return len(s) > 40 and bool(re.search(r"[。！？；]", s))


def fm_blob(fm: dict) -> str:
    """拍平 frontmatter 所有值为一个字符串，用于 token 覆盖检查。"""
    parts: list[str] = []

    def rec(v):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            for x in v:
                rec(x)
        elif isinstance(v, dict):
            for x in v.values():
                rec(x)

    rec(fm)
    return " ".join(parts)


def value_part(s: str) -> str:
    """取一行里「不是 label」的值部分。label-only / 裸已知字段 / 色块表格 → 返回 ''。"""
    if "bdx-swatch" in s or s.startswith("|") or re.match(r"^`#[0-9a-fA-F]{3,8}`", s):
        return ""
    # **X** 单独 → 无值
    if re.match(r"^\*\*[^*]+\*\*\s*$", s):
        return ""
    # **X**：值 / - **X**：值 / X：值 → 取值
    m = re.match(r"^(?:-\s+)?\*\*[^*]+?\*\*\s*[：:]\s*(.*)$", s)
    if m:
        return m.group(1).strip()
    m = re.match(r"^([一-鿿A-Za-z·]{1,14})\s*[：:]\s*(.*)$", s)
    if m:
        return m.group(2).strip()
    # 裸已知字段名 → label，无值
    if s in Y.FIELD_MAP:
        return ""
    # 其它整行都是值
    return s


def section_deletable(content_lines: list[str], blob: str) -> bool:
    """覆盖率门控：section 可删 ⟺ 无散文 且 每个值 token 都已在 merged frontmatter 里。
    构造上无损——删掉的东西全都还在 frontmatter。"""
    for line in content_lines:
        s = line.strip()
        if not s:
            continue
        if is_prose(line):
            return False
        vp = value_part(s)
        if not vp:
            continue  # label-only / 色块 / 表格分隔
        for tok in re.split(r"[、，,;；]", vp):
            tok = Y.strip_annotation(tok.strip()).strip("。.！？ ")
            if len(tok) < 2 or tok in Y.NOISE_NAMES:
                continue
            if tok not in blob:
                return False  # 有 token 没进 frontmatter → 不能删
    return True


def merge_fm(existing: dict, body: dict) -> dict:
    """existing 标量优先；body 补缺；list/人际 取并集保序。"""
    out = dict(existing)
    for k, v in body.items():
        if v is None:
            continue
        if k == "人际":
            ex = dict(out.get("人际") or {})
            for sub, names in (v or {}).items():
                cur = ex.get(sub) or []
                seen = set(cur)
                ex[sub] = cur + [n for n in names if n not in seen]
            out["人际"] = ex
        elif k not in out or out[k] in (None, "", []):
            out[k] = v
        elif isinstance(out[k], list) and isinstance(v, list):
            seen = set(out[k])
            out[k] = out[k] + [x for x in v if x not in seen]
        # else: existing 标量优先，不动
    return out


def process(text: str) -> str:
    fm_text, body = split_fm(text)
    if not fm_text:
        return text  # 无 frontmatter（B1 跳过的 172 篇）→ 不碰

    m = re.match(r"^---\n(.*?)\n---\n", fm_text, re.DOTALL)
    existing_fm = (yaml.safe_load(m.group(1)) if m else {}) or {}

    # 1. 重解析 body 字段 + merge
    body_fm = Y.parse_doc(body)
    if body_fm is None:
        return text  # suspect 结构（多个同名 **field** 堆叠等）→ 不碰，避免误删丢数据
    merged = merge_fm(existing_fm, body_fm)
    blob = fm_blob(merged)  # 用于 section 删除的覆盖率门控

    # 2. 拆 preamble + sections
    lines = body.split("\n")
    pre = []
    i = 0
    while i < len(lines) and not lines[i].startswith("## "):
        pre.append(lines[i])
        i += 1
    kept = []
    while i < len(lines):
        heading = lines[i]
        i += 1
        content = []
        while i < len(lines) and not lines[i].startswith("## "):
            content.append(lines[i])
            i += 1
        name = heading[3:].strip()
        base = re.sub(r"[（(].*", "", name).strip()
        is_seam = any(s in name for s in SEAM_MARKERS)
        nonblank = [l for l in content if l.strip()]
        if is_seam:
            if nonblank:
                kept.append((heading, content))
            # else: 空接缝 → 删
        elif base in FIELD_DUMP_SECTIONS and section_deletable(content, blob):
            pass  # 字段 dump 且每个值都已进 frontmatter → 删（构造上无损）
        else:
            kept.append((heading, content))

    # 3. 重建
    new_body_lines = list(pre)
    for heading, content in kept:
        new_body_lines.append(heading)
        new_body_lines.extend(content)
    new_body = "\n".join(new_body_lines)
    new_body = re.sub(r"\n{3,}", "\n\n", new_body).strip("\n") + "\n"

    h1 = pre[0][2:].strip() if pre and pre[0].startswith("# ") else ""
    new_fm = Y.build_frontmatter(merged.get("姓名") or h1, merged)
    return new_fm + new_body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=12)
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

    changed = skipped_no_fm = shown = 0
    for brand, p in docs:
        orig = p.read_text(encoding="utf-8")
        if not split_fm(orig)[0]:
            skipped_no_fm += 1
            continue
        new = process(orig)
        if new == orig:
            continue
        changed += 1
        if args.apply:
            backup = p.parent / ".pre_b2_backup"
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
    print(f"{'应用' if args.apply else 'dry-run'}：{changed} 篇有改动，{skipped_no_fm} 篇无 frontmatter 跳过")
    if not args.apply and changed > shown:
        print(f"（只显示前 {shown} 篇 diff，--sample N 看更多）")


if __name__ == "__main__":
    main()
