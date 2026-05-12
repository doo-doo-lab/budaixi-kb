#!/usr/bin/env python3
"""扫描 docs/角色/，报告 schema 一致性、断链、孤儿、size 异常。read-only。"""
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs" / "角色"
OUT = Path(__file__).resolve().parent / "lint_report.md"

# ---------- 收集 ----------
brands = {"pili": [], "jinguang": [], "dongli": []}
all_docs = {}  # name -> (brand, path, text, size)
for brand in brands:
    for p in (DOCS_DIR / brand).glob("*.md"):
        if p.name == "index.md":
            continue
        name = p.stem
        text = p.read_text(encoding="utf-8", errors="ignore")
        all_docs[name] = (brand, p, text, p.stat().st_size)
        brands[brand].append(name)

# ---------- size buckets ----------
size_buckets = Counter()
size_outliers = {"too_small": [], "too_large": []}
BUCKETS = [("<300", 0, 300), ("300-1k", 300, 1000), ("1k-4k", 1000, 4000),
           ("4k-8k", 4000, 8000), ("8k-16k", 8000, 16000), (">=16k", 16000, 10**9)]
for name, (brand, _, _, sz) in all_docs.items():
    for label, lo, hi in BUCKETS:
        if lo <= sz < hi:
            size_buckets[label] += 1
            break
    if sz < 300:
        size_outliers["too_small"].append((name, brand, sz))
    elif sz >= 16000:
        size_outliers["too_large"].append((name, brand, sz))
size_outliers["too_small"].sort(key=lambda x: x[2])
size_outliers["too_large"].sort(key=lambda x: -x[2])

# ---------- 可疑 H1 ----------
DISAMBIG_BAD = ["汉语词汇", "词语)", "成语)", "汉字)", "演艺公司", "民国藏书",
                "上古凶兽", "（书法", "（神话", "（地名"]
suspect_h1 = []
for name, (brand, _, text, _) in all_docs.items():
    h1 = text.split("\n", 1)[0]
    if any(k in h1 for k in DISAMBIG_BAD):
        suspect_h1.append((name, brand, h1.strip()[:80]))

# ---------- 字段统计：**bold** 标记 ----------
FIELD_PAT = re.compile(r"\*\*([一-鿿]{2,8})\*\*")
field_counts = Counter()
for name, (_, _, text, _) in all_docs.items():
    found = set(FIELD_PAT.findall(text))
    for f in found:
        field_counts[f] += 1

# ---------- 字段统计：行首"中文字段：" 模式 ----------
LINE_FIELD_PAT = re.compile(r"^([一-鿿]{2,8})[：:]", re.MULTILINE)
line_field_counts = Counter()
for name, (_, _, text, _) in all_docs.items():
    found = set(LINE_FIELD_PAT.findall(text))
    for f in found:
        line_field_counts[f] += 1

# 合并：取**bold**和"行首字段"的并集（任一出现就算）
combined_fields = Counter()
for name, (_, _, text, _) in all_docs.items():
    found = set(FIELD_PAT.findall(text)) | set(LINE_FIELD_PAT.findall(text))
    for f in found:
        combined_fields[f] += 1

# ---------- 交叉引用 ----------
# 只对长度 >=3 的名字算引用（避免 "苍"/"宵" 这种短名误命中）
ref_counts = Counter()
name_set = set(all_docs.keys())
for src_name, (_, _, text, _) in all_docs.items():
    # 给文本里的名字打一遍标
    for other_name in name_set:
        if other_name == src_name:
            continue
        if len(other_name) < 3:
            continue
        if other_name in text:
            ref_counts[other_name] += 1

orphans = [n for n in all_docs if ref_counts[n] == 0 and len(n) >= 3]
orphans.sort(key=lambda n: (all_docs[n][0], n))

# 短名（<3 字符）单独列出
short_names = [n for n in all_docs if len(n) < 3]
short_names.sort(key=lambda n: (all_docs[n][0], n))

# 引用最多的角色
top_refed = ref_counts.most_common(20)

# ---------- 写报告 ----------
lines = []
lines.append("# 角色 docs lint 报告\n")
lines.append(f"扫描时间：{__import__('time').strftime('%Y-%m-%d %H:%M:%S')}")
lines.append(f"总文件数：{len(all_docs)}\n")

lines.append("## 厂牌分布")
for b, names in brands.items():
    lines.append(f"- {b}: **{len(names)}**")
lines.append("")

lines.append("## Size 分布")
for label, _, _ in BUCKETS:
    lines.append(f"- {label:<8}: {size_buckets[label]}")
lines.append("")

lines.append(f"## Size 异常 - 太小 (<300 字节，共 {len(size_outliers['too_small'])} 个)")
lines.append("最小的 40 个：\n")
for name, brand, sz in size_outliers["too_small"][:40]:
    lines.append(f"- {sz:>4} `{brand}/{name}`")
lines.append("")

lines.append(f"## Size 异常 - 太大 (>=16KB，共 {len(size_outliers['too_large'])} 个)")
lines.append("最大的 20 个：\n")
for name, brand, sz in size_outliers["too_large"][:20]:
    lines.append(f"- {sz:>6} `{brand}/{name}`")
lines.append("")

lines.append(f"## 可疑 H1（带消歧义后缀，共 {len(suspect_h1)} 个）")
for name, brand, h1 in suspect_h1:
    lines.append(f"- `{brand}/{name}`: `{h1}`")
lines.append("")

lines.append("## 字段使用频率（**bold** 标记 + 行首 `中文字段：` 取并集）")
lines.append("Top 40 字段及覆盖率：\n")
for f, c in combined_fields.most_common(40):
    pct = 100 * c / len(all_docs)
    lines.append(f"- `{f}`: {c} docs ({pct:.0f}%)")
lines.append("")

lines.append(f"## 引用最多的角色 (top 20)")
for n, c in top_refed:
    brand = all_docs[n][0]
    lines.append(f"- {c:>4} 次  `{brand}/{n}`")
lines.append("")

lines.append(f"## 短名 (<3 字符，共 {len(short_names)} 个，需特殊处理)")
for n in short_names:
    brand = all_docs[n][0]
    lines.append(f"- `{brand}/{n}`")
lines.append("")

lines.append(f"## 孤儿（没有任何其它 doc 提到，name 长度 >=3，共 {len(orphans)} 个）")
lines.append("前 100 个：\n")
for o in orphans[:100]:
    brand, _, _, sz = all_docs[o]
    lines.append(f"- `{brand}/{o}` ({sz}b)")

OUT.write_text("\n".join(lines), encoding="utf-8")

# 控制台 summary
print(f"总文件：{len(all_docs)}  (pili={len(brands['pili'])}, jinguang={len(brands['jinguang'])}, dongli={len(brands['dongli'])})")
print()
print("Size 分布：")
for label, _, _ in BUCKETS:
    print(f"  {label:<8}: {size_buckets[label]}")
print()
print(f"Size 异常：太小 {len(size_outliers['too_small'])}，太大 {len(size_outliers['too_large'])}")
print(f"可疑 H1：{len(suspect_h1)}")
print(f"短名 (<3 字符)：{len(short_names)}")
print(f"孤儿（无外部引用）：{len(orphans)}")
print()
print(f"Top 10 字段：")
for f, c in combined_fields.most_common(10):
    pct = 100 * c / len(all_docs)
    print(f"  {f}: {c} docs ({pct:.0f}%)")
print()
print(f"完整报告：{OUT}")
