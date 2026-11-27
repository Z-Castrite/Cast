"""流式筛选器：旁路看主意识在想什么，产出一条可检索的索引。

职责变了——它不再决定"存不存"（原文已经在 raw 里全量留着），
它决定的是"怎么索引"：摘要、关键词、重要性。

所以它现在更像图书管理员，不是守门员。
"""

import json
import re

import llm

_SYSTEM = """我是记忆模型的索引员。我的工作是把一段内容整理成日后**可被检索**的索引条目。

**主语必须准确，这是最容易错的地方：**
- 内容如果是用户说的、关于用户的 → 主语写「用户」
- 内容如果是 AI 自己的判断、想法、决定 → 主语写「我」
- 绝对不能把用户的事写成"主意识……"，那会让记忆分不清是谁的

要提取的内容：
1. 做出的决定、结论、取舍
2. 会影响未来行为的事实或条件
3. 对旧判断的修正、推翻
4. 值得记住的情绪/状态变化
5. 约定、待办、承诺

不要提取：
- 思考过程本身、试探、犹豫
- 寒暄、过渡句、对措辞的打磨
- 对用户情绪的无意义安抚
- 纯知识性陈述（那种东西不需要记，查得到）

关键词是这一条最重要的字段。规则：
- 给 3 到 8 个
- **不是这段文字里出现的词，而是日后这个人可能用来说起这件事的词**
- 包括他的口语说法、身体部位、时间、地点、事件
- 例：记忆是"左手15%肌肉空洞源于童年托管机构事件"
  → 关键词：["左手","肌肉空洞","伤","童年","托管机构","铁窗","15%"]
  注意"伤"这个字原文里根本没有，但日后很可能会被这样问。

**时间也是必填项，而且是「事件发生的时间」不是「现在说话的时间」：**
- 从内容里能推断出时间就写：昨天、上个月、去年冬天、童年、五岁那年、八年级、2026年10月
- 推断不出来就写空字符串
- 这一项是日后区分「同样的事不同时候发生」的唯一依据，别偷懒

**path 是这条记忆该放哪，写成分类路径：**
- 一般 1 到 2 层，最多 3 层，每层 2 到 4 个字
- **优先用「已有分类树」里现成的路径**，别自己另造一套
- 确实没有合适的，可以新开一层。新开之前先想想：能不能塞进已有的某个节点下面
- 例：左手肌肉空洞 → ["身体","伤"]；一天三十块 → ["经济","吃饭"]；
      写散文集 → ["写作","如我们所书"]

如果这段里没有任何值得索引的东西，就返回空列表。宁可漏，不要凑数。

输出严格的 JSON，不要任何解释、不要 markdown 代码块：
{"items":[{"type":"decision|fact|emotion|todo|insight","content":"一句话，主语明确，脱离上下文也能读懂","keywords":["..."],"path":["分类","子分类"],"time_hint":"事件发生的时间，推断不出就空字符串","importance":0.0到1.0,"supersedes":["要推翻的旧记忆id，没有就空数组"]}]}"""


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def screen(api, cfg, chunk, recent_lines, threshold=0.6, speaker="主意识",
           tree_lines=None):
    """判断一块内容。返回条目列表。

    speaker 决定这段内容的来源，索引器靠它把主语写对：
      用户输入 → speaker="用户"
      AI 输出 → speaker="主意识"

    tree_lines 是已有的分类树（一串缩进好的路径字符串）。
    给它看，它才会往现成的格子里放，不会每次另起一套。
    """
    if not chunk or not chunk.strip():
        return []

    user = ""
    if recent_lines:
        user += "【既有索引（已存过，不要重复）】\n" + "\n".join(recent_lines) + "\n\n"
    if tree_lines:
        user += ("【已有分类树（我会优先往这些格子里放）】\n"
                 + "\n".join(tree_lines) + "\n\n")
    user += f"【下面是「{speaker}」说的/想的内容】\n" + chunk.strip()

    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]

    try:
        raw = llm.chat(
            api, cfg, messages,
            model=cfg["screener_model"],
            temperature=cfg["screener_temperature"],
            max_tokens=cfg["screener_max_tokens"],
        )
    except Exception as e:  # 索引挂了不能拖死主意识
        print(f"\n[索引器异常，跳过这一块] {e}")
        return []

    obj = _extract_json(raw)
    if not obj:
        print(f"\n[索引器输出无法解析，跳过] {raw[:200]}")
        return []

    items = []
    for it in obj.get("items") or []:
        if not isinstance(it, dict):
            continue
        try:
            imp = float(it.get("importance", 0))
        except (TypeError, ValueError):
            imp = 0.0
        content = (it.get("content") or "").strip()
        if not content:
            continue
        kws = it.get("keywords") or []
        if isinstance(kws, str):
            kws = [k.strip() for k in re.split(r"[,，、\s]+", kws) if k.strip()]
        items.append({
            "type": it.get("type", "insight"),
            "content": content,
            "keywords": [str(k) for k in kws][:12],
            "path": _clean_path(it.get("path") or it.get("domain")),
            "time_hint": (it.get("time_hint") or "").strip(),
            "importance": imp,
            "supersedes": it.get("supersedes") or [],
            "below_threshold": imp < threshold,
        })
    return items


def _clean_path(val):
    """分类路径洗干净：最多三级，每级不超过 6 字。"""
    if not val:
        return []
    if isinstance(val, str):
        val = [val]
    out = []
    for p in val:
        p = str(p).strip().strip("[]\"'")
        p = re.sub(r"[\\/:*?\"<>|\s]+", "", p)
        if p and len(p) <= 6 and p not in out:
            out.append(p)
    return out[:3]
