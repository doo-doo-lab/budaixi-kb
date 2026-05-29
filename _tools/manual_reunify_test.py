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


def reunify_suhuanzhen(orig: str) -> str:
    """素还真 — 删 ## 【补充来源】 下的多组 dump，保留 swatch + 机关阵法 + 著作 + 其他事项诗号 + 人物关系."""
    lines = orig.split("\n")
    # 补充来源 H2
    h2_idx = next(i for i, l in enumerate(lines) if l.startswith("## 【补充来源:霹雳官网"))
    # 补充来源 下的 ## 角色背景 / ## 技能专长 / ## 武器
    bg_idx = next(i for i, l in enumerate(lines[h2_idx:], h2_idx) if l == "## 角色背景")
    skill_idx = next(i for i, l in enumerate(lines[bg_idx:], bg_idx) if l == "## 技能专长")
    weapon_idx = next(i for i, l in enumerate(lines[skill_idx:], skill_idx) if l == "## 武器")
    rel_idx = next(i for i, l in enumerate(lines[weapon_idx:], weapon_idx) if l == "## 人物关系")

    # 提 swatch 块（角色背景 范围内）
    swatch_lines = [l for l in lines[bg_idx:skill_idx] if "bdx-swatch" in l]

    # ## 技能专长 段（skill_idx..weapon_idx）：武学 dump 删，机关阵法 留
    skill_seg = lines[skill_idx:weapon_idx]
    # 找 "机关阵法" 标签起点（在 skill_seg 内）
    kept_skill = ["## 技能专长", ""]
    if "机关阵法" in skill_seg:
        ji_i = skill_seg.index("机关阵法")
        # 后续行（标签后空行 + 阵法 list 行）直到段末
        kept_skill.append("机关阵法")
        kept_skill.append("")
        for l in skill_seg[ji_i+1:]:
            if l.strip() and l != "机关阵法":
                kept_skill.append(l)
        kept_skill.append("")

    # ## 武器 段（weapon_idx..rel_idx）：武器 dump 删，著作 留，所有物 删
    weapon_seg = lines[weapon_idx:rel_idx]
    kept_weapon = ["## 武器", ""]
    # 找 "著作" 起点 + 它的内容（到下一个空标签/段尾）
    if "著作" in weapon_seg:
        zhu_i = weapon_seg.index("著作")
        kept_weapon.append("著作")
        kept_weapon.append("")
        # 著作 后续行（直到遇到下一个非空非内容标签 "所有物" 或 "其他事项" 或段末）
        for j in range(zhu_i+1, len(weapon_seg)):
            ls = weapon_seg[j].strip()
            if ls in ("所有物", "其他事项", "其他纪录"):
                break
            if ls:
                kept_weapon.append(weapon_seg[j])
        kept_weapon.append("")
        # 之后还有 "其他事项" 这个标签下的诗号（在 weapon_seg 内）—— 一律保留
        for j in range(zhu_i+1, len(weapon_seg)):
            ls = weapon_seg[j].strip()
            if ls == "其他事项":
                # 从这一行起到段末全部保留
                kept_weapon.append("")
                kept_weapon.extend(weapon_seg[j:])
                break

    # 拼装
    keep = lines[:bg_idx]  # L1 到 ## 角色背景 之前（含 ## 【补充来源】H2 + URL + 繁体标题 + lead）
    keep.append("")
    keep.append("**代表颜色**")
    keep.append("")
    keep.extend(swatch_lines)
    keep.append("")
    keep.extend(kept_skill)
    keep.extend(kept_weapon)
    keep.append("")
    keep.extend(lines[rel_idx:])  # ## 人物关系 全段

    # 去尾空行
    while keep and not keep[-1].strip():
        keep.pop()
    return "\n".join(keep) + "\n"


def reunify_yiyeshu(orig: str) -> str:
    """一页书 — 删 ## 【补充来源】下 H2 子段的 dump，保留化身/swatch/机关阵法/著作/座骑/其他事项诗号/人物关系."""
    lines = orig.split("\n")
    h2_idx = next(i for i, l in enumerate(lines) if l.startswith("## 【补充来源:霹雳官网"))
    bg_idx = next(i for i, l in enumerate(lines[h2_idx:], h2_idx) if l == "## 角色背景")
    skill_idx = next(i for i, l in enumerate(lines[bg_idx:], bg_idx) if l == "## 技能专长")
    hold_idx = next(i for i, l in enumerate(lines[skill_idx:], skill_idx) if l == "## 所持有物")
    rel_idx = next(i for i, l in enumerate(lines[hold_idx:], hold_idx) if l == "## 人物关系")

    # ## 角色背景 段：保留 **化身** + swatch；删 性别/初登场/称号/根据地/身份/名言/诗词
    bg_seg = lines[bg_idx:skill_idx]
    # 找 **化身** 起点 + 后续 6 化身名（到 **代表颜色** 前）
    huashen_start = next(i for i, l in enumerate(bg_seg) if l == "**化身**")
    swatch_label_idx = next(i for i, l in enumerate(bg_seg) if l == "**代表颜色**")
    huashen_block = bg_seg[huashen_start:swatch_label_idx]  # 含 **化身** 标签 + 名字
    swatch_lines = [l for l in bg_seg if "bdx-swatch" in l]

    # ## 技能专长 段：删 武学，留 机关阵法
    skill_seg = lines[skill_idx:hold_idx]
    kept_skill = ["## 技能专长", ""]
    if "**机关阵法**" in skill_seg:
        ji_i = skill_seg.index("**机关阵法**")
        kept_skill.append("**机关阵法**")
        kept_skill.append("")
        for l in skill_seg[ji_i+1:]:
            if l.strip():
                kept_skill.append(l)
        kept_skill.append("")

    # ## 所持有物 段：删 武器/所有物，留 著作/交通(座骑)/其他事项 之后所有
    hold_seg = lines[hold_idx:rel_idx]
    kept_hold = ["## 所持有物", ""]
    # 找 **著作** 起点 → 一直保留到段末
    if "**著作**" in hold_seg:
        zhu_i = hold_seg.index("**著作**")
        kept_hold.extend(hold_seg[zhu_i:])
        # 去内嵌 **武器** **所有物** 段（如果在 著作 之后还有的话——通常不会）
    # 否则若无著作，从 交通(座骑) 起点开始也行
    elif any("交通" in l or "座骑" in l for l in hold_seg):
        jt_i = next(i for i, l in enumerate(hold_seg) if "交通" in l or "座骑" in l)
        kept_hold.extend(hold_seg[jt_i:])

    keep = lines[:bg_idx]
    # 保留化身 + swatch
    keep.append("")
    keep.extend(huashen_block)
    keep.append("")
    keep.append("**代表颜色**")
    keep.append("")
    keep.extend(swatch_lines)
    keep.append("")
    keep.extend(kept_skill)
    keep.extend(kept_hold)
    keep.append("")
    keep.extend(lines[rel_idx:])

    while keep and not keep[-1].strip():
        keep.pop()
    return "\n".join(keep) + "\n"


REUNIFIERS = {
    "槐破梦": reunify_huaipomeng,
    "素还真": reunify_suhuanzhen,
    "一页书": reunify_yiyeshu,
}


def run(name: str):
    src = Path(f"docs/角色/pili/{name}.md")
    orig = src.read_text(encoding="utf-8")
    fn = REUNIFIERS[name]
    new = fn(orig)

    preview_dir = Path("_tools/reunify_preview")
    preview_dir.mkdir(exist_ok=True)
    out_path = preview_dir / f"{name}.md"
    out_path.write_text(new, encoding="utf-8")

    print(f"[{name}] 原文: {len(orig)} 字 / 输出: {len(new)} 字 / 删: {len(orig)-len(new)} ({(len(orig)-len(new))/len(orig)*100:.1f}%)")
    ok, reason = validate(orig, new)
    print(f"  校验: {'✓ PASS' if ok else '✗ FAIL'} — {reason}")
    return ok


if __name__ == "__main__":
    import sys
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(REUNIFIERS.keys())
    for name in targets:
        run(name)
