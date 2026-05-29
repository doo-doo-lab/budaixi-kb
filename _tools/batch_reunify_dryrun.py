#!/usr/bin/env python3
"""对所有剩余 ≥20KB 大 doc 跑 generic reunify dry-run，分类报告。

不写原文，只报告：每篇 generic 删多少 + validate 是否过。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_reunify import validate
from manual_reunify_test import reunify_generic

DONE = {
    "槐破梦", "素还真", "一页书", "俏如来", "叶小钗",
    "乱世狂刀", "风之痕", "秦假仙", "青阳子",
}
DOCS = Path("docs/角色")


def main():
    big = []
    for f in DOCS.rglob("*.md"):
        if f.name in ("index.md", ".pages"):
            continue
        if any(p.startswith(".") for p in f.parts):
            continue
        if f.stat().st_size < 20000:
            continue
        t = f.read_text(encoding="utf-8")
        if not t.startswith("---"):
            continue
        if f.stem in DONE:
            continue
        big.append(f)
    big.sort(key=lambda f: -f.stat().st_size)

    can_apply = []   # generic 删了且 validate 过
    zero_del = []    # generic 0 删（需手工）
    failed = []      # generic 删了但 validate 没过
    for f in big:
        orig = f.read_text(encoding="utf-8")
        new = reunify_generic(orig)
        delta = len(orig) - len(new)
        if delta == 0:
            zero_del.append(f.stem)
            continue
        ok, reason = validate(orig, new)
        if ok:
            can_apply.append((f.stem, delta, reason))
        else:
            failed.append((f.stem, delta, reason))

    print(f"=== generic 能 apply（删了+校验过）: {len(can_apply)} ===")
    for n, d, r in can_apply:
        print(f"  {n}: -{d}字  {r}")
    print(f"\n=== generic 删了但校验失败: {len(failed)} ===")
    for n, d, r in failed:
        print(f"  {n}: -{d}字  {r[:50]}")
    print(f"\n=== generic 0 删（需我手工）: {len(zero_del)} ===")
    print("  " + " ".join(zero_del))


if __name__ == "__main__":
    main()
