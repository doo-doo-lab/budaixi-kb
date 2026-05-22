#!/usr/bin/env python3
"""reunify 前的确定性预清洗。只删【可证明安全】的噪音，绝不碰数据。

处理：
1. 纯分隔条（一行全是 = 号，如 `========...`）→ 删
2. MediaWiki 式章节头 `===标题===` → 转成 `## 标题`
3. 残留 baidu UI：整行 `播报编辑` / `播报` / `编辑` / `订阅` / `有用+1` → 删
4. 连续完全重复的非空行（非标题）→ 保留第一行删后续
5. 3+ 连续空行 → 压成 1 个空行

**不碰**：swatch HTML（`<span class="bdx-swatch">` 是 B 系列特意加的显示数据）、
`杂学`/`邪魔`/`诡谲` 等关系分类标签、frontmatter、任何叙事/列表内容。

用法:
    python body_preclean.py docs/角色                 # dry-run，报告每篇会改多少
    python body_preclean.py docs/角色 --apply         # 应用（先备份到 .pre_preclean_backup/）
    python body_preclean.py docs/角色/pili/一线生.md   # 单篇
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

UI_NOISE_LINES = {"播报编辑", "播报", "编辑", "订阅", "有用+1", "讨论", "收藏"}


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end < 0:
        return "", text
    return text[: end + 5], text[end + 5:]


def clean_body(body: str) -> str:
    lines = body.split("\n")
    out: list[str] = []
    prev_nonblank = None
    for line in lines:
        s = line.strip()

        # 1. 纯分隔条：一行全是 = （≥3 个），删
        if re.fullmatch(r"={3,}", s):
            continue

        # 2. ===标题=== → ## 标题
        m = re.fullmatch(r"={3,}\s*(.+?)\s*={3,}", s)
        if m:
            title = m.group(1).strip()
            if title:
                out.append(f"## {title}")
                prev_nonblank = f"## {title}"
            continue

        # 3. baidu UI 噪音整行删
        if s in UI_NOISE_LINES:
            continue

        # 4. 连续完全重复的非空、非标题行 → 跳过
        if s and not s.startswith("#") and s == prev_nonblank:
            continue

        out.append(line)
        if s:
            prev_nonblank = s

    text = "\n".join(out)
    # 5. 3+ 空行压成 1
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def process(path: Path, apply: bool) -> tuple[int, int]:
    """返回 (原字数, 新字数)。"""
    original = path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(original)
    new_body = clean_body(body)
    new_text = fm + new_body if fm else new_body
    # 收尾：确保单个结尾换行
    new_text = new_text.rstrip() + "\n"

    if apply and new_text != original:
        backup = path.parent / ".pre_preclean_backup"
        backup.mkdir(exist_ok=True)
        (backup / path.name).write_text(original, encoding="utf-8")
        path.write_text(new_text, encoding="utf-8")
    return len(original), len(new_text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if target.is_file():
        files = [target]
    else:
        files = [
            f for f in sorted(target.rglob("*.md"))
            if f.name not in ("index.md", ".pages")
            # 排除备份/预览目录（任何路径段以 . 开头，或叫 reunify_preview/samples_out）
            and not any(
                part.startswith(".") or part in ("reunify_preview", "samples_out")
                for part in f.parts
            )
        ]
    if args.limit:
        files = files[: args.limit]

    changed = 0
    total_removed = 0
    samples = []
    for f in files:
        before, after = process(f, args.apply)
        if before != after:
            changed += 1
            total_removed += before - after
            if len(samples) < 15:
                samples.append((f.stem, before, after))

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"[{mode}] 扫 {len(files)} 篇，{changed} 篇有改动，共减 {total_removed} 字")
    for name, b, a in samples:
        print(f"  {name}: {b}→{a} (-{b-a})")


if __name__ == "__main__":
    main()
