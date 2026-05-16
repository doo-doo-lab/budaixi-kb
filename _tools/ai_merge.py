#!/usr/bin/env python3
"""把 _tools/raw_baidu/X.md 的内容合并进 docs/角色/{pili|jinguang|dongli}/X.md。

用 mimo 严格 prompt 合并：
- 只能保留两份原文中已有的字
- 新版独有的字段加入 ## 基本信息 表
- 新版独有的段落加为 ## 来自百度百科 子段
- 主版结构（H1 + 表 + 段）保持

用法:
    python ai_merge.py                      # dry-run，预览所有
    python ai_merge.py --apply              # 应用全部
    python ai_merge.py --limit 5            # 只跑前 5 个
    python ai_merge.py --apply --limit 5    # 应用前 5 个
"""
from __future__ import annotations
import argparse
import json
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
RAW_DIR = Path(__file__).resolve().parent / "raw_baidu"
DOCS_DIR = ROOT / "docs" / "角色"
STATE_FILE = Path(__file__).resolve().parent / ".merge_state.json"
LOG_FILE = Path(__file__).resolve().parent / "ai_merge.log"

API_KEY = "29647c86-28a2-46bc-8682-9cb0cecb8d45"
API_BASE = "https://kspmas.ksyun.com/v1"
MODEL = "mimo-v2.5"  # 用快版（合并任务量大但简单）

VALIDATION_MIN_MATCH = 0.85
WINDOW_SIZE = 16
WINDOW_STEP = 8

SYSTEM_PROMPT = """你是中文百科条目合并助手。我会给你两份关于同一个布袋戏角色的 markdown 文档：

【主版】当前 docs 里的内容（已整理过，是基础结构）
【副版】新从百度百科抓的内容（带补充信息）

任务：把副版的【独有信息】**追加**到主版的尾部，保持主版几乎不动。

# ⚠️⚠️⚠️ 关键：YAML frontmatter 必须完整保留

如果主版以 `---` 开头有 YAML frontmatter 块（开头 `---`，结尾 `---`，中间是 `key: value` 或缩进字段），**必须把整个 frontmatter 块（含开头和结尾的 `---`）原样放在你输出的最前面，所有字段一字不改、不增不减、缩进格式完全保留**。

不能：
- 删除 frontmatter
- 把字段移到 markdown 表格里
- 改字段名（如把 "姓名" 改成 "名称"）
- 删除任何字段值（包括 list 列表项）
- 调整缩进格式

frontmatter 之后才是 `# 角色名` H1 标题。

# ⚠️⚠️⚠️ 关键：避免跨源拼接

我会用 16 字滑动窗口检查输出。任何 16 个连续字符如果横跨"主版的句子末尾 + 副版的句子开头"，因为这种字串两份原文里都不存在，会让验证失败。

**为避免这种情况：**
- Lead 段（H1 下面那段）：**完整逐字使用主版的**，副版的 lead 段一律不要拼到主版 lead 后面
- 主版的章节段：**完整逐字保留**主版段落的内容，副版独有段落作为 **新的 ## 子节** 加在文档末尾，前面留空行
- 字段表：主版字段表整体保留；副版独有字段在表的末尾追加新行，不要交错插入
- 段落之间必须有空行分隔；H2/H3 标题前也要有空行

简言之：主版的内容**整体不动、原位保留**；副版的独有内容**append 到末尾**，用空行 + 标题清晰隔开。

# ⚠️ 绝对禁止

1. 不得添加任何**两份文档都没有的字**（来自你训练数据的额外信息也不行）
2. 不得改写句子改变含义
3. 不得编造任何"据说"、"可能"、"也许"
4. 不得删主版的实质内容
5. 名词、数字、专有名词必须**逐字保留**两份原文里的写法
6. 不得把副版的句子穿插到主版段落之间（必然产生跨源边界，导致验证失败）
7. 不得删除或修改主版开头的 YAML frontmatter（如有）。必须完整保留 `---` ... `---` 块作为输出的最前面

# 期望产物结构

```
---
（如果主版有 frontmatter 就完整逐字保留这一块——所有字段、缩进、---  分隔符都原样）
---

# 角色名（主版的 H1 标题，完整保留）

（主版的 lead 段，完整逐字保留——不要拼接副版的 lead）

（主版的所有 H2 章节，完整逐字保留——不要在段尾插入副版的句子）

## 来自百度百科的补充

（副版里主版完全没有的段落，原文照抄；如果副版的 lead 段比主版详细，把副版的 lead 整段也放这里，前面加空行）

| 字段 | 值 |
|---|---|
| 中文名 | xxx |  ← 副版独有的字段，主版没有的才列在这里
| ... |
```

# 允许的"重排"动作（小心使用）

- 删除完全重复的句子（两份原文都有同一句话，主版那份保留，副版那份在追加段中删掉）
- 副版字段表里**主版完全没有的字段**：单独建一个表追加在 ## 来自百度百科的补充 下
- 副版完全是主版的子集：直接保留主版原样输出（不需要追加任何内容）

# 输出格式

直接输出合并后的 markdown，不要任何前言/后语，不要 ```markdown ``` 包裹。

# 验证

我会用程序逐 16 字窗口检查你的输出，必须 ≥85% 字串来自两份原文之一（不允许跨源拼接产生新字串）。**不在原文里的连续字符**会让整个合并被拒绝、原文不动。
"""


def normalize_for_check(text: str) -> str:
    text = re.sub(r"(?m)^#{1,6}\s+.*$", "", text)
    text = re.sub(r"(?m)^\|[\s\-:|]+$", "", text)
    text = re.sub(
        r"(?m)^\|\s*(?:字段|属性|项目|名称|key|项|条目)\s*\|\s*(?:值|内容|描述|value|资料)\s*\|.*$",
        "",
        text,
    )
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


def validate(combined_input: str, output: str, primary: str = "") -> tuple[bool, str]:
    if not output or len(output) < 200:
        return False, "输出太短"
    # frontmatter 保留检查
    if primary.startswith("---\n"):
        # 主版有 frontmatter
        p_end = primary.find("\n---\n", 4)
        if p_end > 0:
            primary_fm = primary[:p_end + 5]  # 含两个 ---
            if not output.startswith("---"):
                return False, "frontmatter 丢失：输出未以 --- 开头"
            o_end = output.find("\n---\n", 4)
            if o_end < 0:
                return False, "frontmatter 不完整：找不到结尾 ---"
            output_fm = output[:o_end + 5]
            # 主 keys 必须都在
            p_keys = set(re.findall(r"(?m)^([\w]+):", primary_fm))
            o_keys = set(re.findall(r"(?m)^([\w]+):", output_fm))
            missing = p_keys - o_keys
            if missing:
                return False, f"frontmatter 丢字段: {missing}"
    inp = normalize_for_check(combined_input)
    out = normalize_for_check(output)
    if len(out) < 100:
        return False, f"归一化后输出仅 {len(out)} 字"
    if len(out) > len(inp) * 1.15:
        return False, f"输出 {len(out)} 字 > 输入 {len(inp)} 字 × 1.15，疑似添加内容"
    matched = total = 0
    failed_chunks = []
    for i in range(0, len(out) - WINDOW_SIZE + 1, WINDOW_STEP):
        chunk = out[i : i + WINDOW_SIZE]
        total += 1
        if chunk in inp:
            matched += 1
        elif len(failed_chunks) < 3:
            failed_chunks.append(chunk)
    if total == 0:
        return False, "无可检查窗口"
    rate = matched / total
    if rate < VALIDATION_MIN_MATCH:
        return False, f"匹配率 {rate:.1%}，失败片段：{failed_chunks}"
    return True, f"匹配率 {rate:.1%}"


def strip_baidu_metadata(baidu: str) -> str:
    """从副版抽掉只是元数据的行（`- **来源**: URL`、`# {name}`、`### 基本信息表（来自百度页 dl）` 块），
    LLM 别把它们和正文段落穿插造成 validation 跨源拼接失败。

    `### 基本信息表` 内的字段大多 primary frontmatter 也有，主版不会丢；正文段落里也经常重复。
    """
    lines = baidu.splitlines()
    out_lines: list[str] = []
    skip_basicinfo = False
    for line in lines:
        # 进入 `### 基本信息表` 段，开始跳
        if line.startswith("### 基本信息表"):
            skip_basicinfo = True
            continue
        if skip_basicinfo:
            # 跳到下一个 `## ` 或 `### ` 或 `# ` 结束
            if line.startswith(("## ", "### ", "# ")):
                skip_basicinfo = False
                # 此 line 是新章节，要保留 — fall through 处理
            else:
                continue
        # 去掉 `- **来源**:` 行
        if re.match(r"^\s*-\s*\*\*来源\*\*:", line):
            continue
        # 去掉 baidu 文件开头的 `# {name}` H1（主版的 H1 才该保留）
        if re.match(r"^\s*#\s+\S", line):
            continue
        out_lines.append(line)
    result = "\n".join(out_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def call_merge(client: OpenAI, primary: str, baidu: str) -> tuple[str, object]:
    baidu_clean = strip_baidu_metadata(baidu)
    user_msg = (
        "【主版】（当前 docs 里的内容）\n\n```markdown\n"
        + primary
        + "\n```\n\n【副版】（新从百度百科抓的，只含正文章节）\n\n```markdown\n"
        + baidu_clean
        + "\n```\n\n请按系统指令合并。"
    )
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
                max_tokens=32000,
                stream=True,
                stream_options={"include_usage": True},
            )
            chunks = []
            usage = None
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = chunk.usage
            out = "".join(chunks).strip()
            out = re.sub(r"^```(?:markdown|md)?\s*\n", "", out)
            out = re.sub(r"\n```\s*$", "", out)
            if out:
                return out.strip(), usage
            last_err = RuntimeError("空输出")
        except Exception as e:
            last_err = e
            print(f"  [!] attempt {attempt+1}/3: {type(e).__name__}: {e}", flush=True)
        time.sleep(2 + attempt * 3)
    raise last_err or RuntimeError("merge 全部失败")


def find_doc_for(name: str) -> Path | None:
    """在 pili/jinguang/dongli 三个子目录中找名为 {name}.md 的文件。"""
    for sub in ("pili", "jinguang", "dongli"):
        p = DOCS_DIR / sub / f"{name}.md"
        if p.exists():
            return p
    return None


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"merged": {}, "failed": {}}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="原地写入")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    raw_files = sorted(RAW_DIR.glob("*.md"))
    state = load_state()

    todo = []
    for rf in raw_files:
        name = rf.stem
        if name in state["merged"]:
            continue
        doc = find_doc_for(name)
        if not doc:
            log(f"[skip] {name}：在 docs/角色 中找不到对应文件")
            continue
        todo.append((rf, doc, name))

    if args.limit:
        todo = todo[: args.limit]

    if not todo:
        log("没有待合并文件")
        return

    log(f"开始：{len(todo)} 个文件待合并")
    client = OpenAI(
        api_key=API_KEY,
        base_url=API_BASE,
        timeout=httpx.Timeout(connect=15, read=120, write=15, pool=15),
        max_retries=0,
    )

    success = failed = 0
    for i, (rf, doc, name) in enumerate(todo, 1):
        primary = doc.read_text(encoding="utf-8")
        baidu = rf.read_text(encoding="utf-8")
        combined = primary + "\n\n=== BAIDU ===\n\n" + baidu

        try:
            merged, usage = call_merge(client, primary, baidu)
        except Exception as e:
            failed += 1
            log(f"[{i}/{len(todo)}] ✗ {name}  API 错误：{e}")
            state["failed"][name] = {"ts": int(time.time()), "reason": str(e)}
            continue

        ok, reason = validate(combined, merged, primary)
        if not ok:
            failed += 1
            log(f"[{i}/{len(todo)}] ✗ {name}  {reason}")
            state["failed"][name] = {"ts": int(time.time()), "reason": reason}
            continue

        if args.apply:
            backup = doc.parent / ".pre_merge_backup"
            backup.mkdir(exist_ok=True)
            (backup / doc.name).write_text(primary, encoding="utf-8")
            doc.write_text(merged, encoding="utf-8")
            state["merged"][name] = {
                "ts": int(time.time()),
                "primary_chars": len(primary),
                "merged_chars": len(merged),
            }
            log(
                f"[{i}/{len(todo)}] ✓ APPLIED {name}  {len(primary)}→{len(merged)} 字  {reason}"
            )
        else:
            log(
                f"[{i}/{len(todo)}] ✓ DRY {name}  {len(primary)}→{len(merged)} 字  {reason}"
            )
        success += 1

        if i % 5 == 0:
            save_state(state)

    save_state(state)
    log(f"\n完成：成功 {success}，失败 {failed}")


if __name__ == "__main__":
    main()
