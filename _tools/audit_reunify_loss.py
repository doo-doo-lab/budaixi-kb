#!/usr/bin/env python3
"""审计 reunify 是否丢了独有信息。

对每篇有 .pre_reunify_backup 的 doc：
- backup = reunify 前，current = reunify 后
- 找 backup 里「消失的值 token」：按行 + 顿号/逗号分割成 item，
  normalize 后若该 item 在 normalize(current) 全文中再也找不到 → 数据丢失
- 报告每篇丢失的 token
"""
import re
import sys
from pathlib import Path

DOCS = Path("docs/角色")


def normalize(s: str) -> str:
    return re.sub(r"[^一-鿿㐀-䶿a-zA-Z0-9]", "", s)


def audit_one(backup: Path, current: Path):
    bt = backup.read_text(encoding="utf-8")
    ct = current.read_text(encoding="utf-8")
    cnorm = normalize(ct)

    lost = []
    for line in bt.split("\n"):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("---"):
            continue
        if s.startswith("- **来源**") or s.startswith("<span"):
            continue
        # 拆 item
        items = [x.strip() for x in re.split(r"[、，,；;\s]", s) if x.strip()]
        for it in items:
            itn = normalize(it)
            if len(itn) < 2:
                continue
            if itn not in cnorm:
                lost.append(it)
    return lost


def main():
    targets = sys.argv[1:]
    found_any = False
    for sub in ("pili", "jinguang", "dongli"):
        bdir = DOCS / sub / ".pre_reunify_backup"
        if not bdir.exists():
            continue
        for backup in sorted(bdir.glob("*.md")):
            name = backup.stem
            if targets and name not in targets:
                continue
            current = DOCS / sub / backup.name
            if not current.exists():
                continue
            lost = audit_one(backup, current)
            if lost:
                found_any = True
                # 去重保序
                seen = set()
                uniq = [x for x in lost if not (x in seen or seen.add(x))]
                print(f"⚠️  {name}: 丢失 {len(uniq)} 个 token")
                for t in uniq[:30]:
                    print(f"      {t}")
    if not found_any:
        print("✓ 所有审计的 doc 无 token 丢失")


if __name__ == "__main__":
    main()
