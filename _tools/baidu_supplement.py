#!/usr/bin/env python3
"""为 raw_baidu/{name}.md 补充百度页 basicInfo 表（Readability 剪掉的那部分）。

流程：
1. 从已存在的 raw_baidu/{name}.md 提取来源 URL
2. curl baidu 原始 HTML
3. BS4 解析 <dt class="basicInfo-item"> / <dd>（含 paraTitle h2/h3 也补回）
4. 把 basicInfo 表插入到 raw_baidu/{name}.md 的 "## 基本信息（来自百度百科）" 段后

只追加内容，不删原文。**完全保留 baidu 原始文字，不总结不改写**。
"""
from __future__ import annotations
import argparse
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("缺 bs4: pip install beautifulsoup4", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(__file__).resolve().parent / "raw_baidu"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def fetch_html(url: str, retries: int = 4) -> str | None:
    """直接 urllib 抓 baidu 原页面。失败返回 None。带 retry+backoff 应对 baidu SSL 限流。"""
    # 把 URL path 里的中文 percent-encode
    parsed = urllib.parse.urlsplit(url)
    encoded_path = urllib.parse.quote(parsed.path, safe="/%")
    safe_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, encoded_path, parsed.query, parsed.fragment)
    )
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            safe_url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "close",  # 不复用连接，减少 SSL 池问题
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, Exception) as e:
            last_err = e
            if attempt < retries - 1:
                wait = 3 + attempt * 5  # 3, 8, 13s backoff
                time.sleep(wait)
                continue
    print(f"  fetch err after {retries} retries: {last_err}", file=sys.stderr)
    return None


def extract_basicinfo(html: str) -> list[tuple[str, str]]:
    """从 baidu 原 HTML 抽 basicInfo 字段。返回 [(key, value), ...]."""
    soup = BeautifulSoup(html, "html.parser")
    dts = soup.find_all("dt", class_=re.compile(r"basicInfo"))
    dds = soup.find_all("dd", class_=re.compile(r"basicInfo"))
    pairs: list[tuple[str, str]] = []
    for dt, dd in zip(dts, dds):
        k = re.sub(r"\s+", "", dt.get_text(strip=True))
        v = dd.get_text(strip=True)
        v = re.sub(r"\s*\[\d+(?:[-–]\d+)?\]\s*", "", v)  # 去 citation
        v = re.sub(r"\s+", " ", v).strip()
        if k and v:
            pairs.append((k, v))
    return pairs


def get_url_from_md(md_path: Path) -> str | None:
    """从 raw_baidu md 文件第 3 行附近提取 URL。"""
    for line in md_path.read_text(encoding="utf-8").splitlines()[:10]:
        m = re.match(r"^\s*-\s*\*\*来源\*\*:\s*(\S+)", line)
        if m:
            return m.group(1)
    return None


def md_already_has_basicinfo(md_text: str, pairs: list[tuple[str, str]]) -> bool:
    """启发式：看 md 是否已经包含大部分 basicInfo 字段。"""
    if not pairs:
        return True
    # 检查前 4 个 key 是否出现在 md 文本
    hits = 0
    for k, _ in pairs[:4]:
        if k in md_text:
            hits += 1
    return hits >= 3  # 4 个中 3 个出现 = 已有


def inject_basicinfo(md_text: str, pairs: list[tuple[str, str]]) -> str:
    """把 basicInfo 表注入到 ## 基本信息（来自百度百科）章节末尾。"""
    block_lines = ["", "### 基本信息表（来自百度页 dl）", ""]
    for k, v in pairs:
        block_lines.append(f"- **{k}**: {v}")
    block = "\n".join(block_lines) + "\n"

    # 找下一个 ## 章节边界
    lines = md_text.splitlines()
    # 找 "## 基本信息（来自百度百科）" 之后下一个 ## 的位置
    start_idx = None
    for i, line in enumerate(lines):
        if line.startswith("## 基本信息（来自百度百科）"):
            start_idx = i
            break
    if start_idx is None:
        # 没有该章节，插入到 URL 行后
        for i, line in enumerate(lines):
            if line.startswith("- **来源**:"):
                lines.insert(i + 1, "")
                lines.insert(i + 2, "## 基本信息（来自百度百科）")
                lines.insert(i + 3, block)
                return "\n".join(lines)
        # 实在不行，文件尾
        return md_text + "\n\n## 基本信息（来自百度百科）\n" + block

    # 找下一个 ## 章节
    next_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("## "):
            next_idx = j
            break
    # 在 next_idx 前插入
    insert = block_lines + [""]
    new_lines = lines[:next_idx] + insert + lines[next_idx:]
    return "\n".join(new_lines).rstrip() + "\n"


def supplement_one(name: str, force: bool = False, delay: float = 1.0) -> str:
    md_path = RAW_DIR / f"{name}.md"
    if not md_path.exists():
        return "missing_md"

    url = get_url_from_md(md_path)
    if not url:
        return "no_url"

    html = fetch_html(url)
    if not html:
        return "fetch_failed"

    pairs = extract_basicinfo(html)
    if not pairs:
        return "no_basicinfo"

    md_text = md_path.read_text(encoding="utf-8")
    if not force and md_already_has_basicinfo(md_text, pairs):
        return "already_has"

    new_text = inject_basicinfo(md_text, pairs)
    md_path.write_text(new_text, encoding="utf-8")
    time.sleep(delay)
    return f"added_{len(pairs)}_fields"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="要补的角色名；不写则全部 raw_baidu/*.md")
    ap.add_argument("--force", action="store_true", help="即使已有也覆盖添加")
    ap.add_argument("--delay", type=float, default=1.0, help="每个 fetch 之间延迟秒")
    args = ap.parse_args()

    if args.names:
        names = args.names
    else:
        names = sorted(p.stem for p in RAW_DIR.glob("*.md"))

    print(f"补 basicInfo: {len(names)} 个文件")
    counts = {"added": 0, "already_has": 0, "no_basicinfo": 0, "fail": 0}
    for i, name in enumerate(names, 1):
        result = supplement_one(name, force=args.force, delay=args.delay)
        if result.startswith("added"):
            counts["added"] += 1
            print(f"  [{i:3d}/{len(names)}] ✓ {name} {result}")
        elif result == "already_has":
            counts["already_has"] += 1
        elif result == "no_basicinfo":
            counts["no_basicinfo"] += 1
        else:
            counts["fail"] += 1
            print(f"  [{i:3d}/{len(names)}] ✗ {name} {result}")
    print(f"\n汇总: added={counts['added']} already={counts['already_has']} no_info={counts['no_basicinfo']} fail={counts['fail']}")


if __name__ == "__main__":
    main()
