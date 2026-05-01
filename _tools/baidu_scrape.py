#!/usr/bin/env python3
"""用 Playwright 真实 Chrome 抓百度百科（绕开 baidu 反爬）。

只保存原文，不总结、不删改。仅过滤百度自身的 UI 噪音（导航、广告、参考资料等）。

抓到的页面写到 _tools/raw_baidu/{name}.md。

用法:
    python baidu_scrape.py docs/角色 --threshold 2000 --limit 10  # 跑前 10 个
    python baidu_scrape.py docs/角色/pili/吞佛童子.md             # 单文件
    python baidu_scrape.py docs/角色 --threshold 2000             # 全部 <2KB
"""
from __future__ import annotations
import argparse
import json
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("[!] 缺 playwright：pip install playwright && python -m playwright install chromium")
    sys.exit(1)

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = Path(__file__).resolve().parent / "raw_baidu"
STATE_FILE = Path(__file__).resolve().parent / ".baidu_scrape_state.json"
LOG_FILE = Path(__file__).resolve().parent / "baidu_scrape.log"

PUPPET_KEYWORDS = [
    "布袋戏", "布袋戲", "霹雳", "霹靂", "金光",
    "东离", "東離", "Thunderbolt",
    "虚拟人物", "虛擬人物", "虚拟角色", "虛擬角色",
    "黄文择", "黄强华", "黄海岱", "黄俊雄", "黄立纲",
]

# 百度 UI 噪音（要从抓到的 HTML 里去掉的 class/element）
NOISE_CLASSES = [
    "polysemantList-wrapper",  # 多义词 header（手动处理）
    "side-content", "before-content", "after-content",  # 侧边广告
    "lemma-reference",  # 参考资料
    "lemma-statistics", "edit-block",  # 编辑统计
    "openingTimes", "wgt-", "side", "share",  # 各种 UI
    "footer", "nav-",
]


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"scraped": {}, "failed": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def is_puppet_content(text: str) -> bool:
    """前 3000 字检测布袋戏关键词。"""
    return any(kw in text[:3000] for kw in PUPPET_KEYWORDS)


def items_to_markdown(items, name, url):
    """把 [{kind, text}] 列表转 markdown。"""
    if not items:
        return None

    md_parts = [f"# {name}\n", f"- **来源**: {url}\n"]

    # 把 dt/dd 配对成基本信息表
    info_pairs = []
    paragraphs = []
    headers_and_paras = []
    pending_dt = None
    for it in items:
        kind = it["kind"]
        text = it["text"].strip()
        text = re.sub(r"\[\d+(?:[-–]\d+)?\]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if kind == "dt":
            pending_dt = text.rstrip("：:")
        elif kind == "dd":
            if pending_dt:
                info_pairs.append((pending_dt, text))
                pending_dt = None
        elif kind in ("h2", "h3"):
            headers_and_paras.append((kind, text))
        else:  # p
            headers_and_paras.append(("p", text))

    # 输出基本信息（如果有）
    if info_pairs:
        md_parts.append("## 基本信息\n")
        md_parts.append("| 字段 | 值 |")
        md_parts.append("|---|---|")
        for k, v in info_pairs:
            md_parts.append(f"| {k} | {v} |")
        md_parts.append("")

    # 输出段落 / 标题（去重短行）
    seen = set()
    for kind, text in headers_and_paras:
        if kind == "p":
            sig = text[:80]
            if sig in seen:
                continue
            seen.add(sig)
            md_parts.append(text + "\n")
        elif kind == "h2":
            md_parts.append(f"## {text}\n")
        elif kind == "h3":
            md_parts.append(f"### {text}\n")

    body = "\n".join(md_parts)
    return {
        "title": name,
        "body_md": body,
        "char_count": len(body),
    }


def parse_baidu_data(data, name, url):
    """处理 fetch_page_data 返回的 dict。返回 dict 或 None。"""
    if not data:
        return None

    # 多义词页：找含布袋戏关键词的链接
    polysem_links = data.get("polysemLinks") or []
    if polysem_links and not data.get("items"):
        for link in polysem_links:
            if any(kw in link.get("text", "") for kw in PUPPET_KEYWORDS):
                return {"redirect": link["href"]}
        return None

    items = data.get("items") or []
    if not items:
        return None

    # 验证：所有文字拼起来必须含布袋戏关键词
    all_text = "\n".join(it["text"] for it in items[:30])
    if not is_puppet_content(all_text):
        return None

    return items_to_markdown(items, name, url)


def parse_baidu_text(text: str, name: str, url: str) -> dict | None:
    """从 inner_text 抽布袋戏角色内容（baidu 动态渲染，HTML class 不稳，纯文本驱动）。

    返回 {title, body_md, char_count} 或 None。
    """
    if not text or len(text) < 200:
        return None

    # 1. 检测多义词页：本词条是多义词
    if "本词条是一个多义词" in text or "请在下列义项中选择浏览" in text:
        # 找含 布袋戏/霹雳/金光/东离 的义项链接（需要在 HTML 处理）
        return {"is_polysem": True}

    # 2. 找 lead 段起点：在出现"上传视频"或"创建人物关系"之后（这之前都是 baidu UI）
    #    然后找 name 第一次以"独立行 / 句子开头"出现的位置作为 lead 起点
    ui_end_markers = ["创建人物关系", "上传视频", "订阅"]
    body_start = 0
    for marker in ui_end_markers:
        i = text.find(marker)
        if i > body_start:
            body_start = i + len(marker)

    # 从 body_start 开始找 name 出现位置
    name_pos = text.find(name, body_start)
    if name_pos < 0:
        # 没找到 name，可能页面不对
        return None
    # 往前推到最近的换行
    prev_nl = text.rfind("\n", 0, name_pos)
    m_start = prev_nl + 1 if prev_nl >= 0 else name_pos

    # 3. 找 body 终点：通常是参考资料/词条贡献者/©/相关词条之类
    end_markers = [
        "参考资料",
        "词条统计",
        "词条贡献者",
        "©2026 Baidu",
        "©2025 Baidu",
        "© Baidu",
        "京ICP证",
        "京公网安备",
        "百度百科合作平台",
    ]
    end_pos = len(text)
    for marker in end_markers:
        i = text.find(marker, m_start)
        if i > 0 and i < end_pos:
            end_pos = i

    body_text = text[m_start:end_pos].strip()

    # 4. 去 UI 噪音（每行级别）
    noise_lines = {
        "播报", "编辑", "讨论", "收藏", "赞", "分享", "登录", "注册",
        "上传视频", "创建人物关系", "更多", "查看更多", "订阅",
        "进入词条", "全站搜索", "国际版帮助", "个人中心", "百度首页",
    }
    noise_prefixes = (
        "©", "京ICP", "京公网", "登录", "注册", "上传", "下载",
        "百度首页", "新人", "校园", "权威合作", "动态百科",
        "数字博物馆", "非遗百科", "艺术百科", "科学百科",
        "知识专题", "加入百科", "进阶成长", "任务广场",
        "百科团队", "分类达人团", "热词团", "繁星团", "蝌蚪团",
        "合作模式", "常见问题", "联系方式", "免责声明", "声明",
    )
    cleaned_lines = []
    seen = set()
    for line in body_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line in noise_lines:
            continue
        if line.startswith(noise_prefixes):
            continue
        # 视频元数据（如 "24:06"）— 跳过纯时长行
        if re.match(r"^\d{1,3}:\d{2}(:\d{2})?$", line):
            continue
        # 数字单独成行的（如订阅数 "971"），跳过短数字
        if re.match(r"^\d{1,4}$", line):
            continue
        # 去脚注号 [1] [3-4]
        line = re.sub(r"\[\d+(?:[-–]\d+)?\]", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line or len(line) < 3:
            continue
        # 去重短行（< 100 字）
        if len(line) < 100:
            sig = line[:60]
            if sig in seen:
                continue
            seen.add(sig)
        cleaned_lines.append(line)

    if not cleaned_lines:
        return None

    body = "\n\n".join(cleaned_lines)

    # 验证：必须含布袋戏关键词
    if not is_puppet_content(body):
        return None

    md = f"# {name}\n\n"
    md += f"- **来源**: {url}\n\n"
    md += body + "\n"

    return {
        "title": name,
        "body_md": md,
        "char_count": len(md),
    }


def parse_baidu_html(html: str, name: str, url: str) -> dict | None:
    """旧入口：用 BS4 + inner_text 提取。

    这里我们用 BS4 解析以获取 inner_text，但内容提取走 parse_baidu_text。
    """
    soup = BeautifulSoup(html, "html.parser")

    # 多义词页 redirect 处理：在 HTML 层面找
    polysem = soup.find(class_=re.compile(r"polysem"))
    if polysem:
        for a in polysem.find_all("a", href=True):
            link_text = a.get_text(strip=True)
            if any(kw in link_text for kw in PUPPET_KEYWORDS):
                href = a["href"]
                if not href.startswith("http"):
                    href = "https://baike.baidu.com" + href
                return {"redirect": href}

    # 拿全文文本走文本提取
    body = soup.find("body")
    if not body:
        return None
    text = body.get_text(separator="\n", strip=True)

    return parse_baidu_text(text, name, url)


def goto_with_retry(page, url, retries=3):
    """goto 带重试。返回 html 或 None。"""
    for attempt in range(retries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(0.5 + random.random() * 1.0)
            return page.content()
        except (PWTimeout, Exception):
            if attempt < retries - 1:
                wait = 3 + attempt * 2 + random.random() * 2
                time.sleep(wait)
                continue
            return None
    return None


# 用 JS 直接抽 baidu 的段落 + 标题 + 基本信息字段（DOM-aware，比 inner_text 准）
EXTRACT_JS = """() => {
    const items = [];
    // 段落 + 标题（按文档顺序）
    document.querySelectorAll(
        'div[class*="para_"], h2[class*="paraTitle"], h3[class*="paraTitle"], ' +
        'h2[class*="para-title"], h3[class*="para-title"], ' +
        'dt[class*="basicInfoItem"], dd[class*="basicInfoItem"], ' +
        'dt[class*="basicInfo-item"], dd[class*="basicInfo-item"]'
    ).forEach(el => {
        const t = (el.innerText || '').trim();
        if (!t) return;
        let kind = 'p';
        if (el.tagName === 'H2') kind = 'h2';
        else if (el.tagName === 'H3') kind = 'h3';
        else if (el.tagName === 'DT') kind = 'dt';
        else if (el.tagName === 'DD') kind = 'dd';
        items.push({kind, text: t});
    });
    // 多义词页检测
    const polysem = document.querySelector('[class*="polysem"]');
    let polysemLinks = [];
    if (polysem) {
        polysem.querySelectorAll('a[href]').forEach(a => {
            polysemLinks.push({text: (a.innerText||'').trim(), href: a.href});
        });
    }
    return {items, polysemLinks};
}"""


def fetch_page_data(page, url):
    """加载 url 并用 JS 抽数据。"""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
    except Exception:
        return None
    time.sleep(0.5 + random.random() * 1.0)
    try:
        return page.evaluate(EXTRACT_JS)
    except Exception:
        return None


def fetch_one(browser, name: str) -> dict:
    """用 Playwright 抓一个角色页。返回 {ok, reason, char_count, output_path}。"""
    out = RAW_DIR / f"{name}.md"
    if out.exists() and out.stat().st_size > 200:
        return {"ok": True, "reason": "已缓存", "cached": True}

    url = f"https://baike.baidu.com/item/{quote(name)}"
    page = browser.new_page()
    try:
        # 重试
        data = None
        for attempt in range(3):
            data = fetch_page_data(page, url)
            if data is not None and (data.get("items") or data.get("polysemLinks")):
                break
            time.sleep(3 + attempt * 2)
    finally:
        page.close()
    if not data:
        return {"ok": False, "reason": "网络/超时（3 次重试都失败）"}

    parsed = parse_baidu_data(data, name, url)
    if not parsed:
        return {"ok": False, "reason": "非布袋戏内容或无主体"}

    # 处理重定向（多义词页指向具体义项）
    if parsed.get("redirect"):
        redirect_url = parsed["redirect"]
        page = browser.new_page()
        try:
            data2 = fetch_page_data(page, redirect_url)
        finally:
            page.close()
        if not data2:
            return {"ok": False, "reason": "重定向后网络失败"}
        parsed = parse_baidu_data(data2, name, redirect_url)
        if not parsed or parsed.get("redirect"):
            return {"ok": False, "reason": "重定向链不通"}

    RAW_DIR.mkdir(exist_ok=True)
    out.write_text(parsed["body_md"], encoding="utf-8")

    return {
        "ok": True,
        "reason": "ok",
        "char_count": parsed["char_count"],
        "output_path": str(out),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="文件或目录")
    ap.add_argument("--threshold", type=int, default=2000, help="目录模式下，<此字节数才抓 baidu")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 个")
    ap.add_argument("--delay", type=float, default=2.0, help="每次抓取之间延迟秒数")
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if target.is_file():
        files = [target]
    else:
        files = [
            f
            for f in sorted(target.rglob("*.md"))
            if f.name not in ("index.md", ".pages")
            and f.stat().st_size < args.threshold
        ]

    if args.limit:
        files = files[: args.limit]

    if not files:
        log("[!] 没有待抓取文件")
        return

    state = load_state()

    log(f"开始：{len(files)} 个角色待抓 baidu，延迟 {args.delay}s/请求")
    success = failed = cached = 0

    # 用 persistent context 保 cookies，mobile UA 减少反爬
    user_data_dir = Path(__file__).resolve().parent / ".pw_userdata"
    user_data_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        try:
            for i, f in enumerate(files, 1):
                name = f.stem
                rel = str(f).replace("\\", "/")

                if rel in state["scraped"]:
                    cached += 1
                    continue

                result = fetch_one(browser, name)
                if result.get("cached"):
                    cached += 1
                    log(f"[{i}/{len(files)}] · {name} 文件已存")
                    continue

                if result["ok"]:
                    success += 1
                    state["scraped"][rel] = {
                        "ts": int(time.time()),
                        "chars": result.get("char_count", 0),
                    }
                    log(f"[{i}/{len(files)}] ✓ {name} 抓 {result.get('char_count', 0):,} 字")
                else:
                    failed += 1
                    state["failed"][rel] = {
                        "ts": int(time.time()),
                        "reason": result["reason"],
                    }
                    log(f"[{i}/{len(files)}] ✗ {name} {result['reason']}")

                if i % 10 == 0:
                    save_state(state)

                if i < len(files):
                    time.sleep(args.delay + random.random() * 1.0)
        finally:
            browser.close()

    save_state(state)
    log(f"\n完成：成功 {success}，失败 {failed}，缓存跳过 {cached}")


if __name__ == "__main__":
    main()
