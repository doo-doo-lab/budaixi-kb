#!/usr/bin/env python3
"""清洗布袋戏百科 markdown：去除百度百科 UI 噪音，保留多源补充段落。

用法:
    python clean.py <文件或目录>            # 干跑，输出预览到 _tools/samples_out/
    python clean.py <文件或目录> --apply    # 原地写入
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_OUT = Path(__file__).resolve().parent / "samples_out"

SEP_RE = re.compile(r"={20,}")


def clean_baidu_metadata(text: str) -> str:
    """全局清理 baidu 抓取元数据（保留非 baidu 的补充源）。"""
    # H1 去掉 `_百度百科` 后缀（任何位置）
    text = re.sub(r"(?m)^(# .*?)_百度百科\s*$", r"\1", text)
    # 删除指向 baike.baidu.com 的 - **来源**: 行（保留其他域名的补充源）
    text = re.sub(
        r"(?m)^- \*\*来源\*\*:\s*https?://baike\.baidu\.com/\S*\s*\r?\n?",
        "",
        text,
    )
    # - **系列**: 和 - **抓取时间**: 是 baidu 抓取专属
    text = re.sub(
        r"(?m)^- \*\*(?:系列|抓取时间)\*\*:.*\r?\n?",
        "",
        text,
    )
    # (百度百科无对应条目) 注释
    text = re.sub(r"(?m)^\(百度百科无对应条目\)\s*\r?\n?", "", text)
    return text


def clean_body(text: str) -> str:
    """清洗正文（含多源补充段，但只去 UI 噪音，保留补充段元数据）。"""
    # 顶部百度导航条：网页新闻贴吧知道...展开N个同名词条
    text = re.sub(r"网页新闻贴吧知道.*?展开\d+个同名词条", "", text)
    # 兜底：剥到"播报讨论上传视频"
    text = re.sub(r"网页新闻贴吧知道.*?播报讨论上传视频", "", text)
    # 再兜底：剥到"个人中心"
    text = re.sub(r"网页新闻贴吧知道.*?个人中心", "", text)

    # "目录1XX2YY..." 索引行
    text = re.sub(r"目录\d+[^\n]*", "", text)

    # 把 "[小节名]播报编辑" 提升为 ## 标题
    text = re.sub(
        r"([一-龥]{2,8})播报编辑",
        r"\n\n## \1\n\n",
        text,
    )
    # 残余的"播报编辑"直接删除（前面无中文字符的边缘情况）
    text = re.sub(r"播报编辑", "", text)

    # 图集占位 "(N张)" / "（N张）"
    text = re.sub(r"[（(]\d+张[）)]", "", text)

    # 脚注号 [1] [3-4] [5]
    text = re.sub(r"\s?\[\d+(?:[-–]\d+)?\]", "", text)

    # 配对的 "展开X收起" → 保留 X，去掉标记（处理百度元数据表的折叠 UI）
    # 限定 2000 字以内，避免跨大段匹配
    text = re.sub(r"展开(.{0,2000}?)收起", r"\1", text, flags=re.DOTALL)
    # 兜底：单独的"展开<N个同名词条>"等已覆盖；剩余的"展开"在已知 UI 词前删除
    text = re.sub(
        r"展开(?=登场作品|登场记录|人物|更多|相关|图集|作品|关系|目录)",
        "",
        text,
    )

    # 页脚版权条
    text = re.sub(
        r"新手上路成长任务编辑.*?京公网安备\d+号",
        "",
        text,
    )

    # 其他百科 UI 残留：本詞條是多義詞，共N個義項...更多義項 ▼ / 收起列表 ▲
    text = re.sub(r"本詞條是多義詞[，,].*?[▼▲]", "", text)
    text = re.sub(r"收起列表\s*[▲▼]", "", text)
    text = re.sub(r"更多義?[項项]\s*[▼▲]", "", text)

    return text


# 已知小节标题（一行单独出现的结构性标题，将提升为 H2）
PILI_SECTIONS = [
    "角色背景", "角色形象", "人物關係", "人物关系",
    "招式", "招式技能", "武功", "武器", "兵器",
    "角色經歷", "角色经历",
    "口白選錄", "口白选录", "經典台詞", "经典台词",
    "登場記錄", "登场记录",
    "個性與外觀", "个性与外观",
    "詩號", "诗号",
    "備註", "备注",
    "角色配樂", "角色配乐",
    "角色榮譽", "角色荣誉",
    "角色評價", "角色评价",
    "技能專長", "技能专长",
    "所持有物", "持有物",
]

# 已知键名字段（一行单独出现的元数据键名，加粗使其与值区分）
PILI_KEYS = [
    "性別", "性别",
    "初登場", "初登场",
    "退場", "退场", "暫退場", "暂退场", "再登場", "再登场",
    "稱號", "称号", "別稱", "别称", "別名", "别名",
    "來自", "来自",
    "根據地", "根据地",
    "代表顏色", "代表颜色",
    "上司", "下屬", "下属",
    "同伴", "友人", "朋友",
    "敵人", "敌人", "宿敵", "宿敌",
    "親屬", "亲属",
    "妻子", "丈夫", "兒子", "儿子", "女兒", "女儿",
    "父親", "父亲", "母親", "母亲", "兄弟", "姐妹",
    "配音", "配音員", "配音员",
    "兴趣爱好", "興趣愛好",
    "所持有物", "持有物",
    "口頭禪", "口头禅",
    "事跡", "事迹",
]


def transform_structure(text: str) -> str:
    """结构化转换：修复 hex 色码 H1 误识、提升小节标题、加粗键名。"""
    # 1) 修复 #XXXXXX 行首被识别为 H1：转成色块 + 行内代码
    text = re.sub(
        r"(?m)^(#[0-9a-fA-F]{6})\s*$",
        lambda m: (
            f'<span class="bdx-swatch" style="background:{m.group(1)}"></span> '
            f'`{m.group(1)}`'
        ),
        text,
    )

    # 2) 已知小节标题（独占一行）→ H2，前后加空行确保 markdown 识别
    section_pattern = "|".join(re.escape(s) for s in PILI_SECTIONS)
    text = re.sub(
        rf"(?m)^({section_pattern})\s*$",
        r"\n## \1\n",
        text,
    )

    # 3) 已知键名（独占一行）→ **加粗**，与值在同一段落用一个空行隔开
    key_pattern = "|".join(re.escape(k) for k in PILI_KEYS)
    text = re.sub(
        rf"(?m)^({key_pattern})\s*$",
        r"\n**\1**\n",
        text,
    )

    return text


def clean(text: str) -> str:
    # 全局清理 baidu 元数据（包括合并文档里的）
    text = clean_baidu_metadata(text)
    # 全文走一遍 body 清洗
    text = clean_body(text)
    # 结构化转换
    text = transform_structure(text)

    # 整理空白
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip() + "\n"
    return text


def process(target: Path, apply: bool) -> None:
    files = [target] if target.is_file() else sorted(target.rglob("*.md"))
    if not files:
        print(f"[!] 未找到 .md 文件: {target}")
        return

    SAMPLES_OUT.mkdir(parents=True, exist_ok=True)

    total = 0
    saved_bytes = 0
    for f in files:
        original = f.read_text(encoding="utf-8")
        cleaned = clean(original)
        delta = len(original) - len(cleaned)
        saved_bytes += delta
        total += 1

        if apply:
            f.write_text(cleaned, encoding="utf-8")
        else:
            try:
                rel = f.relative_to(ROOT)
            except ValueError:
                rel = f.name
            out = SAMPLES_OUT / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(cleaned, encoding="utf-8")
            print(f"  {f.relative_to(ROOT)}  {len(original):>6} → {len(cleaned):>6}  (-{delta})")

    mode = "APPLY" if apply else "DRY"
    print(f"\n[{mode}] 共 {total} 文件，节省 {saved_bytes:,} 字节")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    target = Path(args[0]).resolve()
    apply = "--apply" in args
    process(target, apply)


if __name__ == "__main__":
    main()
