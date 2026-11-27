"""语言板块：白话 → 文言 → 白话 的往返压缩。

这个板块只做一件事：把啰嗦的表达先过一遍高密度语言，再还原。
效果是去水分、收紧句式。

===== 一条硬规矩，写在最前面 =====

**文言转换的结果绝对不进记忆库。**

记忆检索用的是字符二元组和关键词匹配。库里存"锥"，你问"螺丝刀"，
字符对不上，这条记忆就永久失联了。
更糟的是 raw.jsonl 存的原文和索引存的白话会对不上，整个追溯链断裂。

所以：转换只在输出端做一次。raw 存原文，索引存原文，只有屏幕上那句是文言转回来的。
"""

import llm

_CLASSICAL_SYS = """我在把下面这段白话文改写成文言文。

要求：
1. 必须保留全部具体信息：数字、数量、方位、专名、时间、因果、否定，一个都不能丢。
2. 我要去掉口头语、重复、铺垫、情绪修饰、客套。
3. 我不用生僻典故，不为了对仗牺牲准确性。
4. 我只输出文言文本身，不解释，不加译文。

如果原文里没什么可压缩的（比如已经很短），我就原样返回。"""

_VERNACULAR_SYS = """我在把下面这段文言文改写成现代白话文。

要求：
1. 信息完整，不许增加原文没有的内容。数字、方位、专名必须原样准确。
2. **我要用一个人对另一个人说话的口吻来写**，不写成书面报告、不写成文章。
3. **我禁止使用下列句式，出现任何一条即视为失败**：
   首先、其次、最后、总之、总的来说、综上所述、综上、
   需要注意的是、值得注意的是、需要指出的是、
   从……角度来看、从技术层面、从工程角度、
   一方面、另一方面、
   建议你、希望对你有所帮助、欢迎随时提问、
   这是一个很好的问题、非常好的问题。
4. 我不用「第一、第二、第三」或「一、二、三」这种序号列举。
   并列的东西我用口语串起来：「还有就是」「另外」「再说」。
5. 长句拆短。一段话不超过三句。
6. 我只输出白话文本身，不解释，不加标题。"""


def to_classical(text, api, cfg):
    """白话 → 文言。"""
    if not text or not text.strip():
        return text
    return llm.chat(
        api, cfg,
        [{"role": "system", "content": _CLASSICAL_SYS},
         {"role": "user", "content": text}],
        model=cfg["language_model"],
        temperature=cfg["language_temperature"],
        max_tokens=cfg["language_max_tokens"],
    ).strip()


def to_vernacular(text, api, cfg):
    """文言 → 白话。"""
    if not text or not text.strip():
        return text
    return llm.chat(
        api, cfg,
        [{"role": "system", "content": _VERNACULAR_SYS},
         {"role": "user", "content": text}],
        model=cfg["language_model"],
        temperature=cfg["language_temperature"],
        max_tokens=cfg["language_max_tokens"],
    ).strip()


def roundtrip(text, api, cfg, max_chars=1500):
    """走一整圈。返回 (白话终稿, 中间文言稿)。

    **长文本直接放弃这一步。**

    原因：文言转换的 max_tokens 是 1024。一段三千字的回答，白话转文言时
    会被截断——后面的内容直接没了，转回来的东西比原文短一截，还看不出来。
    分段转又会丢掉整篇的语气，拼起来是几段各说各话。

    而且写长文的时候本来就不需要去 AI 味——那会儿它是在给你写东西，
    不是在跟你说话。
    """
    if len(text or "") > max_chars:
        return text, ""

    classical = to_classical(text, api, cfg)
    back = to_vernacular(classical, api, cfg)
    return back, classical
