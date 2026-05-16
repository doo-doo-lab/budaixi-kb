#!/usr/bin/env python3
"""把 mcp__open-websearch__fetchWebContent 的结果清洗成 raw_baidu/{name}.md。

解析 result.readableHtml（百度页 readability 后的干净 HTML），按 h2/p 重建章节结构。
只做格式整理 + 去 baidu UI 噪音（订阅/播报/编辑/参考资料/citation [N]/image caption）。
**绝不总结、绝不改写内容**——所有文字都来自 baidu，仅按章节归位。

用法：
    python clean_baidu_v2.py --name "月灵公主" --url "https://baike.baidu.com/item/月灵公主/4289701" --input "tmp.json"

tmp.json 是 fetchWebContent 返回的 JSON 字符串（保存到文件）。
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("缺 bs4: pip install beautifulsoup4", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "raw_baidu"

# 噪音文本（整行匹配跳过）
NOISE_EXACT = {
    "订阅", "有用+1", "播报", "编辑", "讨论", "收藏", "分享",
    "上传视频", "创建人物关系", "展开", "全部",
    "下一图集", "查看更多", "图集",
    # baidu 把 svg 旁边的 span 文字拼起来后常见的合并形式
    "播报编辑", "讨论编辑",
}

# 噪音 regex（match → 跳过整行）
NOISE_PATTERNS = [
    re.compile(r"^\d*有用\+\d+$"),                  # "0有用+1"、"3有用+1"
    re.compile(r"^展开\d+个同名词条$"),               # "展开2个同名词条"
    re.compile(r"^\d+个同名词条$"),                   # "2个同名词条"
    re.compile(r"^本词条是一个多义词"),               # 多义词页提示
    re.compile(r"^\d{1,3}:\d{2}(:\d{2})?$"),         # 视频时长 "12:34"
    re.compile(r"^\[\d+(?:[-–]\d+)?\]$"),            # 纯 citation 行
]

# 噪音前缀
NOISE_PREFIXES = (
    "©", "京ICP", "京公网", "百度首页",
    "试卷", "数字博物馆", "非遗百科",
)


def is_noise(t: str) -> bool:
    if t in NOISE_EXACT:
        return True
    if t.startswith(NOISE_PREFIXES):
        return True
    for pat in NOISE_PATTERNS:
        if pat.match(t):
            return True
    return False


def clean_text(t: str) -> str:
    """单行文本清理：去 citation、合并多空格。"""
    if not t:
        return ""
    # 去 [N] [N-M] citation
    t = re.sub(r"\s*\[\d+(?:[-–]\d+)?\]\s*", "", t)
    # 合并空白
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_from_html(html: str, lemma_name: str) -> tuple[str, list[tuple[str, str]]]:
    """从 readableHtml 解析出 (lemma_desc, [(section_name, section_content), ...]).

    lemma_desc: 词条简介（lead 段落，在第一个 h2 之前）
    sections: 章节列表，按文档顺序
    """
    soup = BeautifulSoup(html, "html.parser")

    # 找正文容器
    root = soup.find(id="J-lemma-main-wrapper") or soup

    lead_parts: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    current_section: str | None = None
    current_content: list[str] = []

    # 词条副标题（lemma desc / 副标题）— 通常在 #lemmaDesc 内
    lemma_desc_div = root.find(id="lemmaDesc")
    if lemma_desc_div:
        for p in lemma_desc_div.find_all("p"):
            t = clean_text(p.get_text(strip=True))
            if t and not is_noise(t):
                lead_parts.append(t)

    # 遍历 root 内所有 h2/h3/p
    for elem in root.find_all(["h2", "h3", "p", "li", "td"]):
        if elem.name == "h2":
            # 保存上一个 section
            if current_section is not None:
                sections.append((current_section, "\n\n".join(current_content)))
            current_section = clean_text(elem.get_text(strip=True))
            current_content = []
        elif elem.name == "h3":
            # 子标题作为 markdown ### 标题
            sub = clean_text(elem.get_text(strip=True))
            if sub and current_section is not None:
                current_content.append(f"### {sub}")
        else:
            # p / li / td 都视作段落
            # 跳过被 h2/h3 包含的（已处理）
            if elem.find_parent(["h2", "h3"]):
                continue
            # 跳过被 #lemmaDesc 包含的（已处理）
            if elem.find_parent(id="lemmaDesc"):
                continue
            t = clean_text(elem.get_text(strip=True))
            if not t or is_noise(t):
                continue
            # 跳过图集 caption: "{lemma_name}的图片"
            if t == f"{lemma_name}的图片":
                continue

            if current_section is None:
                # 第一个 h2 之前：lead
                # 但已经处理过 lemmaDesc，所以这里也可能有更多 lead 段
                if t not in lead_parts:  # 去重
                    lead_parts.append(t)
            else:
                # 去重短重复行
                if t in current_content:
                    continue
                current_content.append(t)

    # 保存最后一个 section
    if current_section is not None:
        sections.append((current_section, "\n\n".join(current_content)))

    lemma_desc = "\n\n".join(lead_parts)
    return lemma_desc, sections


def build_markdown(name: str, url: str, lemma_desc: str, sections: list[tuple[str, str]]) -> str:
    parts = [f"# {name}", "", f"- **来源**: {url}", ""]
    if lemma_desc:
        parts.append("## 基本信息（来自百度百科）")
        parts.append("")
        parts.append(lemma_desc)
        parts.append("")
    for sec_name, sec_content in sections:
        if not sec_content.strip():
            continue
        parts.append(f"## {sec_name}")
        parts.append("")
        parts.append(sec_content)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="角色名")
    ap.add_argument("--url", required=True, help="baidu 完整 URL")
    ap.add_argument("--input", required=True, help="fetchWebContent JSON 结果文件")
    ap.add_argument("--stdout", action="store_true", help="输出到 stdout 而不是文件")
    args = ap.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    html = data.get("readableHtml") or ""
    if not html:
        # 退而求其次：用 content 字段
        content = data.get("content") or ""
        if not content:
            print("ERR: 没有 readableHtml 也没有 content", file=sys.stderr)
            sys.exit(2)
        # 没有 HTML 结构信息，只能整段输出
        md = f"# {args.name}\n\n- **来源**: {args.url}\n\n## 基本信息（来自百度百科）\n\n{clean_text(content)}\n"
    else:
        lemma_desc, sections = extract_from_html(html, args.name)
        if not lemma_desc and not sections:
            print("ERR: 解析后没有内容（可能是非布袋戏词条或多义词页）", file=sys.stderr)
            sys.exit(3)
        md = build_markdown(args.name, args.url, lemma_desc, sections)

    if args.stdout:
        sys.stdout.write(md)
    else:
        OUT_DIR.mkdir(exist_ok=True)
        out_path = OUT_DIR / f"{args.name}.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"OK {out_path} ({len(md)} chars)")


if __name__ == "__main__":
    main()
