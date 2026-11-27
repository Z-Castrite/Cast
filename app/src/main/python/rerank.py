"""检索重排：让一个模型来读你的问题，决定哪些记忆相关。

为什么需要这一层：
  问"我身上哪里缺了一块"，字面上跟"肌肉空洞"一个字都对不上。
  字符匹配找不到。而模型看一眼就知道说的是同一件事。

为什么用 LLM 而不是向量：
  DeepSeek 没有 embedding 接口（可用模型只有 flash 和 v4-pro）。
  但 LLM 重排其实比向量更强——它不只算相似度，还能推理。
  代价是慢一点（1 秒左右）、贵一点（每次约 1000 token），但都在可接受范围。

两个踩过的坑，写在这里免得以后重犯：

  1. max_tokens 不能给太小。deepseek-flash 是推理模型，
     60 token 全被推理链吃光，content 返回空字符串。
     所以给 400。

  2. 不能让模型输出 "3,5" 这种逗号分隔——deepseek-chat 会把标点吞掉，
     变成 "35"，于是被解析成第三十五条，全盘错位。
     所以强制 JSON 输出，编号在数组里，位置明确。
"""

import json
import re

import llm


def make_reranker(cfg):
    """返回一个 (query, candidates, k) -> list 的函数，给 MemoryStore 用。

    这样 memory 模块不用知道 API 怎么调，只认这个回调。
    """
    if not cfg.get("rerank_enabled"):
        return None

    api = cfg["api"]
    model = cfg["rerank_model"]

    def rerank(query, candidates, k=4):
        if not candidates:
            return []
        if len(candidates) == 1:
            return candidates        # 只有一条，没什么可挑的

        lines = []
        for i, c in enumerate(candidates, 1):
            when = c.get("time_hint") or ""
            prefix = f"[{when}] " if when else ""
            lines.append(f"{i}. {prefix}[{c.get('type', '?')}] {c['content'][:120]}")

        prompt = (
            f"问题：{query}\n\n"
            "候选记忆：\n" + "\n".join(lines) + "\n\n"
            f"我要挑出与问题真正相关的，最多 {k} 条。\n\n"
            "**注意时间——这是最容易出错的地方：**\n"
            "- 如果问题带时效性（“上次”“昨天”“最近”“前几天”），我优先最近的那条\n"
            "- 如果问的是很久以前的事，我不拿最近的事顶替\n"
            "- 同一件事在不同时间发生过多次，问题问哪次就只给哪次，不混在一起\n"
            "- 时间对不上但关键词很像的，我宁可不要\n\n"
            "我只输出 JSON，不要任何其他文字、不要代码块：\n"
            '{"pick":[编号,编号]}\n'
            "一条都不相关就输出 {\"pick\":[]}"
        )

        try:
            out = llm.chat(
                api, cfg, [{"role": "user", "content": prompt}],
                model=model, temperature=0.0, max_tokens=400,
            )
        except Exception as e:
            print(f"\n[重排失败] {e}")
            return []

        obj = _extract_json(out)
        if not obj:
            print(f"\n[重排无结果] 模型返回: {out[:100]!r}")
            return []

        picked = []
        for n in obj.get("pick") or []:
            try:
                idx = int(n) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(candidates) and candidates[idx] not in picked:
                picked.append(candidates[idx])

        # 解析失败就返回空——宁可"没找到"，也不要"给一条错的"。
        # 错误注入比不注入更糟：它会让主意识在一段无关记忆上继续推理。
        return picked[:k]

    return rerank


def _extract_json(text):
    """模型可能吐代码块或带解释，做容错提取。"""
    text = (text or "").strip()
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
