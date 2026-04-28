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

# 百度百科的小节标题（用于把 "[小节]播报编辑" 转为 ## 小节）
BAIDU_SECTIONS = [
    "角色背景", "角色形象", "角色能力", "角色经历", "角色關係", "角色关系",
    "角色评价", "角色評價", "角色配乐", "角色配樂", "角色荣誉", "角色榮譽",
    "登场记录", "登場記錄", "相关作品", "相關作品",
    "對戰記錄", "对战记录",
    "主要人际关系", "其他人际关系", "人际关系", "人際關係",
    "根据地", "根據地", "武学", "武學", "武功", "兵器", "武器", "招式",
    "诗号", "詩號",
    "事跡", "事迹", "主要事跡", "主要事迹",
    "官方评价", "官方評價", "他人评价", "他人評價",
    "人物配乐", "人物配樂",
    "人物势力", "人物勢力", "势力", "勢力",
    "新登场人物", "新登場人物", "死亡退隐人物", "死亡退隱人物",
]
# 注：故意不加 "经历" "勢力" "人物" 等短词；它们是更长小节的子串（角色经历/人物势力等）
# 加入会被错误捕获短后缀，把 "## 角色经历" 拆成 "角色" + "## 经历"

# 百度 infobox 字段名（线性化的元数据中识别字段，转结构化键值对）
BAIDU_INFOBOX_FIELDS = [
    # 名称
    "中文名", "外文名", "中文名称", "英文名", "本名", "原名",
    "别名", "別名", "别称", "別稱", "化名",
    # 个人
    "性别", "年龄", "身高", "体重",
    "生日", "出生日期", "出生地", "星座", "生肖",
    "种族", "族群", "国籍",
    # 配音 / 制作
    "配音", "配音员", "声优",
    "原型",
    "本尊雕偶师", "接手雕偶师", "雕偶师",
    "编剧", "导演", "出品",
    # 身份 / 阵营
    "身份", "官位", "爵位", "职业", "阵营",
    "师承", "门派", "称号", "人称",
    "根据地", "所属", "组织", "出身", "代表势力",
    # 武艺 / 道具
    "武器", "兵器", "佩剑",
    "武学", "武功", "功体", "体质", "招式",
    "宝物", "著作", "所持有物", "持有物",
    "绝学",
    # 演出
    "登场作品", "代表作品", "主要作品", "电影作品", "动画作品",
    "初登场", "首次登场", "退场", "暂退场", "再登场", "再退场",
    "出场", "再出场", "出场集数",
    # 文学 / 标签
    "诗号", "口头禅",
    "人物特征", "武林地位", "剧中地位",
    # 家庭
    "父亲", "母亲", "兄弟", "姐妹",
    "妻子", "丈夫", "儿子", "女儿",
    "师父", "师傅", "弟子", "徒弟",
    # 制作 (金光系列特有)
    "人物原创编剧", "人物接手编剧", "本尊偶雕偶师", "接手雕偶偶师",
    "角色编剧", "角色配音",
]


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

    # 顶部百度泡泡 "订阅N有用+M" 兜底
    text = re.sub(r"订阅\d+有用\+\d+", "", text)

    # 把 "[已知小节名]播报编辑" 提升为 ## 标题（用固定列表避免误捕长上下文）
    for s in BAIDU_SECTIONS:
        text = re.sub(
            rf"(?<![一-龥])({re.escape(s)})播报编辑",
            r"\n\n## \1\n\n",
            text,
        )
    # 残余的"播报编辑"直接删除
    text = re.sub(r"播报编辑", "", text)

    # 修复上一版误拆的 "角色\n\n## 经历" → "## 角色经历" 类回退
    text = re.sub(
        r"(?m)^角色\s*\n\s*\n## 经历\s*$",
        "## 角色经历",
        text,
    )
    text = re.sub(
        r"(?m)^角色\s*\n\s*\n## 經歷\s*$",
        "## 角色經歷",
        text,
    )

    # 修复早期版本误捕的 H2（如 "## 麟星解锋镝根据地" → "麟星解锋镝\n\n## 根据地"）
    # 用 set 检查整行是否本身就是已知小节，是就不动；否则尝试从最长后缀切分
    sections_set = set(BAIDU_SECTIONS)
    sections_sorted = sorted(BAIDU_SECTIONS, key=len, reverse=True)

    def _fix_h2(line: str) -> str:
        if not line.startswith("## "):
            return line
        title = line[3:].strip()
        if title in sections_set:
            return line  # 本身就是已知小节，保留
        for s in sections_sorted:
            if title.endswith(s) and len(title) > len(s):
                prefix = title[: -len(s)]
                return f"{prefix}\n\n## {s}"
        return line

    text = "\n".join(_fix_h2(line) for line in text.split("\n"))

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


def _field_pattern(name: str) -> str:
    """生成允许字符间空格的字段名匹配模式（如 "性别" → "性\\s*别"）。"""
    return r"\s*".join(re.escape(c) for c in name)


def restructure_baidu_infobox(text: str) -> str:
    """识别百度百科被压扁的 infobox 序列，转成结构化键值对。

    策略：infobox 的可靠起点是首次出现的 "中文名"（百度模板第一字段）。
    从那里开始扫描已知字段，紧凑连续（间距 <60 字）的字段才视为 infobox 部分。
    括号内的字段名跳过（避免 "1988年（初登场）" 这种）。
    """
    fields_sorted = sorted(BAIDU_INFOBOX_FIELDS, key=len, reverse=True)
    pattern = "(" + "|".join(_field_pattern(f) for f in fields_sorted) + ")"
    full_re = re.compile(pattern)

    # 寻找 infobox 的可靠起点：首次出现的 "中文名" 或 "本名"
    anchor = re.search(r"中\s*文\s*名|本\s*名(?=[一-龥A-Za-z])", text)
    if not anchor:
        return text  # 没有强标记，跳过

    start_pos = anchor.start()
    # 只扫描从 anchor 起到下一段落分隔/##/===/补充来源 标记之间的内容
    end_search = re.search(
        r"\n\s*\n|\n##\s|\n=={3,}|【补充来源",
        text[start_pos:],
    )
    block_end = start_pos + end_search.start() if end_search else len(text)

    block = text[start_pos:block_end]
    matches = list(full_re.finditer(block))
    if len(matches) < 3:
        return text

    # 跳过括号内的匹配
    def in_parens(pos: int) -> bool:
        depth = 0
        for i, ch in enumerate(block[:pos]):
            if ch in "（(":
                depth += 1
            elif ch in "）)":
                depth -= 1
        return depth > 0

    matches = [m for m in matches if not in_parens(m.start())]
    if len(matches) < 3:
        return text
    # 同段落内全部视为 infobox（段落边界已由 block_end 隔开）；
    # 不再按相邻间距裁剪，因为有些字段值本身很长（如 "登场作品" 列表）

    # 构造结构化输出
    parts = []
    for i, m in enumerate(matches):
        field_text = m.group(0)
        canonical = re.sub(r"\s+", "", field_text)
        v_start = m.end()
        v_end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        value = block[v_start:v_end].strip(" 、，,；;：:")
        if value:
            parts.append(f"**{canonical}**：{value}")

    if not parts:
        return text

    replacement = "\n\n" + "\n\n".join(parts) + "\n\n"
    # 替换 [start_pos : start_pos + last_match_end_in_block]
    last_match_end_in_block = matches[-1].end()
    # 如果最后字段后还有未消费的内容（>20 字），也保留进 value
    return text[:start_pos] + replacement + text[start_pos + len(block):]


def break_long_paragraphs(text: str) -> str:
    """对超过 300 字的纯文字段落，在句号 / 问号 / 感叹号后插入段落分隔。"""
    paragraphs = re.split(r"(\n\s*\n)", text)
    result = []
    for p in paragraphs:
        # 保留分隔符
        if not p.strip() or len(p) <= 300:
            result.append(p)
            continue
        # 跳过特殊块：标题、表格、代码、HTML、列表、加粗段
        stripped = p.lstrip()
        if stripped.startswith(("#", "```", "- ", "* ", "|", "<", "**", "===")):
            result.append(p)
            continue
        # 在 。！？; 后接中文/英文/数字时插入段落断点
        broken = re.sub(
            r"([。！？；])(?=[一-龥A-Za-z0-9\(（])",
            r"\1\n\n",
            p,
        )
        result.append(broken)
    return "".join(result)


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
    # 重构百度 infobox 字段串（必须在 break_long_paragraphs 之前）
    text = restructure_baidu_infobox(text)
    # pili 风格的结构化转换
    text = transform_structure(text)
    # 长段落按句号分行
    text = break_long_paragraphs(text)

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
