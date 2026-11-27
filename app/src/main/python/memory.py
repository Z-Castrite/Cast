"""记忆库：全量原文 + 索引层 + 单一写入者 + 自污染防护。

之前的设计有个根本错误：筛选器当守门员，它认为不重要的就不存，
再加上 history 满了会丢——两者一叠，东西就永久消失了。
那不叫记忆，那叫抽样后的残影。

现在的结构：

    raw.jsonl      每轮完整原文，只追加，永不删、永不进检索
      ↑ 原文回捞
    memory.json    索引层：摘要 + 关键词 + 重要性（这才是被检索的东西）

纪律（写进代码，不靠自觉）：
  1. 只有 MemoryStore 一个对象能写。
  2. raw 只追加，物理上不提供删除接口。
  3. 索引条目默认是"推测"（draft），
     只有被用户确认才升格为"已确认"（confirmed）。
  4. 筛选器不再决定"存不存"，只决定"怎么索引"。
"""

import glob
import json
import os
import re
import threading
from datetime import datetime

import embed as embedmod


# ---------------------------------------------------------------- 工具

def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _month():
    """当前月份，用来決定事件写到哪个分片文件。"""
    return datetime.now().strftime("%Y-%m")


def _id_num(entry_id):
    """m0042 → 42。解析不了就当 0。"""
    m = re.search(r"(\d+)", entry_id or "")
    return int(m.group(1)) if m else 0


_STOP = set("的了是在我你他她它们这那就都也还和与或而但不没很要会能可以一说个上下来去有对把被给让从到这么那吗呢吧啊呀哦嗯")


def _bigrams(text):
    """中文没有空格，用二元组做检索键。零依赖，够用。"""
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text.lower())
    grams = set()
    for i in range(len(text) - 1):
        g = text[i:i + 2]
        if g not in _STOP:
            grams.add(g)
    return grams


class MemoryStore:
    def __init__(self, root, embed_cfg=None, reranker=None):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, "memory.json")
        self.raw_path = os.path.join(root, "raw.jsonl")
        self.lock = threading.Lock()
        self.data = {"next_id": 1, "entries": []}
        # 存储从"一个大 JSON"改成"按时间分片的文件夹"。
        #
        #   months/2026-11.jsonl   当月所有事件（新增 / 改状态），只追加
        #   raw/2026-11.jsonl      当月原文，只追加
        #
        # 为什么要改：JSON 是一个整体，改一个字要重写整个文件。
        # 三千条时写一次 61ms，一年后一万条要两百多毫秒——每轮对话要写好几次。
        # 追加式写入永远是 O(1)，不管库多大。
        # 顺带还有两个好处：一条坏了只丢那一行，以及每次改状态都留了痕迹。
        self.months_dir = os.path.join(root, "months")
        self.raw_dir = os.path.join(root, "raw")
        os.makedirs(self.months_dir, exist_ok=True)
        os.makedirs(self.raw_dir, exist_ok=True)
        # 向量检索配置。关了、或者本地服务连不上，就自动回退字符匹配。
        self.embed_cfg = embed_cfg or {}
        self.embed_enabled = bool(self.embed_cfg.get("enabled"))
        self._embed_failed = False
        # 重排回调：由 run.py 注入，memory 不直接依赖 API 细节
        self.reranker = reranker
        # 条目少于此数时跳过粗筛——粗筛会漏召，而库小的时候没必要省这点钱
        self.rerank_all_limit = 40
        self._load()

    def _embed(self, text):
        """算向量。失败返回 None，调用方自动降级。

        失败一次就不再试——本地服务挂了不该让每一轮都卡在超时上。
        """
        if not self.embed_enabled or self._embed_failed:
            return None
        try:
            return embedmod.embed(
                text,
                self.embed_cfg.get("base_url", "http://127.0.0.1:11434"),
                self.embed_cfg.get("model", "nomic-embed-text"),
                self.embed_cfg.get("timeout", 15),
            )
        except Exception as e:
            self._embed_failed = True
            print(f"\n[向量检索不可用，已降级为字符匹配] {e}")
            return None

    # ------------------------------------------------------------ 持久化

    def _load(self):
        """从月度文件重建内存视图。

        每个文件是一串事件，一行一个：
          {"_op": "upsert", "entry": {...}}              新增或整体覆盖
          {"_op": "patch", "id": "m0001", "patch": {...}}  改状态、升格、推翻

        后写的覆盖先写的。所以改一条记忆的状态只需要追加一行，
        不用重写整个库——这也是为什么文件夹比单文件合适。
        """
        by_id = {}
        max_id = 0
        self._migrate_legacy()
        for path in sorted(glob.glob(os.path.join(self.months_dir, "*.jsonl"))):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue        # 坏了一行，跳过，不拖累整个库
                        op = rec.get("_op")
                        if op == "upsert" and rec.get("entry"):
                            e = rec["entry"]
                            by_id[e["id"]] = e
                            max_id = max(max_id, _id_num(e["id"]))
                        elif op == "patch" and rec.get("id") in by_id:
                            by_id[rec["id"]].update(rec.get("patch") or {})
            except OSError:
                continue
        self.data = {"next_id": max_id + 1, "entries": list(by_id.values())}

    def _migrate_legacy(self):
        """老的 memory.json / raw.jsonl 迁到分片目录里。

        只跑一次：迁完就把老文件改名成 .migrated，免得下次重复迁。
        """
        old_mem = os.path.join(self.root, "memory.json")
        if os.path.exists(old_mem) and not glob.glob(
                os.path.join(self.months_dir, "*.jsonl")):
            try:
                with open(old_mem, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for e in data.get("entries") or []:
                    self._append_event({"_op": "upsert", "entry": e})
                os.replace(old_mem, old_mem + ".migrated")
                print(f"[迁移] 老的 memory.json 已分片归档")
            except Exception as e:
                print(f"[迁移失败，保留原文件] {e}")

        old_raw = os.path.join(self.root, "raw.jsonl")
        if os.path.exists(old_raw) and not self._raw_files():
            try:
                with open(old_raw, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        rec = json.loads(line)
                        path = os.path.join(self.raw_dir, _month() + ".jsonl")
                        with open(path, "a", encoding="utf-8") as out:
                            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                os.replace(old_raw, old_raw + ".migrated")
                print(f"[迁移] 老的 raw.jsonl 已分片归档")
            except Exception as e:
                print(f"[迁移原文失败，保留原文件] {e}")

    def _append_event(self, record):
        """往当月分片追加一行。O(1)，库多大都一样快。"""
        path = os.path.join(self.months_dir, _month() + ".jsonl")
        line = json.dumps(record, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ------------------------------------------------------------ 元数据

    def _meta_path(self):
        return os.path.join(self.root, "meta.json")

    def get_meta(self, key, default=None):
        try:
            with open(self._meta_path(), "r", encoding="utf-8") as f:
                return json.load(f).get(key, default)
        except (OSError, json.JSONDecodeError):
            return default

    def set_meta(self, key, value):
        p = self._meta_path()
        data = {}
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        data[key] = value
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------ 分类索引
    #
    # 分类树不是外面设计好的，是索引器写入时自己长出来的。
    # 它每次写入都会先看已有的树，尽量往里放；实在放不下才开新节点。
    #
    # 磁盘上就是这样：
    #   facets/身体/_ids.jsonl          ← 身体这个节点下所有条目
    #   facets/身体/伤/_ids.jsonl       ← 再细一层
    # 每个节点都记 id，所以查任何一级都能命中。

    @staticmethod
    def _facet_name(name):
        return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name))[:24] or "_"

    def _facet_path(self, parts):
        d = os.path.join(self.root, "facets")
        for p in parts:
            d = os.path.join(d, self._facet_name(p))
        return d

    def _append_facet(self, parts, entry_id):
        """沿路径每一级都记一笔。查"身体"能查到，查"身体/伤"也能查到。"""
        d = os.path.join(self.root, "facets")
        os.makedirs(d, exist_ok=True)
        for p in parts:
            d = os.path.join(d, self._facet_name(p))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "_ids.jsonl"), "a", encoding="utf-8") as f:
                f.write(entry_id + "\n")

    @staticmethod
    def _read_ids(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return {line.strip() for line in f if line.strip()}
        except OSError:
            return set()

    def facet_tree_lines(self, max_lines=80):
        """把已有分类树渲染成缩进文本，给索引器看。

        不给它看，它每次都会另起一套新名字，
        最后长出几十棵互不相认的树。
        """
        root = os.path.join(self.root, "facets")
        if not os.path.isdir(root):
            return []
        lines = []

        def walk(base, depth):
            if len(lines) >= max_lines:
                return
            try:
                names = sorted(n for n in os.listdir(base)
                               if os.path.isdir(os.path.join(base, n)))
            except OSError:
                return
            for n in names:
                p = os.path.join(base, n)
                cnt = len(self._read_ids(os.path.join(p, "_ids.jsonl")))
                lines.append("  " * depth + f"{n}/" + (f"  ({cnt})" if cnt else ""))
                walk(p, depth + 1)

        walk(root, 0)
        return lines

    def _facet_filter(self, query):
        """问题里提到了某个分类，就只在这些条目里找。

        走一遍已建的分类树，路径上任何一级名字出现在问题里，就算命中。
        命中几个节点就取并集——「都存一遍」的收益就在这里。
        一个都没命中，返回 None，退回全量扫描。
        """
        root = os.path.join(self.root, "facets")
        if not os.path.isdir(root):
            return None
        ids = set()
        hit = False

        def walk(base):
            nonlocal hit
            try:
                names = sorted(n for n in os.listdir(base)
                               if os.path.isdir(os.path.join(base, n)))
            except OSError:
                return
            for n in names:
                p = os.path.join(base, n)
                if n != "_" and len(n) >= 1 and n in query:
                    found = self._read_ids(os.path.join(p, "_ids.jsonl"))
                    if found:
                        ids.update(found)
                        hit = True
                walk(p)

        walk(root)
        return ids if hit else None

    # ------------------------------------------------------------ 全量原文

    def append_raw(self, user_text, draft_text, final_text=None, affect=None):
        """每轮只存两样东西：原始推理链路（初稿）+ 最终输出。

        不存中间态。文言稿那种东西，在生成过程中存在过就够了，没有留存价值。

        为什么留这两样：
          draft —— 主意识当时是怎么想的。日后能回溯"为什么这么说"。
          final —— 用户实际看到的那个版本。他下次开口引用的是这个，
                   不是初稿。记忆和现实对齐，检索才准。

        affect 是这一轮的情绪分布：{"heard": {...}, "said": {...}}。
        收到消息时判一次、说完时判一次，都留在这儿，日后能对账
        "他说那句话的时候我是什么心情"。
        """
        rec = {
            "ts": _now(),
            "user": user_text,
            "draft": draft_text,
            "final": final_text if final_text is not None else draft_text,
            "affect": affect or {},
        }
        with self.lock:
            # 原文也按月分片，追加式。不再往一个大文件里堆。
            path = os.path.join(self.raw_dir, _month() + ".jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def _raw_files(self):
        """所有原文分片，按月份从旧到新。"""
        return sorted(glob.glob(os.path.join(self.raw_dir, "*.jsonl")))

    def read_raw(self, limit=10):
        """读最近 N 轮原文。

        只看最新的几个分片——从最旧的开始读整年没必要。
        """
        files = self._raw_files()
        if not files:
            return []
        out = []
        with self.lock:
            for path in reversed(files):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                except OSError:
                    continue
                for line in reversed(lines):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                    if len(out) >= limit:
                        break
                if len(out) >= limit:
                    break
        out.reverse()
        return out

    def count_raw(self):
        total = 0
        with self.lock:
            for path in self._raw_files():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        total += sum(1 for line in f if line.strip())
                except OSError:
                    continue
        return total

    # ------------------------------------------------------------ 索引层写入

    def append_episodic(self, item, source="self_thought", turn_ref=None,
                        layer=None, confirmed=False):
        """索引层的写入口。

        默认：layer="episodic"、status="draft"（筛选器写进来的东西，先当推测）。
        但种子数据（用户确认过的旧记忆、通用知识）需要直接写进对应层，
        所以留了 layer / confirmed 两个口子。

        层的含义：
          episodic  —— 情节层，筛选器写，默认是推测
          semantic  —— 语义层，用户确认过的事实（关于用户的）
          knowledge —— 知识库，通用原则/技术结论，不属于某个人
        """
        content = (item.get("content") or "").strip()
        if not content:
            return None
        keywords = [str(k).strip() for k in (item.get("keywords") or []) if str(k).strip()][:12]

        # 向量在锁外算：embedding 要几十毫秒，不能卡住写入队列
        vec = self._embed(content + " " + " ".join(keywords))

        with self.lock:
            mid = "m%04d" % self.data["next_id"]
            self.data["next_id"] += 1
            entry = {
                "id": mid,
                "layer": layer or "episodic",
                "type": item.get("type", "insight"),
                "content": content,
                "keywords": keywords,
                # 主题分类路径，写入时就定好。例：["身体", "伤"]
                "path": item.get("path") or item.get("domain") or [],
                # 事件发生的时间（不是记录时间）。空字符串表示推断不出。
                "time_hint": (item.get("time_hint") or "").strip(),
                # 情感标签：切分制情绪分布，例 {"开心": 5.19, "担忧": 4.01}。
                # 由 affect 模型判，不是这条记忆自己写的；0 分的情绪不会出现在这里。
                "emotions": dict(item.get("emotions") or {}),
                "affect_note": (item.get("affect_note") or "").strip(),
                "importance": float(item.get("importance", 0.5)),
                "confidence": 0.95 if confirmed else (
                    0.5 if source == "self_thought" else 0.9),
                "source": source,
                "status": "confirmed" if confirmed else "draft",
                "supersedes": item.get("supersedes") or [],
                "turn_ref": turn_ref,
                "vec": vec,
                "created_at": _now(),
                "day": _today(),
            }
            self.data["entries"].append(entry)
            self._append_event({"_op": "upsert", "entry": entry})
            # 分类索引：按路径建多级文件夹，里面只记 id。
            # 一条记忆有几条路径就进几个文件夹——「都存一遍」，
            # 检索时找到任何一个抽屉，里面就是它。
            p = entry.get("path") or []
            if p:
                self._append_facet(p, mid)
            for old_id in entry["supersedes"]:
                for e in self.data["entries"]:
                    if e["id"] == old_id and e["status"] != "superseded":
                        e["status"] = "superseded"
                        e["superseded_by"] = mid
                        self._append_event({
                            "_op": "patch", "id": old_id,
                            "patch": {"status": "superseded", "superseded_by": mid},
                        })
            return entry

    def promote(self, entry_id, source="user_confirmed"):
        """把一条推测升格为已确认，并进入语义层。"""
        with self.lock:
            for e in self.data["entries"]:
                if e["id"] == entry_id and e["status"] == "draft":
                    patch = {"status": "confirmed", "layer": "semantic",
                             "source": source, "confidence": 0.95}
                    e.update(patch)
                    self._append_event({"_op": "patch", "id": entry_id, "patch": patch})
                    return e
            return None

    def supersede(self, entry_id, by_id, why=""):
        """把一条记忆标成被取代。不删，只标记——被取代的以后不参与检索。"""
        with self.lock:
            for e in self.data["entries"]:
                if e["id"] == entry_id and e["status"] != "superseded":
                    patch = {"status": "superseded", "superseded_by": by_id,
                             "supersede_why": why}
                    e.update(patch)
                    self._append_event({"_op": "patch", "id": entry_id, "patch": patch})
                    return e
            return None

    def recategorize(self, entry_id, path):
        """改一条记忆归到哪个分类下。

        旧分类文件夹里的 id 不动——查旧名字也还能找到，只是多了一条新路径。
        分类改错不该让人彻底找不到它。
        """
        with self.lock:
            for e in self.data["entries"]:
                if e["id"] == entry_id:
                    e["path"] = list(path)
                    self._append_event({
                        "_op": "patch", "id": entry_id, "patch": {"path": list(path)},
                    })
                    self._append_facet(path, entry_id)
                    return e
            return None

    def prune(self, max_entries=5000):
        """归档旧的 superseded，不物理删除。"""
        with self.lock:
            keep, arch = [], []
            for e in self.data["entries"]:
                if e["status"] == "superseded":
                    arch.append(e)
                else:
                    keep.append(e)
            if len(keep) > max_entries:
                arch.extend(keep[:-max_entries])
                keep = keep[-max_entries:]
            self.data["entries"] = keep
            if arch:
                with open(os.path.join(self.root, "archive.jsonl"), "a", encoding="utf-8") as f:
                    for e in arch:
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")
                # 归档掉的，在事件流里标一下，下次加载不会再出现
                for e in arch:
                    self._append_event({
                        "_op": "patch", "id": e["id"],
                        "patch": {"status": "archived"},
                    })
            return len(arch)

    # ------------------------------------------------------------ 检索

    def is_duplicate(self, content, threshold=0.72):
        """这条内容是不是已经有一条差不多在库里了。

        主要给"它自己的念头"用：每次醒来重新发现同一件事，
        不去重的话，记忆库会被同一批想法灌满。
        """
        g = _bigrams(content)
        if not g:
            return False
        with self.lock:
            entries = list(self.data["entries"])
        for e in entries:
            if e["status"] == "superseded":
                continue
            eg = _bigrams(e["content"])
            if not eg:
                continue
            overlap = len(g & eg) / min(len(g), len(eg))
            if overlap >= threshold:
                return True
        return False

    def search(self, query, k=8, layer=None, use_rerank=True):
        """给定 query 找最该进上下文的条目。

        有向量就走向量（语义匹配：问"我那条伤"能捞到"肌肉空洞"），
        没向量就退回字符二元组（字面匹配）。
        两边都叠关键词命中与时间衰减。
        """
        with self.lock:
            entries = list(self.data["entries"])
        if not entries:
            return []

        # 先圈定待检索集合
        pool = []
        for e in entries:
            if e["status"] == "superseded":
                continue
            if layer and e["layer"] != layer:
                continue
            pool.append(e)
        if not pool:
            return []

        # 分类预筛：问题里提到了某个分类，就只在这个格子里找。
        # 找不到格子就退回全量——不赌分类一定对。
        #
        # 这一步就是"文件夹检索"：找到对的那个抽屉，里面的就是候选，
        # 不用把整个库扫一遍。库越大，省得越多。
        facet_ids = self._facet_filter(query)
        if facet_ids:
            narrowed = [e for e in pool if e["id"] in facet_ids]
            if narrowed:
                pool = narrowed

        use_rr = bool(use_rerank and self.reranker and len(pool) > 1)

        # 库小的时候不做粗筛，直接全部交给重排模型。
        #
        # 这一条是踩过坑之后改的：粗筛是省钱手段，不是召回手段。
        # 问"我身上哪里缺了一块"，跟"肌肉空洞"一个字都对不上，
        # 粗筛直接返回空——重排拿不到候选，再聪明也救不回来。
        # 所以条目少的时候让模型看全量，漏召问题从根上消失。
        if use_rr and len(pool) <= self.rerank_all_limit:
            try:
                picked = self.reranker(query, pool, k)
                if picked:
                    return picked
            except Exception as e:
                print(f"\n[重排异常，回退字符匹配] {e}")

        qvec = self._embed(query)
        qgrams = _bigrams(query)
        qtext = query.lower()
        if qvec is None and not qgrams:
            return pool[:k]

        now = datetime.now()
        scored = []
        for e in pool:
            kws = e.get("keywords") or []
            kw_hit = sum(1 for kw in kws if kw and kw.lower() in qtext)

            if qvec is not None and e.get("vec"):
                # 余弦对不相关文本也有 0.3~0.5 的底噪，先减掉再映射到 0~1
                sem = embedmod.cosine(qvec, e["vec"])
                base = max(0.0, (sem - 0.45) / 0.55)
                floor = 0.02
            else:
                grams = _bigrams(e["content"] + " " + " ".join(kws))
                hits = len(qgrams & grams) if qgrams else 0
                base = hits / (len(grams) ** 0.5 + 1.0) if grams else 0.0
                floor = 0.0

            try:
                age_days = (now - datetime.strptime(e["created_at"], "%Y-%m-%d %H:%M:%S")).days
            except (ValueError, KeyError):
                age_days = 0
            recency = 1.0 / (1.0 + age_days / 14.0)     # 两周半衰

            score = (base + 0.12 * kw_hit) * (0.7 + 0.3 * e.get("importance", 0.5)) * recency
            if score > floor:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        # 粗筛多取一些，交给重排模型精挑。粗筛保证不漏太多，精排保证顺序对。
        coarse = [e for _, e in scored[:max(k, 15)]]
        if use_rr and len(coarse) > 1:
            try:
                picked = self.reranker(query, coarse, k)
                if picked:
                    return picked
            except Exception as e:
                print(f"\n[重排异常，回退粗筛顺序] {e}")
        return coarse[:k]

    # ------------------------------------------------------------ 原文兜底检索

    def search_raw(self, query, limit=2, scan=300):
        """在最近 N 轮原文里找命中的。

        存在的理由：索引器当时认为不重要的东西，索引层里没有，
        但它可能恰恰是日后要问的。这一层保证它还有最后一次被捞到的机会。
        """
        qgrams = _bigrams(query)
        if not qgrams:
            return []
        rows = self.read_raw(limit=scan)
        scored = []
        for r in rows:
            # 兼容：旧记录只有 reply，新记录是 draft + final
            parts = [r.get("user"), r.get("draft"), r.get("final"), r.get("reply")]
            text = " ".join(p for p in parts if p)
            grams = _bigrams(text)
            hits = len(qgrams & grams)
            if hits:
                scored.append((hits / (len(grams) ** 0.5 + 1.0), r))
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:limit]]

    # ------------------------------------------------------------ 注入

    def render_context(self, query, cfg):
        """组装给主意识看的记忆区。

        分三层：
          热：最近原文（由调用方从 history 给，不在这里）
          温：已确认 / 高重要性
          冷：推测
        这个分块是整套东西里最重要的一处：
        不分的话，主意识会把自己上一轮编的东西当成事实。
        """
        limit_conf = cfg.get("inject_confirmed", 6)
        limit_spec = cfg.get("inject_speculative", 3)
        max_chars = cfg.get("max_entry_chars", 400)

        confirmed = self.search(query, k=limit_conf, layer="semantic")
        drafts = self.search(query, k=limit_spec, layer="episodic")
        knows = self.search(query, k=cfg.get("inject_knowledge", 3), layer="knowledge")

        def fmt(items):
            out = []
            for e in items:
                c = e["content"]
                if len(c) > max_chars:
                    c = c[:max_chars] + "…"
                when = e.get("time_hint") or ""
                prefix = f"[{when}] " if when else ""
                out.append(f"- {prefix}[{e['type']}] {c}")
            return "\n".join(out)

        parts = []
        if confirmed:
            parts.append("【已确认的事】（关于他的，我可以直接当作已知）\n" + fmt(confirmed))
        if knows:
            parts.append("【知识库】（通用的原则与结论，不限于是谁的事）\n" + fmt(knows))
        if drafts:
            parts.append(
                "【我此前的推测】（我自己想过但没被他确认过，可能是我在自我强化，"
                "需要时我重新核实，不当事实用）\n" + fmt(drafts)
            )

        # 兜底：索引层命中不足时，去原文里捞。
        #
        # 之前的条件是"索引层一条都没命中才捞"——那等于说：
        # 只要索引层命中了任何一条相关的、却没命中目标的那条，原文就被永远锁死。
        # 而索引器当时判不重要的东西，恰恰不会进索引层。
        # 所以改成：命中数低于门槛就补，并做去重，避免和索引层重复注入。
        total_hits = len(confirmed) + len(drafts)
        fallback_at = cfg.get("raw_fallback_at", 2)
        if total_hits < fallback_at:
            raws = self.search_raw(query, limit=cfg.get("inject_raw", 2))
            seen = "".join(e["content"] for e in (confirmed + drafts))
            lines = []
            for r in raws:
                snippet = (r.get("user") or "").strip()
                if not snippet:
                    # 新记录用 final（用户实际看到的版本），旧记录用 reply
                    snippet = (r.get("final") or r.get("reply") or "").strip()[:150]
                snippet = snippet[:150]
                # 已经通过索引层进过上下文的内容，不要重复塞
                if snippet[:20] and snippet[:20] in seen:
                    continue
                lines.append(f"- [{r.get('ts', '')}] {snippet}")
            if lines:
                parts.append(
                    "【更早的对话原文片段】（没有整理过的原始记录，"
                    "仅供参考，可能有噪音）\n" + "\n".join(lines)
                )
        return "\n\n".join(parts)

    def stats(self):
        with self.lock:
            entries = list(self.data["entries"])
        # 注意：count_raw 自己会拿 lock，非重入锁下不能再套一层
        raw_count = self.count_raw()
        return {
            "total": len(entries),
            "confirmed": sum(1 for e in entries if e["status"] == "confirmed"),
            "draft": sum(1 for e in entries if e["status"] == "draft"),
            "superseded": sum(1 for e in entries if e["status"] == "superseded"),
            "raw": raw_count,
        }
