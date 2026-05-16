#!/usr/bin/env python3
"""跑一批指定 name 的 baidu_scrape，共享一个 Playwright browser。

复用 baidu_scrape.py 的 fetch_one()，避免每次重启 chromium。

用法:
    python pull_batch.py priority   # 跑硬编码的 13 优先列表
    python pull_batch.py auto 50    # 自动挑 50 个最小未抓 stub
    python pull_batch.py both 50    # 13 优先 + 50 auto
"""
from __future__ import annotations
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from baidu_scrape import (  # noqa: E402
    fetch_one,
    log,
    load_state,
    save_state,
    RAW_DIR,
)
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# 13 优先列表（之前规划好的 20 中剩余）
PRIORITY = [
    "月灵公主", "风雪一路禅", "妲眸姬", "不二刀", "炎无心",
    "傲刀缳莺", "司马骏业", "金小侠", "翳流教主", "六聪天乞",
    "楚君仪", "绝日狂图", "剑谪仙",
]


def pick_auto(n: int, exclude: set[str]) -> list[str]:
    """从 docs/角色 挑 n 个最小 stub（<2KB），跳过已有 raw_baidu 的、跳过 exclude。"""
    docs = ROOT / "docs" / "角色"
    cands = []
    for f in sorted(docs.rglob("*.md")):
        if f.name in ("index.md", ".pages"):
            continue
        if f.stat().st_size >= 2000:
            continue
        name = f.stem
        if name in exclude:
            continue
        raw = RAW_DIR / f"{name}.md"
        if raw.exists() and raw.stat().st_size > 200:
            continue
        cands.append((f.stat().st_size, name))
    cands.sort()
    # 去重（同名跨厂牌只挑一次）
    seen = set()
    out = []
    for _, name in cands:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= n:
            break
    return out


def run(names: list[str], delay: float = 2.0) -> None:
    state = load_state()
    success = failed = cached = 0

    user_data_dir = Path(__file__).resolve().parent / ".pw_userdata"
    user_data_dir.mkdir(exist_ok=True)

    log(f"开始批量抓：{len(names)} 个，延迟 {delay}s/请求")

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        try:
            for i, name in enumerate(names, 1):
                key = f"batch::{name}"
                result = fetch_one(browser, name)
                if result.get("cached"):
                    cached += 1
                    log(f"[{i}/{len(names)}] · {name} 已缓存")
                    continue
                if result["ok"]:
                    success += 1
                    state["scraped"][key] = {
                        "ts": int(time.time()),
                        "chars": result.get("char_count", 0),
                    }
                    log(f"[{i}/{len(names)}] ✓ {name} {result.get('char_count', 0):,} 字")
                else:
                    failed += 1
                    state["failed"][key] = {
                        "ts": int(time.time()),
                        "reason": result["reason"],
                    }
                    log(f"[{i}/{len(names)}] ✗ {name} {result['reason']}")

                if i % 10 == 0:
                    save_state(state)

                if i < len(names):
                    time.sleep(delay + random.random() * 1.0)
        finally:
            browser.close()

    save_state(state)
    log(f"完成：成功 {success}，失败 {failed}，缓存跳过 {cached}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    mode = sys.argv[1]

    if mode == "priority":
        names = PRIORITY[:]
    elif mode == "auto":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        names = pick_auto(n, exclude=set(PRIORITY))
    elif mode == "both":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        names = PRIORITY[:] + pick_auto(n, exclude=set(PRIORITY))
    else:
        print(f"unknown mode: {mode}")
        sys.exit(1)

    run(names)


if __name__ == "__main__":
    main()
