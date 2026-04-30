#!/usr/bin/env python3
"""页面内去重：删除单个角色 markdown 文件中重复的段落。

策略：
- 按段落（\\n\\n 分隔）切分
- 段落必须 ≥30 字才参与去重（短段如 "男" "天罗山" 等元数据值经常合理重复）
- 严格相等判定（去除首尾空白后逐字符比较）
- 第一次出现保留，后续重复的删除
- 不动结构性分隔符（=== 行）和 H1/H2 标题
- 跨"## 标题"边界的重复也去（同一文件内同样段落出现在两段不同章节是冗余）

用法：
    python dedupe.py <文件或目录>            # dry-run（仅打印统计）
    python dedupe.py <文件或目录> --apply    # 原地写入
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

MIN_LEN = 30  # 短于 30 字的段不去重（元数据值如 "男"、"霹雳金光"）


def is_structural(p: str) -> bool:
    """是否是结构性段落（不参与去重）。"""
    s = p.strip()
    if not s:
        return True
    # 分隔条
    if re.match(r"^=+$", s):
        return True
    # H1/H2/H3 标题
    if re.match(r"^#{1,6}\s", s):
        return True
    # 列表项（短列表项不去重，避免误删）
    if re.match(r"^[-*]\s", s):
        return False
    return False


def dedupe_text(text: str) -> tuple[str, int]:
    """返回 (去重后的文本, 删掉的段数)。"""
    paragraphs = re.split(r"(\n\s*\n)", text)
    # paragraphs 是 [content, sep, content, sep, ...] 交替
    seen: set[str] = set()
    out_parts: list[str] = []
    removed = 0
    pending_sep: str | None = None  # 待写入的分隔符（如果上一段被删则丢弃）

    for chunk in paragraphs:
        if re.match(r"^\n\s*\n$", chunk):
            # 分隔符
            pending_sep = chunk
            continue

        content = chunk
        s = content.strip()

        if is_structural(content) or len(s) < MIN_LEN:
            # 结构性 / 太短：保留
            if pending_sep is not None and out_parts:
                out_parts.append(pending_sep)
            out_parts.append(content)
            pending_sep = None
        else:
            # 候选去重段
            if s in seen:
                removed += 1
                # 不写入这段，也不写之前的 pending_sep（避免连续空行）
                pending_sep = None
            else:
                seen.add(s)
                if pending_sep is not None and out_parts:
                    out_parts.append(pending_sep)
                out_parts.append(content)
                pending_sep = None

    return "".join(out_parts), removed


def process(target: Path, apply: bool) -> None:
    files = [target] if target.is_file() else sorted(target.rglob("*.md"))
    if not files:
        print(f"[!] 未找到 .md 文件: {target}")
        return

    total_removed = 0
    affected_files = 0
    for f in files:
        original = f.read_text(encoding="utf-8")
        cleaned, removed = dedupe_text(original)
        if removed == 0:
            continue
        affected_files += 1
        total_removed += removed
        delta = len(original) - len(cleaned)
        if apply:
            f.write_text(cleaned, encoding="utf-8")
            print(f"  [APPLY] {f}: 删 {removed} 段 (-{delta:,} 字)")
        else:
            print(f"  [DRY]   {f}: 删 {removed} 段 (-{delta:,} 字)")

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\n[{mode}] 共 {len(files)} 文件，{affected_files} 个有重复，共删 {total_removed} 段")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    target = Path(args[0]).resolve()
    apply = "--apply" in args
    process(target, apply)


if __name__ == "__main__":
    main()
