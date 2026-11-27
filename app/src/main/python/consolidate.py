"""记忆整理：每天一次，把新记下来的东西捋一遍。

相当于睡眠时的大脑巩固。白天记的东西又碎又名目混乱——
同一个人说了三遍同一件事，两条记忆互相矛盾，一条该归到 A 类却塞进了 B 类。
不整理的话，越攒越乱，检索越来越不准。

整理做什么：
  1. 合并重复——说的是同一件事，留信息最全的那条
  2. 处理矛盾——两条对不上，判断哪个更可信
  3. 修正分类——分错抽屉的挪回去

**不做**什么：
  - 不删任何东西（只用 supersede 标记被取代的）
  - 不合并时间不同的同一件事（"去年住院"和"今年住院"是两件事）
  - 不改原文（raw 永远不动）

跑法：由 run.py 每天自动触发；也可以手动 python consolidate.py
"""

import json
import re
from datetime import datetime

import llm

_SYSTEM = """我在整理自己的记忆。下面是一组同类记录，我要找出有问题的地方。

**该合并的：**
- 重复：说的是同一件事，留信息最全的那条
- 补充：一条是另一条的一部分，可以并成一条更完整的

**该处理的矛盾：**
- 两条对不上（同一件事两种说法、时间冲突）
- 判断哪个更可信，或者标明存疑

**不要合并的：**
- 时间不同的同一类事（"去年住院"和"今年住院"是两件事）
- 只是关键词像、其实不是一回事的

输出 JSON，不要别的字：
{"merge":[{"keep":"m0005","drop":["m0006"],"why":"重复"}],
 "conflict":[{"keep":"m0001","drop":["m0002"],"why":"后者是旧判断"}],
 "recat":[{"id":"m0007","path":["身体","伤"],"why":"分错类"}]}

没有要处理的就输出 {"merge":[],"conflict":[],"recat":[]}"""


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


def _fmt(entries):
    lines = []
    for e in entries:
        when = e.get("time_hint") or ""
        prefix = f"[{when}] " if when else ""
        lines.append(f"{e['id']} {prefix}{e['content']}")
    return "\n".join(lines)


def _ask(cfg, group_name, entries):
    """问一次：这组记忆里有什么问题。"""
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"分类「{group_name}」下的记录：\n\n" + _fmt(entries)},
    ]
    try:
        out = llm.chat(
            cfg["api"], cfg, messages,
            model=cfg["screener_model"],
            temperature=0.1,
            max_tokens=800,
        )
    except Exception as e:
        print(f"  [整理调用失败] {e}")
        return None
    return _parse(out)


def _apply(store, result, verbose=True):
    """执行整理结果。只用 supersede，不删东西。"""
    if not result:
        return 0
    done = 0
    by_id = {e["id"]: e for e in store.data["entries"]}

    # 合并 / 矛盾：留 keep，把 drop 的全标成被取代
    for kind in ("merge", "conflict"):
        for item in result.get(kind) or []:
            keep = item.get("keep")
            drops = item.get("drop") or []
            if keep not in by_id:
                continue
            for did in drops:
                if did == keep or did not in by_id:
                    continue
                store.supersede(did, keep, why=item.get("why") or kind)
                done += 1
                if verbose:
                    print(f"  · {did} 并入 {keep}（{item.get('why') or kind}）")

    # 分类修正
    for item in result.get("recat") or []:
        eid = item.get("id")
        path = item.get("path") or []
        if eid in by_id and path:
            store.recategorize(eid, path)
            done += 1
            if verbose:
                print(f"  · {eid} 改归到 {'/'.join(path)}")

    return done


def run(cfg, store, verbose=True):
    """整理一轮。返回处理了多少条。"""
    since = store.get_meta("last_consolidate") or ""
    entries = [e for e in store.data["entries"]
               if e["status"] != "superseded" and e["status"] != "archived"]

    news = [e for e in entries if (e.get("created_at") or "") > since]
    if not news:
        if verbose:
            print("  [整理] 没有新记忆，跳过。")
        return 0

    if verbose:
        print(f"  [整理] 上次整理之后新增 {len(news)} 条。")

    # 按分类根节点分组。新记忆所在的那几组优先。
    groups = {}
    for e in news:
        p = e.get("path") or []
        key = p[0] if p else "_无分类"
        groups.setdefault(key, set()).add(e["id"])

    total = 0
    for key, new_ids in groups.items():
        # 这一组下的所有现有条目（不只是新的）
        same = [e for e in entries
                if ((e.get("path") or ["_无分类"])[0] == key)]
        if len(same) < 2:
            continue
        if verbose:
            print(f"  整理分类「{key}」（{len(same)} 条，其中新增 {len(new_ids)} 条）")
        # 太多了就分批，一批最多 20 条
        for i in range(0, len(same), 20):
            batch = same[i:i + 20]
            if len(batch) < 2:
                continue
            res = _ask(cfg, key, batch)
            total += _apply(store, res, verbose=verbose)

    store.set_meta("last_consolidate", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if verbose:
        print(f"  [整理] 完成，处理了 {total} 处。")
    return total


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cfg as cfgmod
    import memory

    c = cfgmod.load_config()
    if not cfgmod.has_key(c):
        print("先把 config.json 的 api_key 填了。")
        raise SystemExit(1)
    s = memory.MemoryStore(os.path.join(cfgmod.ROOT, "memory_store"))
    print(f"库里 {len(s.data['entries'])} 条")
    run(c, s)
