#!/usr/bin/env python3
"""用 mimo-v2.5-pro（KSYun）整理布袋戏角色页面。

核心：
- 严格 system prompt 禁止 AI 添加任何原文没有的信息
- 输出验证：滑动窗口 char 级别检查，<85% 命中即拒绝并保留原文
- 断点续跑：已处理过的文件跳过（写 .reformat_state.json 记录）
- 失败保留原文，永不破坏数据

用法：
    python ai_reformat.py docs/角色/pili/素还真.md         # 单文件预览（不写）
    python ai_reformat.py docs/角色/pili/素还真.md --apply # 单文件应用
    python ai_reformat.py docs/角色 --limit 5              # 跑前 5 个未处理文件
    python ai_reformat.py docs/角色 --apply                # 跑全部
    python ai_reformat.py docs/角色 --apply --resume       # 接着上次的进度
    python ai_reformat.py docs/角色 --apply --redo         # 全部重跑
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
    print("[!] 缺 openai 包：pip install openai httpx")
    sys.exit(1)

# --------------------------------------------------------------------- 配置
API_KEY = os.environ.get("KSYUN_API_KEY", "29647c86-28a2-46bc-8682-9cb0cecb8d45")
API_BASE = "https://kspmas.ksyun.com/v1"

# 实测：
#   mimo-v2.5-pro：带推理，小文件准（86-100%），但大文件常 timeout
#   mimo-v2.5：    无推理，22KB 文件 2 分钟跑完 99.9%
#   kimi-k2.6：    多次卡住没回应，弃用
MODEL_SMALL = "mimo-v2.5-pro"  # 小文件用 pro（推理更稳）
MODEL_LARGE = "mimo-v2.5"       # 大文件用快版
SIZE_THRESHOLD_BYTES = 8000      # >8KB 自动切快版

STATE_FILE = Path(__file__).parent / ".reformat_state.json"
LOG_FILE = Path(__file__).parent / "ai_reformat.log"

VALIDATION_MIN_MATCH = 0.85  # 输出至少 85% char 窗口在原文出现
WINDOW_SIZE = 16
WINDOW_STEP = 8

SYSTEM_PROMPT = """你是中文百科条目格式整理助手。我给你一篇关于台湾布袋戏角色的 markdown 文档（已初步清洗但格式仍混乱、有多源拼接）。你的任务是 **重排格式**，不是改写内容。

# ⚠️ 极严格的"只能"规则

你**唯二**被允许删除的东西：

1. **完全重复的句子/段落**：原文中字字相同地出现了 2 次或以上，可以保留第一次出现，删除后续重复
2. **明显跟布袋戏完全无关的内容**：例如把一个角色页错爬成了"汉语词语解释"或"政治理论"等百科其他义项的内容，可以整段删除

**其他任何内容都不许删**，特别包括：
- ❌ 不许删招式列表，哪怕很长
- ❌ 不许删武器列表
- ❌ 不许删配音员列表
- ❌ 不许删登场作品列表（哪怕看起来像折叠/展开的两份不一样的列表，也都保留）
- ❌ 不许删配乐列表
- ❌ 不许删奖项 / 票选记录
- ❌ 不许删剧情段落
- ❌ 不许删 `===` 分隔条
- ❌ 不许删 `## 补充来源：XX` 这种来源标记
- ❌ 不许把空 H2 section 删掉

# ⚠️ 绝对禁止添加任何信息

你只能 **重排** 已有内容，禁止：
- ❌ 凭空添加任何事实（角色名、剧集名、招式名、日期、数字、关系、地名）
- ❌ 改写句子改变其含义
- ❌ 把原文没有的信息总结进新句子
- ❌ 添加任何来自你训练数据的信息（即使你"认识"这个角色，也不能添加任何原文没有的字）
- ❌ 添加"据说"、"可能"、"也许"、"或许"、"详见"、"参考" 等
- ❌ 不要写"该角色是一位..."这种总结句（除非原文 lead 段就是这种话）
- ❌ 不要在开头/结尾加"综上所述"、"以上是整理后的版本" 等

# ⚠️ 名词、数字、标点必须原封不动

- 角色名、剧集名、招式名、武器名、地名 → 与原文**逐字相同**
- 日期、年份、集数、票数、百分比 → 与原文**逐字相同**
- 标点也必须保留：原文是逗号"，"就保留，不要改成句号"。"
- 诗号必须**原貌保留**（原文怎么写就怎么写，不可断、不可合、不可改字）
- 简体/繁体 → 保持与原文一致

# ✅ 你被允许的"重排"动作

1. **K-V 行 → 表格**：把 `**中文名**：xxx` 这种零散行整理成 markdown 表格
2. **跨章节移动**：把 lead 段里夹杂的元数据移到 ## 基本信息 段
3. **散乱字段整合**：原文里"性别"和值在不同段，可以把它们组合到一起
4. **段落合并/拆分**：把原文连续多个短段合并成一段；或把过长一段按句拆成几段（**字句必须原样**）
5. **list 化**：把原文用顿号连接的列表（"招式 A、招式 B、招式 C"）改成 bullet
6. **删除完全重复的句子**（按上面规则）

# 期望的文档结构

```
# 角色名
（保持原 H1 行不变，包括 ===分隔条）

[原文 lead 段的内容，可拆分成清晰的几段，但字句不变]

## 基本信息

| 字段 | 值 |
|---|---|
| 中文名 | (取自原文 **中文名**：的值) |
| 别名 | (取自原文) |
| 配音 | (取自原文) |
| 性别 | (取自原文) |
| 初登场 | (取自原文) |
| ... |

## 角色背景 / 角色形象 / 角色经历 / 角色能力 / 人物关系 等

[原文已有的章节内容，按原文顺序，按句拆段整理]

## 武器 / 武学 / 招式

[原 list 内容，bullet 化]

## 角色配乐

[原 list]

## 奖项荣誉

[原 list]

## 补充来源：XX

[来自其他源的补充段，原文有就保留，不许删]
```

# 输出格式

直接输出整理好的完整 markdown：

❌ 不要用 ```markdown ``` 包裹
❌ 不要写任何前言/后语
❌ 不要解释你做了什么

# 验证

我会用程序滑动窗口检查你的输出（去标点后的中文/字母/数字）。每 16 字一个窗口，必须 ≥85% 都能在原文中找到。任何不在原文里的连续字符都会让整篇输出被丢弃，原文不动。

记住：你只是格式整理，不是内容编辑。删除只针对完全重复和明显非布袋戏内容。
"""


# --------------------------------------------------------------------- 验证
def normalize_for_check(text: str) -> str:
    """归一化：去掉所有 markdown 结构、标点、空白，留下纯内容字符。"""
    # 1. 删除整行的 markdown 结构（headers、表格分隔行、表格通用头行）
    text = re.sub(r"(?m)^#{1,6}\s+.*$", "", text)  # 标题行
    text = re.sub(r"(?m)^\|[\s\-:|]+$", "", text)  # 表格分隔行 |---|---|
    text = re.sub(  # 通用表格头行
        r"(?m)^\|\s*(?:字段|属性|项目|名称|key|项|条目)\s*\|\s*(?:值|内容|描述|value|资料)\s*\|.*$",
        "",
        text,
    )

    # 2. 行内 markdown 标记
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(?m)^[\-\*\+]\s+", "", text)
    text = re.sub(r"\|", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

    # 3. 标点（中英文）和空白全部去掉，只留中文/字母/数字
    text = re.sub(r"[^一-鿿㐀-䶿a-zA-Z0-9]", "", text)
    return text


def validate_output(input_text: str, output_text: str) -> tuple[bool, str]:
    """检查 output 是否合规。返回 (pass, reason)。"""
    if not output_text or len(output_text) < 100:
        return False, "输出太短"

    inp = normalize_for_check(input_text)
    out = normalize_for_check(output_text)

    if len(out) < 80:
        return False, f"归一化后输出仅 {len(out)} 字"
    if len(out) > len(inp) * 1.2:
        return False, f"输出 {len(out)} 字 > 输入 {len(inp)} 字 × 1.2，疑似添加内容"

    # 滑动窗口检查
    matched = 0
    total = 0
    failed_chunks = []
    for i in range(0, len(out) - WINDOW_SIZE + 1, WINDOW_STEP):
        chunk = out[i : i + WINDOW_SIZE]
        total += 1
        if chunk in inp:
            matched += 1
        else:
            if len(failed_chunks) < 3:
                failed_chunks.append(chunk)

    if total == 0:
        return False, "没有可检查的窗口"

    rate = matched / total
    if rate < VALIDATION_MIN_MATCH:
        return False, f"匹配率 {rate:.1%}（阈值 {VALIDATION_MIN_MATCH:.0%}），疑似含原文外内容。失败片段示例：{failed_chunks}"

    return True, f"匹配率 {rate:.1%}"


# --------------------------------------------------------------------- API
def pick_model(content_bytes: int, override: str | None = None) -> str:
    """根据文件大小选模型；override 强制指定。"""
    if override:
        return override
    if content_bytes > SIZE_THRESHOLD_BYTES:
        return MODEL_LARGE
    return MODEL_SMALL


def call_ai(
    client: OpenAI,
    content: str,
    model: str,
    retries: int = 2,
    stall_seconds: int = 90,
) -> tuple[str, object, str]:
    """调用 AI 整理一篇文档（流式 + 卡住自动重试 + 失败时切模型）。

    返回 (output_text, usage, model_used)。
    """
    temp = 1.0 if model.startswith("kimi") else 0.0
    fallback_chain = [model]
    # 失败时切到对方
    if model == "mimo-v2.5-pro":
        fallback_chain.append("mimo-v2.5")
    elif model == "mimo-v2.5":
        fallback_chain.append("mimo-v2.5-pro")

    last_error = None
    for try_model in fallback_chain:
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                stream = client.chat.completions.create(
                    model=try_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"请整理以下布袋戏角色 markdown：\n\n---\n\n{content}",
                        },
                    ],
                    temperature=1.0 if try_model.startswith("kimi") else 0.0,
                    max_tokens=32000,
                    stream=True,
                    stream_options={"include_usage": True},
                )

                chunks = []
                usage = None
                for chunk in stream:
                    # 每收到一个 chunk 就重置 stall 计时
                    if chunk.choices and chunk.choices[0].delta:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            chunks.append(delta)
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage = chunk.usage

                out = "".join(chunks).strip()
                out = re.sub(r"^```(?:markdown|md)?\s*\n", "", out)
                out = re.sub(r"\n```\s*$", "", out)
                if out:
                    return out.strip(), usage, try_model
                # 空输出当失败
                last_error = RuntimeError("空输出")

            except (
                httpx.ReadTimeout,
                httpx.ConnectTimeout,
                httpx.ConnectError,
                httpx.RemoteProtocolError,
            ) as e:
                last_error = e
                elapsed = time.time() - t0
                print(
                    f"  [!] 网络/卡住 {elapsed:.0f}s "
                    f"({try_model} attempt {attempt + 1}/{retries + 1}): "
                    f"{type(e).__name__}",
                    flush=True,
                )
            except Exception as e:
                last_error = e
                print(
                    f"  [!] {try_model} attempt {attempt + 1}/{retries + 1}: "
                    f"{type(e).__name__}: {e}",
                    flush=True,
                )

            time.sleep(2 + attempt * 3)  # 指数退避

        # 该模型重试用完，切下一个
        if try_model != fallback_chain[-1]:
            print(f"  [→] 切换到备选模型", flush=True)

    # 全部失败
    raise last_error or RuntimeError("API 全部失败")


# --------------------------------------------------------------------- 状态
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"processed": {}, "failed": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# --------------------------------------------------------------------- 主流程
def process_file(client: OpenAI, fp: Path, apply: bool, state: dict, model_override: str | None = None) -> dict:
    """返回 {ok, reason, in_chars, out_chars, prompt_tokens, completion_tokens, model}."""
    original = fp.read_text(encoding="utf-8")
    rel = str(fp).replace("\\", "/")

    if len(original) < 200:
        return {"ok": False, "reason": "文件太短，跳过"}

    if len(original) > 800_000:
        return {"ok": False, "reason": f"文件 {len(original)} 字过大，跳过"}

    model = pick_model(len(original.encode("utf-8")), model_override)

    try:
        cleaned, usage, actual_model = call_ai(client, original, model)
        model = actual_model  # 记录实际使用的模型（可能切换过）
    except Exception as e:
        return {"ok": False, "reason": f"API 错误：{type(e).__name__}: {e}", "model": model}

    ok, reason = validate_output(original, cleaned)
    result = {
        "ok": ok,
        "reason": reason,
        "in_chars": len(original),
        "out_chars": len(cleaned),
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
        "model": model,
    }

    if ok and apply:
        # 备份原文
        backup_dir = fp.parent / ".pre_ai_backup"
        backup_dir.mkdir(exist_ok=True)
        (backup_dir / fp.name).write_text(original, encoding="utf-8")
        # 写回
        fp.write_text(cleaned, encoding="utf-8")
        state["processed"][rel] = {
            "ts": int(time.time()),
            "in": result["in_chars"],
            "out": result["out_chars"],
        }
    elif not ok:
        state["failed"][rel] = {
            "ts": int(time.time()),
            "reason": reason,
        }

    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="文件或目录")
    ap.add_argument("--apply", action="store_true", help="原地写入（默认 dry-run）")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 个未处理文件")
    ap.add_argument("--resume", action="store_true", help="跳过已处理过的（默认）")
    ap.add_argument("--redo", action="store_true", help="忽略状态全部重跑")
    ap.add_argument(
        "--model",
        default=None,
        help=f"强制指定模型（默认按文件大小自动选 {MODEL_SMALL} / {MODEL_LARGE}）",
    )
    ap.add_argument("--min-size", type=int, default=0, help="只处理 >=N 字节的文件")
    ap.add_argument("--max-size", type=int, default=0, help="只处理 <=N 字节的文件（0=不限）")
    ap.add_argument("--sort-size-desc", action="store_true", help="按大小降序处理（大文件先）")
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if not target.exists():
        print(f"[!] 不存在：{target}")
        sys.exit(1)

    files = [target] if target.is_file() else list(target.rglob("*.md"))
    # 跳过 index.md / .pages / 备份目录里的文件
    files = [
        f for f in files
        if f.name not in ("index.md", ".pages")
        and ".pre_ai_backup" not in f.parts
        and ".pre_merge_backup" not in f.parts
    ]

    # 大小过滤
    if args.min_size > 0:
        files = [f for f in files if f.stat().st_size >= args.min_size]
    if args.max_size > 0:
        files = [f for f in files if f.stat().st_size <= args.max_size]

    # 排序：默认字母序；--sort-size-desc 按大小降序
    if args.sort_size_desc:
        files = sorted(files, key=lambda f: -f.stat().st_size)
    else:
        files = sorted(files)

    state = load_state()
    if args.redo:
        state = {"processed": {}, "failed": {}}

    # 过滤已处理
    todo = []
    for f in files:
        rel = str(f).replace("\\", "/")
        if rel in state["processed"] and not args.redo:
            continue
        todo.append(f)

    if args.limit:
        todo = todo[: args.limit]

    if not todo:
        print("[!] 没有待处理的文件")
        return

    log(f"开始：共 {len(todo)} 文件待处理（已跳过 {len(files) - len(todo)} 已处理）")

    # httpx timeout：连接 15s、单次读 90s（90s 没收到任何 chunk 就当卡住）
    client = OpenAI(
        api_key=API_KEY,
        base_url=API_BASE,
        timeout=httpx.Timeout(connect=15, read=90, write=15, pool=15),
        max_retries=0,  # 我们自己控制重试
    )

    total_in = 0
    total_out = 0
    success = 0
    failed = 0
    for i, fp in enumerate(todo, 1):
        rel = str(fp).replace("\\", "/")
        result = process_file(client, fp, args.apply, state, model_override=args.model)

        total_in += result.get("prompt_tokens", 0)
        total_out += result.get("completion_tokens", 0)

        status = "✓" if result["ok"] else "✗"
        action = "APPLIED" if (args.apply and result["ok"]) else ("DRY" if result["ok"] else "FAIL")
        model_short = result.get("model", "?").replace("mimo-v2.5-pro", "mimo").replace("kimi-k2.6", "kimi")
        log(
            f"[{i}/{len(todo)}] {status} {action} [{model_short}] {fp.name} "
            f"in={result.get('in_chars', 0)} out={result.get('out_chars', 0)} "
            f"tok={result.get('prompt_tokens', 0)}/{result.get('completion_tokens', 0)} "
            f"| {result['reason']}"
        )
        if result["ok"]:
            success += 1
        else:
            failed += 1

        # 每 10 个文件保存状态
        if i % 10 == 0:
            save_state(state)

    save_state(state)

    log(
        f"\n完成：成功 {success}，失败 {failed}，"
        f"总 token 输入 {total_in:,}，输出 {total_out:,}"
    )


if __name__ == "__main__":
    main()
