"""情感判断：主意识收到/发出消息时，和记忆入库时，各打一份情绪分布。

===== 为什么单独一个模型 =====

主意识在说话，注意力在"怎么说对"，不在"我现在几分开心"。
索引器在判断"值不值得记"，标准是信息量，不是情绪。
让谁兼做都会两头不讨好；而且混在同一个 prompt 里，情绪分数会被它
自己刚写下的措辞带偏——它先写了"这没什么大不了的"，再打分就不敢打高。

所以拆出去：它只干一件事，只读一段话，只吐一份分布。

===== 切分制，不是单选 =====

满分 10 分，多个情绪可以同时有分。

    {"开心": 5.19, "担忧": 4.01, "苦涩": 0.80}

读作：开心五分多、担忧四分、苦涩不到一分。比例是 5.19 : 4.01 : 0.80。
不是「四舍五入归到一个标签」——那种打法会把"又苦又想笑"压成单选，
而人真正的状态恰好是同时的。

0 分的情绪不出现：空着比写 0 更省字，也不让模型以为"这些是低分项"。
分数保留两位小数。

===== 三个场景 =====

    heard   —— 刚读到他说的话，我此刻的情绪
    said    —— 话刚出口，我此刻的情绪
    memory  —— 这段要被记下来的内容，本身带着什么情绪

前面两路的判断会进主意识的系统提示（它自己看得见），第三路落在索引条目上，
以后 recall 到这条记忆时会带着这组情绪一起回来。

===== 成本 =====

每个场景一次短调用，几百 token。一轮对话多 2~3 次。
不想要就在 config.json 里关：`affect.enabled = false`。
"""

import json
import re

import llm

# 基础词表。刻意收窄：词太散，分数就没法横向比。
# 词表外的细节由模型自己加，不设数量限制。
BASE_EMOTIONS = [
    "开心", "平静", "疲惫", "担忧", "苦涩", "愤怒", "温柔", "孤独",
    "期待", "释然", "无力", "焦躁", "警惕", "心疼", "疏离", "压抑",
]

_SCENES = {
    "heard": "他刚对我说了一段话。我读完之后的情绪分布是：",
    "said": "我刚把话说完。话出口之后，我此刻的情绪分布是：",
    "memory": "下面这段内容要被记下来。这段记忆本身带着的情绪是：",
    # 下面三个是"感知通道"——情绪是它们的必经关卡，不是附加层：
    "seen": "我刚看了一眼那个画面。看到这个，我心里是：",
    "heard_voice": "我听到了一段声音。听到这个，我心里是：",
    "recall": "我翻到了这些旧事。翻到这些，我心里是：",
}

_SYSTEM = """我在判断我自己的情绪分布。

规则：
1. 满分 10 分。多个情绪可以同时有分，分数表示各自的强度。
2. 只写有分的，**0 分不写**。空着就是没有。
3. 分数保留两位小数（例：5.19、4.01、0.80）。
4. 优先用这个词表：{words}。
   词表不够表达细节时，可以另加更具体的词（比如"被推着走的焦躁"）。
5. **种类不设上限。** 实际有几种就写几种，别为了凑数硬加。
6. 另给一句 note：这情绪是被哪个字眼或细节勾出来的，不超过 30 字。

只输出 JSON，不要解释、不要代码块：
{{"emotions": {{"情绪名": 分数}}, "note": "..."}}"""


def _extract_json(text):
    """模型可能吐代码块或带解释，做容错提取。"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _clean_emotions(raw):
    """把模型吐的那坨东西洗成能用的分布。

    三条硬规则（都在这里，不靠模型自觉）：
      - 分数 clamp 到 0~10
      - 保留两位小数
      - 0 分剔除（包括负分）
    不设种类上限：判出几种就是几种，只按分数从高到低排。
    """
    out = {}
    if not isinstance(raw, dict):
        return out
    for name, val in raw.items():
        name = str(name).strip().strip("“”\"'「」")
        if not name or len(name) > 8:
            continue
        try:
            score = float(val)
        except (TypeError, ValueError):
            continue
        score = round(max(0.0, min(10.0, score)), 2)
        if score <= 0:
            continue
        out[name] = score
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _fmt_num(v):
    """5.19 → 5.19；0.80 → 0.8；10.00 → 10。"""
    s = f"{v:.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def format_emotions(emotions, top=None):
    """{"开心": 5.19, "担忧": 4.01} → "开心5.19分｜担忧4.01分"。

    top 不传就全给。情绪种类不设上限，显示也不截。
    """
    if not emotions:
        return ""
    items = sorted(emotions.items(), key=lambda kv: -kv[1])
    if top:
        items = items[:top]
    return "｜".join(f"{name}{_fmt_num(score)}分" for name, score in items)


def format_affect(aff, top=None):
    """完整的一句，给主意识系统提示用：分数 + 来由。"""
    emo = format_emotions((aff or {}).get("emotions") or {}, top=top)
    note = ((aff or {}).get("note") or "").strip()
    if not emo:
        return ""
    return emo + (f"（{note}）" if note else "")


def judge(api, cfg, text, scene="heard"):
    """判一次情绪。返回 {"emotions": {...}, "note": "..."}。

    失败、没配置、空文本 —— 一律返回空分布，绝不抛异常。
    情绪判断是锦上添花，不能因为它挂掉就拖住主意识。
    """
    empty = {"emotions": {}, "note": ""}
    text = (text or "").strip()
    if not text or not cfg.get("affect_enabled"):
        return empty

    system = _SYSTEM.format(words="、".join(BASE_EMOTIONS))
    prompt = _SCENES.get(scene, _SCENES["heard"]) + "\n\n" + text[:2000]

    try:
        out = llm.chat(
            api, cfg,
            [{"role": "system", "content": system},
             {"role": "user", "content": prompt}],
            model=cfg.get("affect_model") or cfg.get("screener_model"),
            temperature=cfg.get("affect_temperature", 0.2),
            max_tokens=cfg.get("affect_max_tokens", 300),
        )
    except Exception as e:
        print(f"\n[情感判断失败，这一轮不标情绪] {e}")
        return empty

    obj = _extract_json(out)
    if not obj:
        print(f"\n[情感判断输出无法解析] {out[:120]}")
        return empty

    return {
        "emotions": _clean_emotions(obj.get("emotions")),
        "note": (obj.get("note") or "").strip()[:60],
    }


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cfg as cfgmod

    c = cfgmod.load_config()
    if not cfgmod.has_key(c):
        print("先把 config.json 的 api_key 填了。")
        raise SystemExit(1)
    for scene, t in (
        ("heard", "今天又没睡好，脑子跟浆糊一样。"),
        ("said", "行，那我把这事先搁着。"),
    ):
        r = judge(c["api"], c, t, scene=scene)
        print(f"[{scene}] {format_affect(r) or '（空）'}")
