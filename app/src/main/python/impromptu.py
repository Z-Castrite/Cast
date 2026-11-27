"""主动思考：没人说话的时候，它自己醒过来，翻记忆，想事情。

不是"定时说一句话"。是：

    睡了一会 → 醒来 → 有点无聊 → 翻自己记着的事
    → 找对不上的、找缺的、推一条新的、挑一个想不通的
    → 然后才决定：要不要找他说话

想完了可以不说。也可以只是问一句「在干嘛」。

这套东西的意义不在"能主动发消息"，在于：
**它会跟自己较劲。** 记忆里有对不上的地方，它会不舒服；
缺了一块，它会想知道；两条合起来能推出新东西，它会自己推。
"""

import json
import re

import llm

_SCENE = """{hours} 小时过去了。
没人跟我说话。
有点无聊。

我翻翻我记着的事。"""

_RULES = """我翻的时候不只是过一遍。看这四样：

1. **对不上的**——两件事互相矛盾、时间不对、同一个人两种说法
2. **缺的**——提过但没记住、我该知道却不知道的
3. **能推出来的**——两条记忆合起来，能得出一个新结论
4. **想不通的**——有什么地方说不通

看完我再决定：要不要找他说话。

**注意上面「我问过但没得到回答的」那些。**
问过的我不再拿一模一样的话问一遍。可以换个角度，换个问法，
也可以先把这事搁着，说点别的。

不说也行。但要开口我就不请示、不解释我在做什么——
直接说，像人一样。

只输出 JSON，不要别的字、不要代码块：
{"conflict": "对不上的，没有就留空", "gap": "缺的，没有就留空", "inference": "推出来的，没有就留空", "puzzle": "想不通的，没有就留空", "speak": true 或 false, "text": "要说的话，没有就留空"}"""


def _parse(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e <= s:
        return None
    try:
        return json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return None


def think(cfg, store, persona, hours=6, sense=""):
    """醒一回。翻记忆、想事情，然后决定说不说。

    返回：
      None —— 决定不说话
      dict —— {"text": 要说的话, "noticed": {...}, "speak": True}
    """
    scene = _SCENE.format(hours=int(max(1, round(hours))))

    # 把最近记下的事摊开给它看。这是"翻"的材料。
    mem_lines = []
    if store is not None:
        try:
            entries = [e for e in store.data["entries"]
                       if e["status"] != "superseded"]
            for e in entries[-10:]:
                when = e.get("time_hint") or ""
                prefix = f"[{when}] " if when else ""
                mem_lines.append(f"· {prefix}{e['content'][:80]}")
        except Exception:
            pass

    mem_block = ""
    if mem_lines:
        mem_block = "我记着这些：\n" + "\n".join(mem_lines)
    else:
        mem_block = "我什么都没记着。"

    # 我问过、但没得到回答的。
    # 不单列出来的话，它会每隔几小时问一模一样的问题——
    # 因为它记得自己"想过什么"，却不记得自己"问过什么"。
    asked = []
    if store is not None:
        try:
            for e in store.data["entries"]:
                if e.get("type") == "question" and e["status"] != "superseded":
                    asked.append(e["content"][:80])
        except Exception:
            pass
    asked_block = ""
    if asked:
        asked_block = ("我问过、还没得到回答的：\n"
                       + "\n".join(f"· {a}" for a in asked[-5:]))

    system = "\n\n".join(p for p in [(persona or "").strip(), scene,
                                     mem_block, asked_block,
                                     ("我现在感知到的：\n" + sense) if sense else "",
                                     _RULES] if p)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "（没有新消息。）"},
    ]

    try:
        out = llm.chat(
            cfg["api"], cfg, messages,
            model=cfg["mind"]["model"],
            temperature=0.9,
            max_tokens=800,
        )
    except Exception as e:
        print(f"\n[主动思考调用失败] {e}")
        return None

    obj = _parse(out)
    if not obj:
        print(f"\n[主动思考输出无法解析] {out[:160]}")
        return None

    noticed = {
        "conflict": (obj.get("conflict") or "").strip(),
        "gap": (obj.get("gap") or "").strip(),
        "inference": (obj.get("inference") or "").strip(),
        "puzzle": (obj.get("puzzle") or "").strip(),
    }

    if not obj.get("speak"):
        return {"speak": False, "text": "", "noticed": noticed}

    text = (obj.get("text") or "").strip()
    if not text:
        return {"speak": False, "text": "", "noticed": noticed}
    return {"speak": True, "text": text, "noticed": noticed}
