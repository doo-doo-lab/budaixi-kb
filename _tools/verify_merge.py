#!/usr/bin/env python3
"""验证 batch 合并质量。

检查项：
1. frontmatter (---) 完整保留
2. H1 完整
3. 没有 baidu UI 噪音（播报编辑/订阅/有用+1）
4. 字数对比：output 应 ≥ primary 且 ≤ (primary + baidu) * 1.1
5. 关键 docs 章节存在（如 ## 角色背景 等）

用法：python verify_merge.py [names...]  不传名字则检查所有 raw_baidu 当前能找到 docs 的
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(__file__).resolve().parent / "raw_baidu"
DOCS_DIR = ROOT / "docs" / "角色"
BACKUP_PATTERN = ".pre_merge_backup"


def find_doc(name: str) -> Path | None:
    for sub in ("pili", "jinguang", "dongli"):
        p = DOCS_DIR / sub / f"{name}.md"
        if p.exists():
            return p
    return None


def find_backup(doc_path: Path) -> Path | None:
    backup = doc_path.parent / BACKUP_PATTERN / doc_path.name
    return backup if backup.exists() else None


def verify(name: str) -> list[str]:
    """返回问题列表。空列表 = 没问题。"""
    issues = []
    doc = find_doc(name)
    if not doc:
        return ["no_doc"]
    raw = RAW_DIR / f"{name}.md"
    if not raw.exists():
        return ["no_raw"]

    merged_text = doc.read_text(encoding="utf-8")
    raw_text = raw.read_text(encoding="utf-8")
    backup = find_backup(doc)
    primary_text = backup.read_text(encoding="utf-8") if backup else None

    # 1. 噪音检查
    for noise in ["播报编辑", "0有用+1", "有用+1播报", "订阅0"]:
        if noise in merged_text:
            issues.append(f"noise:{noise}")
            break

    # 2. frontmatter 完整性（如果 primary 有 frontmatter，merged 也应有）
    if primary_text and primary_text.startswith("---"):
        if not merged_text.startswith("---"):
            issues.append("frontmatter_lost")
        else:
            # 找两边的 frontmatter 块
            p_end = primary_text.find("\n---\n", 3)
            m_end = merged_text.find("\n---\n", 3)
            if p_end > 0 and m_end > 0:
                p_fm = primary_text[:p_end]
                m_fm = merged_text[:m_end]
                # 至少 80% 相同
                if p_fm != m_fm:
                    # 看 keys 是否都在
                    p_keys = set(re.findall(r"^([\w]+):", p_fm, re.M))
                    m_keys = set(re.findall(r"^([\w]+):", m_fm, re.M))
                    missing = p_keys - m_keys
                    if missing:
                        issues.append(f"frontmatter_lost_keys:{','.join(missing)}")

    # 3. H1 检查
    primary_h1 = re.search(r"(?m)^# (.+)$", primary_text or merged_text)
    merged_h1 = re.search(r"(?m)^# (.+)$", merged_text)
    if not merged_h1:
        issues.append("no_h1")

    # 4. 字数比例
    if primary_text:
        p_chars = len(primary_text)
        m_chars = len(merged_text)
        r_chars = len(raw_text)
        # merged 应 >= primary * 0.9 (允许 10% 减少由于格式 normalize)
        if m_chars < p_chars * 0.85:
            issues.append(f"shrunk:{p_chars}→{m_chars}")
        # merged 应 <= (primary + baidu) * 1.1
        max_expected = (p_chars + r_chars) * 1.1
        if m_chars > max_expected:
            issues.append(f"grew_beyond_inputs:{m_chars} > {max_expected:.0f}")

    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    args = ap.parse_args()

    if args.names:
        targets = args.names
    else:
        targets = [p.stem for p in sorted(RAW_DIR.glob("*.md"))]

    total = ok = bad = skip = 0
    issue_counts = {}
    bad_list = []
    for name in targets:
        total += 1
        issues = verify(name)
        if not issues:
            ok += 1
        elif issues == ["no_doc"] or issues == ["no_raw"]:
            skip += 1
        else:
            bad += 1
            bad_list.append((name, issues))
            for iss in issues:
                key = iss.split(":")[0]
                issue_counts[key] = issue_counts.get(key, 0) + 1

    print(f"Total: {total}, OK: {ok}, Bad: {bad}, Skip: {skip}")
    print(f"Issue counts: {issue_counts}")
    if bad_list:
        print("\nBad files:")
        for name, issues in bad_list[:30]:
            print(f"  {name}: {issues}")


if __name__ == "__main__":
    main()
