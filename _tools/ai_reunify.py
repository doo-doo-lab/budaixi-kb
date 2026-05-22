#!/usr/bin/env python3
"""ai_reunify — 把多源拼接的角色 doc 统一成「frontmatter + 干净叙事 H2」。

跟 ai_reformat.py（已过时，造正文基本信息表）不同：本工具
- **保留 frontmatter**（infobox 渲染它），删掉正文里跟 frontmatter 重复的字段 dump
- 删来源接缝噪音（=== / 播报编辑 / swatch HTML / 杂学 残留标签）
- 正文重排成一致 H2（经历/人际/能力/配乐/相关作品/来自百度百科）
- 叙事内容、列表、诗号 一字不丢

# 双重校验（关键）
1. 16 字滑窗 ≥85%：output 几乎全部来自原文（防 LLM 编造）
2. 长句保全：原文每个 ≥30 字叙事句必须在 output 出现（防 LLM 过度删除真内容）
3. frontmatter 字段不丢

失败保留原文，永不破坏数据。本轮只处理「有 frontmatter 且 <SIZE_CAP」的 doc。

用法:
    DEEPSEEK_API_KEY=sk-xxx python ai_reunify.py docs/角色/pili/一线生.md          # 单篇 dry-run
    DEEPSEEK_API_KEY=sk-xxx python ai_reunify.py docs/角色/pili/一线生.md --apply  # 单篇应用
    DEEPSEEK_API_KEY=sk-xxx python ai_reunify.py docs/角色 --limit 8               # 前 8 篇 dry-run
    DEEPSEEK_API_KEY=sk-xxx python ai_reunify.py docs/角色 --apply                 # 全量应用
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import httpx
    from openai import OpenAI
except ImportError:
    print("[!] 缺 openai：pip install openai httpx")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs" / "角色"
STATE_FILE = Path(__file__).resolve().parent / ".reunify_state.json"
LOG_FILE = Path(__file__).resolve().parent / "ai_reunify.log"

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
API_BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"

SIZE_CAP = 20000          # >20KB 本轮跳过（输出 token 上限风险，留单独 chunk 处理）
VALIDATION_MIN_MATCH = 0.85
WINDOW_SIZE = 16
WINDOW_STEP = 8
LONG_SENT_MIN = 30        # ≥此长度的句子视为叙事，必须保全
LONG_SENT_MISS_TOL = 0.05 # 允许最多 5% 长句丢失（容标点/分句差异）

SYSTEM_PROMPT = """你是台湾布袋戏角色维基的「统一格式」助手。我给你一篇 markdown 文档（YAML frontmatter + 正文）。正文是多个爬虫来源拼接出来的，有大量跟 frontmatter 重复的字段 dump、来源接缝、格式噪音。

你的任务：产出统一、干净的版本。**这是重排 + 去冗余，不是改写、不是总结。**

# 必须原样保留（逐字不改）

1. **整块 YAML frontmatter**（从开头 `---` 到第二个 `---`），所有字段、缩进、值一个字都不能动
2. **所有叙事句子**：人物经历、剧情描述、设定说明、角色评价——逐字保留，名词/剧集名/招式名/数字/年份/集数/诗号/标点全部不变
3. **列表内容**：招式、武器、武学、配乐、奖项、登场作品、人际关系名单
4. **lead 段**（H1 下面第一段）

# 应该删除（只删这些）

1. **正文里跟 frontmatter 重复的字段 dump**：例如正文出现 `**性别**\n\n男`、`初登场\n\n霹雳金光 第13集`、`称号\n\n隐闭红尘`、`根据地\n\nXXX`——这些 frontmatter 已经有了、页面 infobox 会自动渲染，正文里这堆是冗余，删掉
2. **来源接缝/噪音**：`===` 分隔条、`播报编辑`、`订阅`、`有用+1`、swatch 色块 HTML（`<span class="bdx-swatch"...>` 那几行和 `#xxxxxx` 色值）、爬虫残留的孤立标签如单独成行的 `杂学`
3. **完全重复的句子/段落**（字字相同出现 2 次，保留第一次）

# 绝对禁止

1. ❌ 不得添加任何原文没有的字（即使你"认识"这个角色，也不能加）
2. ❌ 不得改写句子、改变含义、做总结
3. ❌ 不得删除任何叙事内容、列表项、诗号
4. ❌ 不得修改 frontmatter 的任何字段
5. ❌ 不得加"综上"、"以上"、"整理后"之类的话

# 输出结构（H2 用原文已有的章节名，按这个大致顺序归类）

```
---
（frontmatter 原样）
---

# 角色名

（lead 段，逐字）

## 角色背景 / 角色设定 / 形象设定
（原文设定类叙事段，删掉其中的字段 dump，保留描述性句子）

## 角色经历 / 人物经历
（原文剧情叙事，逐字，按句理顺成段）

## 人物关系 / 人际关系
（关系名单，删掉 frontmatter 已有的重复 + 孤立"杂学"标签）

## 角色能力 / 武学 / 武器
（招式武器列表）

## 角色配乐 / 相关作品 / 获奖记录
（原文列表）

## 来自百度百科的补充
（如果原文有这节，原样保留其下内容）
```

只输出整理后的 markdown，不要任何前言后语，不要用 ```markdown``` 包裹。"""


def log(msg: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"processed": {}, "failed": {}, "skipped": {}}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def split_frontmatter(text: str) -> tuple[str, str]:
    """返回 (frontmatter_block_含---, body)。无 frontmatter 返回 ('', text)。"""
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end < 0:
        return "", text
    fm = text[: end + 5]
    body = text[end + 5:]
    return fm, body


def normalize_for_check(text: str) -> str:
    text = re.sub(r"(?m)^#{1,6}\s+.*$", "", text)          # 标题
    text = re.sub(r"(?m)^\|[\s\-:|]+$", "", text)           # 表分隔
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(?m)^[\-\*\+]\s+", "", text)
    text = re.sub(r"\|", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"[^一-鿿㐀-䶿a-zA-Z0-9]", "", text)
    return text


def extract_long_sentences(body: str) -> list[str]:
    """从正文抽 ≥LONG_SENT_MIN 字的【真叙事句】（归一化后）。用于防过度删除。

    关键：只算「含句末标点 。！？」的散文句子。字段 dump（如「性别\\n\\n男\\n\\n初登场\\n\\n...」）
    没有句号，归一化后虽长但不是叙事，必须排除——否则 LLM 正确删 dump 反被误判过度删除。
    """
    b = re.sub(r"<[^>]+>", "", body)
    b = re.sub(r"(?m)^#{1,6}\s+.*$", "", b)  # 去标题
    out = []
    # 在句末标点处切分，保留标点跟前句一起
    for seg in re.split(r"(?<=[。！？])", b):
        if not ("。" in seg or "！" in seg or "？" in seg):
            continue  # 不含句末标点 → 不是叙事散文（是 dump / 列表 / 标签），跳过
        norm = normalize_for_check(seg)
        if len(norm) >= LONG_SENT_MIN:
            out.append(norm)
    return out


def validate(original: str, output: str) -> tuple[bool, str]:
    if not output or len(output) < 100:
        return False, "输出太短"

    orig_fm, orig_body = split_frontmatter(original)
    out_fm, out_body = split_frontmatter(output)

    # 1. frontmatter 保留
    if orig_fm:
        if not out_fm:
            return False, "frontmatter 丢失"
        o_keys = set(re.findall(r"(?m)^([\w]+):", orig_fm))
        n_keys = set(re.findall(r"(?m)^([\w]+):", out_fm))
        missing = o_keys - n_keys
        if missing:
            return False, f"frontmatter 丢字段: {missing}"
        # frontmatter 内容应一字不改（允许尾部空白差异）
        if orig_fm.strip() != out_fm.strip():
            return False, "frontmatter 内容被改动"

    inp = normalize_for_check(original)
    out = normalize_for_check(output)

    # 2. 16 字滑窗 ⊆ 原文（防编造）
    matched = total = 0
    fails = []
    for i in range(0, len(out) - WINDOW_SIZE + 1, WINDOW_STEP):
        chunk = out[i: i + WINDOW_SIZE]
        total += 1
        if chunk in inp:
            matched += 1
        elif len(fails) < 3:
            fails.append(chunk)
    if total == 0:
        return False, "无可检查窗口"
    rate = matched / total
    if rate < VALIDATION_MIN_MATCH:
        return False, f"匹配率 {rate:.1%}（疑似编造），失败片段：{fails}"

    # 3. 长句保全（防过度删除叙事）
    long_sents = extract_long_sentences(orig_body)
    if long_sents:
        missing_sents = [s for s in long_sents if s not in out]
        miss_rate = len(missing_sents) / len(long_sents)
        if miss_rate > LONG_SENT_MISS_TOL:
            sample = [s[:24] for s in missing_sents[:3]]
            return False, f"长句丢失 {miss_rate:.1%}（{len(missing_sents)}/{len(long_sents)} 句，疑似过度删除）：{sample}"

    return True, f"匹配率 {rate:.1%}，长句保全 {len(long_sents)-len([s for s in long_sents if s not in out])}/{len(long_sents)}"


def call_reunify(client: OpenAI, doc: str) -> str:
    user_msg = "下面是要统一格式的文档：\n\n```markdown\n" + doc + "\n```\n\n请按系统指令产出统一版本。"
    last_err = None
    for attempt in range(3):
        try:
            stream = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=8192,
                stream=True,
            )
            chunks = []
            for ch in stream:
                if ch.choices and ch.choices[0].delta and ch.choices[0].delta.content:
                    chunks.append(ch.choices[0].delta.content)
            out = "".join(chunks).strip()
            out = re.sub(r"^```(?:markdown|md)?\s*\n", "", out)
            out = re.sub(r"\n```\s*$", "", out)
            if out:
                return out.strip()
            last_err = RuntimeError("空输出")
        except Exception as e:
            last_err = e
            print(f"  [!] attempt {attempt+1}/3: {type(e).__name__}: {e}", flush=True)
        time.sleep(2 + attempt * 3)
    raise last_err or RuntimeError("reunify 全部失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="文件或目录")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--resume", action="store_true", help="跳过已处理")
    args = ap.parse_args()

    if not API_KEY:
        print("[!] 缺 DEEPSEEK_API_KEY 环境变量")
        sys.exit(1)

    target = Path(args.target).resolve()
    if target.is_file():
        files = [target]
    else:
        files = [
            f for f in sorted(target.rglob("*.md"))
            if f.name not in ("index.md", ".pages")
            and not any(
                part.startswith(".") or part in ("reunify_preview", "samples_out")
                for part in f.parts
            )
        ]

    state = load_state()
    todo = []
    for f in files:
        key = str(f).replace("\\", "/")
        if args.resume and key in state["processed"]:
            continue
        text = f.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        if not fm:
            state["skipped"][key] = {"reason": "无 frontmatter（本轮跳过）"}
            continue
        if len(text) > SIZE_CAP:
            state["skipped"][key] = {"reason": f"过大 {len(text)}B（本轮跳过）"}
            continue
        todo.append(f)

    if args.limit:
        todo = todo[: args.limit]

    if not todo:
        log("没有待处理文件")
        save_state(state)
        return

    log(f"开始：{len(todo)} 篇待 reunify（{'APPLY' if args.apply else 'DRY-RUN'}），model={MODEL}")
    client = OpenAI(
        api_key=API_KEY, base_url=API_BASE,
        timeout=httpx.Timeout(connect=15, read=180, write=15, pool=15),
        max_retries=0,
    )

    success = failed = 0
    for i, f in enumerate(todo, 1):
        key = str(f).replace("\\", "/")
        original = f.read_text(encoding="utf-8")
        try:
            out = call_reunify(client, original)
        except Exception as e:
            failed += 1
            state["failed"][key] = {"ts": int(time.time()), "reason": str(e)}
            log(f"[{i}/{len(todo)}] ✗ {f.stem}  API 错误：{e}")
            continue

        ok, reason = validate(original, out)
        if not ok:
            failed += 1
            state["failed"][key] = {"ts": int(time.time()), "reason": reason}
            log(f"[{i}/{len(todo)}] ✗ {f.stem}  {reason}")
            continue

        if args.apply:
            backup = f.parent / ".pre_reunify_backup"
            backup.mkdir(exist_ok=True)
            (backup / f.name).write_text(original, encoding="utf-8")
            f.write_text(out, encoding="utf-8")
            state["processed"][key] = {"ts": int(time.time()), "in": len(original), "out": len(out)}
            log(f"[{i}/{len(todo)}] ✓ APPLIED {f.stem}  {len(original)}→{len(out)}字  {reason}")
        else:
            # dry-run：写到 samples_out/ 供人看
            sout = Path(__file__).resolve().parent / "reunify_preview"
            sout.mkdir(exist_ok=True)
            (sout / f.name).write_text(out, encoding="utf-8")
            log(f"[{i}/{len(todo)}] ✓ DRY {f.stem}  {len(original)}→{len(out)}字  {reason}  (预览: reunify_preview/{f.name})")
        success += 1

        if i % 5 == 0:
            save_state(state)

    save_state(state)
    log(f"完成：成功 {success}，失败 {failed}")


if __name__ == "__main__":
    main()
