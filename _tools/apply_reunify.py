#!/usr/bin/env python3
"""对指定大 doc 用 reunify_generic（带覆盖检查）安全 apply。

幂等：若已有 .pre_reunify_backup，从 backup 取基线重跑（不叠加、不覆盖原始备份）。
每篇 apply 后立即审计：被删 token 必须在新文档仍存在，否则报警并回滚该篇。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ai_reunify import validate
from manual_reunify_test import reunify_generic
from audit_reunify_loss import normalize

DOCS = Path("docs/角色")
# 已知 structural label（dump 段标签/分类名，非角色信息值，丢了无害）
STRUCT_LABELS = {
    "名言锦句", "诗词", "其他事项", "其他纪录", "父母", "门派组织", "所属",
    "结发相守", "基本信息表", "代表颜色", "夫", "妻", "儿女", "兄弟", "朋友",
    "同伙", "部属", "师父", "徒弟", "结义", "化身", "武学", "武器", "所有物",
    "机关阵法", "咒术", "发明", "创造", "上司", "仇敌", "同门", "随从", "其他",
}


def find(name: str):
    for sub in ("pili", "jinguang", "dongli"):
        p = DOCS / sub / f"{name}.md"
        if p.exists():
            return p
    return None


def real_lost(base: str, new: str) -> list[str]:
    """返回被删的【真实值 token】（排除 structural label）。"""
    cnorm = normalize(new)
    lost = []
    for line in base.split("\n"):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("---"):
            continue
        if s.startswith("- **来源**") or s.startswith("<span"):
            continue
        for it in re.split(r"[、，,；;\s]", s):
            it = it.strip().strip("*")
            if len(normalize(it)) < 2:
                continue
            if it in STRUCT_LABELS:
                continue
            if normalize(it) not in cnorm:
                lost.append(it)
    seen = set()
    return [x for x in lost if not (x in seen or seen.add(x))]


def main():
    names = sys.argv[1:]
    applied = skipped = warned = 0
    for name in names:
        src = find(name)
        if not src:
            print(f"  ✗ {name}: 找不到")
            continue
        backup = src.parent / ".pre_reunify_backup" / src.name
        if backup.exists():
            base = backup.read_text(encoding="utf-8")  # 从原始基线重跑
        else:
            base = src.read_text(encoding="utf-8")
        new = reunify_generic(base)
        if new == base:
            skipped += 1
            print(f"  · {name}: generic 0 删，跳过")
            continue
        ok, reason = validate(base, new)
        if not ok:
            skipped += 1
            print(f"  ✗ {name}: validate 失败 — {reason[:40]}")
            continue
        lost = real_lost(base, new)
        if lost:
            warned += 1
            print(f"  ⚠️  {name}: 会丢真值 {lost[:8]} — 跳过不 apply")
            continue
        # 安全：存 backup（首次）+ 写回
        if not backup.exists():
            backup.parent.mkdir(exist_ok=True)
            backup.write_text(base, encoding="utf-8")
        src.write_text(new, encoding="utf-8")
        applied += 1
        d = len(base) - len(new)
        print(f"  ✓ {name}: -{d}字  {reason}")
    print(f"\n汇总: apply {applied} / skip {skipped} / warn {warned}")


if __name__ == "__main__":
    main()
