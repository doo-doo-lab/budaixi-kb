#!/usr/bin/env python3
"""从 docs/角色/{brand}/*.md 提取字段，生成 YAML frontmatter。

按 SCHEMA.md v1。

用法：
    python yaml_extract.py                          # dry-run，前 20 个 sample
    python yaml_extract.py --sample 50              # dry-run 50 个
    python yaml_extract.py --filter "步非烟|九幽"     # 只看匹配名字的
    python yaml_extract.py --apply                  # 全量应用（含 backup）
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path
from collections import OrderedDict

try:
    import yaml
except ImportError:
    print("[!] 缺 pyyaml：pip install pyyaml")
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs" / "角色"

# ---------- schema 映射 ----------
# 源字段 → 目标字段（None=丢弃）
FIELD_MAP = {
    # Tier 0
    # 姓名 从 H1 提取，不从 body 字段
    "中文名": None,  # 跟 H1 重复
    "名称": None,    # 跟 H1 重复

    # Tier 1
    "性别": "性别",
    "初登场": "初登场",
    "根据地": "根据地",
    "退场": "退场",
    "称号": "称号",
    "配音": "配音",

    # Tier 2
    "别名": "别名",
    "本名": "别名",  # 合并
    "身份": "身份",
    "诗号": "诗号",

    # Tier 3 - 能力
    "武学": "武学",
    "武器": "武器",
    "兵器": "武器",  # 合并
    "所有物": "所有物",
    "咒术": "咒术",

    # Tier 4 - 人际（特殊处理，进 人际 嵌套）
    "朋友": "_人际_朋友",
    "上司": "_人际_上司",
    "同伙": "_人际_同伙",
    "部属": "_人际_部属",
    "兄弟": "_人际_兄弟",
    "姐妹": "_人际_姐妹",
    "师徒": "_人际_师徒",
    "仇敌": "_人际_仇敌",
    "其他": "_人际_其他",

    # Tier 5 - 组织
    "组织门派": "组织门派",
    "组织": "组织门派",  # 合并
    "门派": "组织门派",  # 合并
    "种族": "种族",

    # Tier 6 - 制作元数据
    "登场作品": "登场作品",
    "本尊雕偶师": "本尊雕偶师",
    "编剧": "编剧",
    "角色编剧": "编剧",  # 合并
    "出场集数": "出场集数",

    # 显式丢弃
    "代表颜色": None,
    "繁体标题": None,
    "标题": None,
    "生日": None,    # dongli 特有，留 v2
    "外文名": None,  # 同上
}

LIST_FIELDS = {"武学", "武器", "所有物", "咒术", "别名", "组织门派", "登场作品"}
# 人际下所有子键都是 list

GENDER_ENUM = {"男", "女", "其他", "不详"}

# ---------- 解析正则 ----------
# `**字段**：值` 或 `**字段** 值`（粗体后跟冒号或紧接值）
BOLD_FIELD_PAT = re.compile(
    r"\*\*([一-鿿]{2,8})\*\*\s*[：:]?\s*\n?\s*(.+?)(?=\n\n|\n#|\n\*\*|\n- \*\*|$)",
    re.DOTALL,
)
# 行首 `字段：值`
LINE_FIELD_PAT = re.compile(r"^([一-鿿]{2,8})[：:]\s*(.+)$", re.MULTILINE)


def strip_annotation(s: str) -> str:
    """剥角色名后的注释：'青阳子（圣龙口）' → '青阳子'，'龙知命 [兄]' → '龙知命'。"""
    s = re.sub(r"\s*[（(\[【].*?[）)\]】]\s*$", "", s)
    s = re.sub(r"\s*\[[^\]]+\]\s*$", "", s)
    return s.strip()


# 早期 AI reformat 留下的占位符/噪声词黑名单
NOISE_NAMES = {"杂学", "无", "无人", "不详", "未知", "其他", "等", "...", "—"}


def split_list(val: str, max_item_len: int = 30) -> list[str]:
    """切分 list 字段：按 、，,\n 分割并去重保序，剥括号注释，过滤过长项/噪声。"""
    parts = re.split(r"[、，,;；\n]+", val)
    out = []
    seen = set()
    for p in parts:
        p = p.strip().rstrip("。.").strip()
        p = re.sub(r"^[\-\*\+]\s*", "", p)
        p = strip_annotation(p)
        if not p or p in seen:
            continue
        if len(p) > max_item_len:
            continue
        if len(p) < 2 and not p.isdigit():
            continue
        if p in NOISE_NAMES:
            continue  # 占位符噪声
        if "：" in p or ":" in p:
            continue  # parse 残渣（含字段冒号）
        out.append(p)
        seen.add(p)
    return out


def normalize_gender(val: str) -> str:
    val = val.strip()
    if val in GENDER_ENUM:
        return val
    if val.startswith("男"):
        return "男"
    if val.startswith("女"):
        return "女"
    return "其他"


def clean_value(val: str, is_list: bool, max_single_len: int = 200) -> str | list[str] | None:
    """归一化 value。返回 None 表示该字段疑似坏数据，应跳过。"""
    val = val.strip()
    val = re.sub(r"\*\*([^*]+)\*\*", r"\1", val)
    val = re.sub(r"\*([^*]+)\*", r"\1", val)
    val = val.rstrip("。.；;")
    val = val.strip()
    if is_list:
        return split_list(val)
    val = re.sub(r"\s+", " ", val)
    if len(val) > max_single_len:
        return None  # 过长单值，大概率 parser 误捕整段
    return val


def has_frontmatter(text: str) -> bool:
    return text.lstrip().startswith("---\n") or text.lstrip().startswith("---\r\n")


def extract_h1(text: str) -> str | None:
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("# "):
            # 去括号
            h1 = s[2:].strip()
            h1 = re.sub(r"[（(].*$", "", h1).strip()
            return h1
    return None


def parse_doc(text: str) -> dict | None:
    """解析 doc 内容，返回 frontmatter dict。返回 None 表示 doc 结构 suspect。"""
    fm: dict = OrderedDict()
    raw_fields: dict[str, str] = {}

    # doc-level 质量门控：同一 bold 字段出现 ≥3 次 → suspect（如多个 **武器**: 堆叠）
    bold_freq: dict[str, int] = {}
    for m in BOLD_FIELD_PAT.finditer(text):
        k = m.group(1)
        bold_freq[k] = bold_freq.get(k, 0) + 1
    if any(c >= 3 for c in bold_freq.values()):
        return None

    # 收集所有字段（bold + line-start），bold 优先（更结构化）
    for m in BOLD_FIELD_PAT.finditer(text):
        k, v = m.group(1), m.group(2).strip()
        if k not in raw_fields:
            raw_fields[k] = v
    for m in LINE_FIELD_PAT.finditer(text):
        k, v = m.group(1), m.group(2).strip()
        if k not in raw_fields:
            raw_fields[k] = v

    # 映射到 canonical
    renji: dict[str, list[str]] = OrderedDict()
    for src_key, raw_val in raw_fields.items():
        target = FIELD_MAP.get(src_key)
        if target is None:
            continue  # 显式丢弃
        if target.startswith("_人际_"):
            sub = target[len("_人际_"):]
            # 人际 list 项更严格：max 15 字符
            items = split_list(raw_val, max_item_len=15)
            if items:
                renji[sub] = items
            continue
        is_list = target in LIST_FIELDS
        cleaned = clean_value(raw_val, is_list)
        if cleaned is None:
            continue  # 跳过坏数据
        if isinstance(cleaned, list) and not cleaned:
            continue  # 空 list 不写
        # 特殊：性别 enum 化
        if target == "性别" and isinstance(cleaned, str):
            cleaned = normalize_gender(cleaned)
        # list 字段如果已有值，合并
        if target in fm and is_list:
            existing = fm[target] if isinstance(fm[target], list) else [fm[target]]
            new = cleaned if isinstance(cleaned, list) else [cleaned]
            merged = []
            seen = set()
            for x in existing + new:
                if x not in seen:
                    merged.append(x)
                    seen.add(x)
            fm[target] = merged
        elif target not in fm:
            fm[target] = cleaned

    # 嵌套 人际（按 SCHEMA tier 顺序）
    if renji:
        renji_order = ["上司", "同伙", "朋友", "部属", "兄弟", "姐妹", "师徒", "仇敌", "其他"]
        ordered = OrderedDict()
        for k in renji_order:
            if k in renji and renji[k]:
                ordered[k] = renji[k]
        # 额外子键也带上
        for k, v in renji.items():
            if k not in ordered and v:
                ordered[k] = v
        if ordered:
            fm["人际"] = dict(ordered)

    return fm


def build_frontmatter(姓名: str, fm: dict) -> str:
    """按 schema tier 顺序排列输出 YAML。"""
    ordered = OrderedDict()
    ordered["姓名"] = 姓名
    tier_order = [
        # Tier 1
        "性别", "初登场", "根据地", "退场", "称号", "配音",
        # Tier 2
        "别名", "身份", "诗号",
        # Tier 3
        "武学", "武器", "所有物", "咒术",
        # Tier 5
        "组织门派", "种族",
        # Tier 4
        "人际",
        # Tier 6
        "登场作品", "本尊雕偶师", "编剧", "出场集数",
    ]
    for k in tier_order:
        if k in fm:
            ordered[k] = fm[k]
    yaml_body = yaml.dump(dict(ordered), allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000)
    return f"---\n{yaml_body}---\n\n"


def process_doc(path: Path, apply: bool) -> tuple[str, str, dict]:
    """
    返回 (state, preview, fm)
    state: 'skip-has-fm' | 'skip-no-fields' | 'ok' | 'applied'
    """
    text = path.read_text(encoding="utf-8")
    if has_frontmatter(text):
        return "skip-has-fm", "", {}
    h1 = extract_h1(text)
    if not h1:
        return "skip-no-h1", "", {}
    fm = parse_doc(text)
    if fm is None:
        return "skip-suspect-structure", "", {"姓名": h1}
    if not fm:
        return "skip-no-fields", "", {"姓名": h1}
    new_frontmatter = build_frontmatter(h1, fm)
    if apply:
        backup_dir = path.parent / ".pre_yaml_backup"
        backup_dir.mkdir(exist_ok=True)
        (backup_dir / path.name).write_text(text, encoding="utf-8")
        path.write_text(new_frontmatter + text, encoding="utf-8")
        return "applied", new_frontmatter, fm
    return "ok", new_frontmatter, fm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--filter", type=str, default=None)
    args = ap.parse_args()

    all_docs = []
    for brand in ["pili", "jinguang", "dongli"]:
        for p in sorted((DOCS_DIR / brand).glob("*.md")):
            if p.name == "index.md":
                continue
            all_docs.append((brand, p))

    if args.filter:
        rx = re.compile(args.filter)
        all_docs = [(b, p) for b, p in all_docs if rx.search(p.stem)]

    if not args.apply:
        all_docs = all_docs[: args.sample]

    stats = {"ok": 0, "applied": 0, "skip-has-fm": 0, "skip-no-h1": 0, "skip-no-fields": 0, "skip-suspect-structure": 0}

    for brand, p in all_docs:
        state, preview, fm = process_doc(p, args.apply)
        stats[state] = stats.get(state, 0) + 1
        if not args.apply and state == "ok":
            print(f"=== {brand}/{p.stem} ===")
            print(preview, end="")
            print()

    print("===========")
    print("Stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    if args.apply:
        print(f"\nApplied to {stats['applied']} files. Backups in .pre_yaml_backup/")


if __name__ == "__main__":
    main()
