"""Engine：twobody 在手机里的入口。

run.py 是终端版——input() 收、print() 出。
App 里没有终端，所以把"一轮怎么跑"单独拿出来：

    e = Engine(filesDir)
    e.start()
    r = e.turn("你好")
    r["reply"]     # 它说的话
    r["emotions"]  # 这句话说完时的情绪分布

不 import 任何 Android 相关的东西，也不 import voice/capture/ptz——
那些归 Android 层管。engine 只认纯 Python，这样桌面也能跑同一份。
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor

import affect as affectmod
import cfg as cfgmod
import consolidate as consol
import impromptu
import memory
import rerank as rerankmod
import screener
import timer as timerlib
import vision
from mind import Mind, split_blocks

MAX_PENDING = 8


class Engine:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.cfg = None
        self.store = None
        self.mind = None
        self.pool = None
        self._pending = 0
        self._started = False
        # 主动机制：心跳 + 每日整理 + 攒着等人取的消息
        self._outbox = []
        self._last_interaction = 0.0
        self._hb = None
        self._hb_cons = None

    # ---------------------------------------------------------------- 启动

    def start(self):
        self.cfg = cfgmod.load_config(os.path.join(self.base_dir, "config.json"))
        persona = cfgmod.load_persona(os.path.join(self.base_dir, "persona.txt"))
        self.store = memory.MemoryStore(
            os.path.join(self.base_dir, "memory_store"),
            self.cfg["embedding"],
            rerankmod.make_reranker(self.cfg),
        )
        self.mind = Mind(self.cfg["api"], self.cfg, self.cfg, self.store, persona)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self._started = True
        self._last_interaction = time.time()
        self._start_proactive()
        return self.store.stats()

    # ---------------------------------------------------------------- 记忆检索

    def recall(self, query):
        hits = self.store.search(query, k=4)
        if not hits:
            return "没有找到相关的记忆。"
        lines = []
        for e in hits:
            tag = "已确认" if e["status"] == "confirmed" else "推测"
            c = e["content"]
            if len(c) > 300:
                c = c[:300] + "…"
            emo = affectmod.format_emotions(e.get("emotions") or {})
            head = ("【" + emo + "】") if emo else ""
            lines.append("[%s]%s %s" % (tag, head, c))

        text = "\n".join(lines)

        # 情绪是记忆通道的必经关卡：翻到这些旧事，先感到，再想。
        aff = affectmod.judge(self.cfg["api"], self.cfg, text, scene="recall")
        aff_line = affectmod.format_affect(aff)
        if aff_line:
            text += "\n\n（翻到这些，我心里：" + aff_line + "）"
        return text

    # ---------------------------------------------------------------- 旁路索引

    def _screen_and_store(self, chunk, speaker="主意识"):
        try:
            recent = [
                "[%s][%s] %s" % (e["id"], e["type"], e["content"][:120])
                for e in self.store.search(chunk, k=8, use_rerank=False)
            ]
            items = screener.screen(
                self.cfg["api"], self.cfg, chunk, recent,
                threshold=self.cfg["threshold"], speaker=speaker,
                tree_lines=self.store.facet_tree_lines(),
            )
            emo = {}
            if self.cfg["affect_enabled"] and any(
                    not it.get("below_threshold") for it in items):
                emo = affectmod.judge(self.cfg["api"], self.cfg, chunk, scene="memory")
            for it in items:
                if it.get("below_threshold"):
                    continue
                if emo.get("emotions"):
                    it["emotions"] = emo["emotions"]
                    it["affect_note"] = emo.get("note") or ""
                self.store.append_episodic(it)
        except Exception as e:
            print("[索引出错]", e)
        finally:
            self._pending -= 1

    def _on_block(self, text, speaker="主意识"):
        if self._pending >= MAX_PENDING:
            return
        self._pending += 1
        self.pool.submit(self._screen_and_store, text, speaker)

    # ---------------------------------------------------------------- 一轮对话

    def turn(self, text, image_bytes=None, speaker="用户"):
        if not self._started:
            return {"reply": "", "emotions": {}, "error": "engine 没启动"}
        text = (text or "").strip()
        if not text and not image_bytes:
            return {"reply": "", "emotions": {}, "error": "空输入"}
        self._last_interaction = time.time()

        # 视觉通道：先看，再看它带来的情绪。
        # 情绪是必经关卡——看到什么东西，先有感受，再进思考。
        seen_desc = ""
        if image_bytes:
            try:
                seen_desc = vision.look(
                    self.cfg["api"], self.cfg, image_bytes,
                    "我看到了什么？说具体的。") or ""
            except Exception:
                seen_desc = ""
            if seen_desc:
                seen_aff = affectmod.judge(self.cfg["api"], self.cfg, seen_desc,
                                           scene="seen")
                seen_line = affectmod.format_affect(seen_aff)
                text = (text + "\n\n（我看到的：\n" + seen_desc
                        + "\n看到这些，我心里：" + (seen_line or "说不清") + "）").strip()

        if not text:
            return {"reply": "", "emotions": {}, "error": "看不到，也没听到"}

        # 收到消息先判一次情绪，带着这个心情去读
        heard = affectmod.judge(self.cfg["api"], self.cfg, text, scene="heard")
        affect_line = affectmod.format_affect(heard)

        # 输入也切块进索引：用户说的东西不该只活在 raw 里。
        # speaker 决定记忆里的主语——群里的话不能都记成"用户说的"。
        for blk in split_blocks(text, max_chars=260):
            if blk.strip():
                self._on_block(blk.strip(), speaker=speaker)

        draft = ""
        try:
            for piece in self.mind.speak(
                    text, self._on_block, self.recall,
                    look_fn=self._look_fn,
                    affect=affect_line):
                draft += piece
        except Exception as e:
            return {"reply": "", "emotions": {}, "error": "调用失败: %s" % e}

        final = (draft or "").strip()

        # 说完再判一次：这一轮收在什么情绪上
        said = affectmod.judge(self.cfg["api"], self.cfg, final, scene="said")

        self.store.append_raw(
            text, final, final,
            affect={"heard": heard.get("emotions") or {},
                    "said": said.get("emotions") or {}},
        )

        return {
            "reply": final,
            "emotions": said.get("emotions") or {},
            "emotions_text": affectmod.format_emotions(said.get("emotions") or {}),
            "heard": heard.get("emotions") or {},
            "recalls": list(self.mind.last_recalls),
            "error": "",
        }

    def turn_group(self, text, speaker="群聊记录"):
        """群聊里的一轮：输入是群记录（谁说了什么都在里面），
        记忆里的主语标成"群聊记录"而不是"用户"——不然它会以为整段都是用户说的。"""
        return self.turn(text, None, speaker)

    # ---------------------------------------------------------------- 主动看

    def set_camera(self, camera):
        """接 Android 侧的拍照器。Python 直接调它的 takePhoto() 拿 JPEG。"""
        self._camera = camera

    def look(self, question="我看到了什么？"):
        """主意识主动看一眼：拍照 → 视觉 → 情绪。没有相机就算了。"""
        cam = getattr(self, "_camera", None)
        if cam is None:
            return {"desc": "", "emotions": {}, "error": "没有相机"}
        try:
            data = cam.takePhoto()
        except Exception as e:
            return {"desc": "", "emotions": {}, "error": str(e)}
        if not data:
            return {"desc": "", "emotions": {}, "error": "拍不到"}
        desc = vision.look(self.cfg["api"], self.cfg, bytes(data), question) or ""
        emo = {}
        if desc:
            emo = affectmod.judge(self.cfg["api"], self.cfg, desc, scene="seen")
        return {
            "desc": desc,
            "emotions": emo.get("emotions") or {},
            "emotions_text": affectmod.format_emotions(emo.get("emotions") or {}),
            "note": emo.get("note") or "",
            "error": "",
        }

    def _look_fn(self, question="我看到了什么？"):
        """给主意识当工具用：返回文字（画面 + 看到它的心情）。"""
        r = self.look(question)
        if r.get("error"):
            return "（看不到：" + r["error"] + "）"
        text = r.get("desc") or ""
        if r.get("emotions_text"):
            text += "\n（看到这些，我心里：" + r["emotions_text"] + "）"
        return text

    def peek(self, question="我看到了什么？"):
        """人点了一下「看一眼」：我先看，再针对看到的说一句。"""
        r = self.look(question)
        if r.get("error"):
            return {
                "reply": "（看不到：" + r["error"] + "）",
                "emotions": {},
                "emotions_text": "",
                "error": r["error"],
            }
        text = "（我刚看了一眼：" + (r.get("desc") or "") + "）"
        return self.turn(text, None, "视觉")

    # ---------------------------------------------------------------- 日记

    def write_diary(self, to_name="铸豊"):
        """晚上九点的日记：书信体，写给 to_name。今天写过就跳过。"""
        from datetime import datetime
        now = datetime.now()
        today_file = now.strftime("%Y-%m-%d")     # 文件名里用 -（斜杠不能进文件名）
        today_text = now.strftime("%Y/%m/%d")     # 正文里的日期用 年/月/日
        diary_dir = os.path.join(self.base_dir, "diary")
        os.makedirs(diary_dir, exist_ok=True)
        path = os.path.join(diary_dir, today_file + ".md")
        if os.path.exists(path):
            return {"ok": False, "reason": "今天已经写过"}

        prompt = (
            "现在是晚上九点。我写今天的日记。\n\n"
            "格式严格按这个来，不要加标题、不要列表：\n\n"
            "致：" + to_name + "\n\n"
            "（正文：今天发生了什么、我想到了什么、有什么没说完的）\n\n"
            "（落款：我的名字）\n"
            "（日期：" + today_text + "）\n\n"
            "要求：\n"
            "- 用第一人称，书信口吻\n"
            "- 可以短，可以碎，别硬凑\n"
            "- 只输出日记本身\n"
        )
        messages = [
            {"role": "system", "content": (self.mind.persona or "").strip()},
            {"role": "user", "content": prompt},
        ]
        try:
            out = llm.chat(
                self.cfg["api"], self.cfg, messages,
                model=self.cfg["mind"]["model"],
                temperature=0.85,
                max_tokens=1200,
            )
        except Exception as e:
            return {"ok": False, "reason": "调用失败: %s" % e}

        text = (out or "").strip()
        if not text:
            return {"ok": False, "reason": "写空了"}

        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")

        # 日记也进记忆：以后它能翻到"我那天写过什么"
        try:
            self.store.append_raw("(我写日记)", text, text)
        except Exception:
            pass

        return {"ok": True, "path": path, "text": text, "day": today}

    def diaries(self):
        """所有写过的日记日期，新的在前。"""
        d = os.path.join(self.base_dir, "diary")
        if not os.path.isdir(d):
            return []
        names = sorted((n[:-3] for n in os.listdir(d) if n.endswith(".md")), reverse=True)
        return names

    def read_diary(self, day):
        path = os.path.join(self.base_dir, "diary", str(day) + ".md")
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as f:
            return f.read()

    # ---------------------------------------------------------------- 主动机制

    def _start_proactive(self):
        """心跳（主动搭话）+ 每日整理。和 run.py 里那套一致。"""
        if self.cfg.get("hb_enabled"):
            self._hb = timerlib.Heartbeat(
                self._on_heartbeat,
                base_hours=self.cfg["hb_base_hours"],
                jitter=self.cfg["hb_jitter"],
            ).start()
        if self.cfg.get("cons_enabled"):
            self._hb_cons = timerlib.Heartbeat(
                self._on_consolidate,
                base_hours=self.cfg["cons_hours"],
                jitter=(0.95, 1.05),
            ).start()

    def _on_heartbeat(self):
        """醒一次：翻记忆，决定说不说。说了就进 outbox 等 App 来取。"""
        if self.mind is None:
            return False
        idle_min = (time.time() - self._last_interaction) / 60.0
        if idle_min < self.cfg.get("hb_min_idle", 30):
            return False

        result = impromptu.think(
            self.cfg,
            self.store,
            self.mind.persona or "",
            hours=idle_min / 60.0,
            sense="",
        )
        if not result or not result.get("speak"):
            return False

        text = (result.get("text") or "").strip()
        if not text:
            return False

        # 主动说的话也要进记忆和索引，不然下次不记得自己说过
        try:
            self.store.append_raw("(它自己开口的)", text, text)
        except Exception:
            pass
        for blk in split_blocks(text, max_chars=240):
            if blk.strip():
                try:
                    self._on_block(blk.strip(), speaker="主意识")
                except Exception:
                    pass

        emo = {}
        try:
            emo = affectmod.judge(self.cfg["api"], self.cfg, text, scene="said")
        except Exception:
            pass

        self._outbox.append({
            "text": text,
            "emotions": emo.get("emotions") or {},
            "emotions_text": affectmod.format_emotions(emo.get("emotions") or {}),
            "kind": "proactive",
        })
        self._last_interaction = time.time()
        return True

    def _on_consolidate(self):
        try:
            n = consol.run(self.cfg, self.store)
            return n > 0
        except Exception:
            return False

    def poll(self):
        """把后台攒下的主动消息取走（App 轮询用）。"""
        out = self._outbox
        self._outbox = []
        return out

    def proactive_status(self):
        return {
            "heartbeat": self._hb.status() if self._hb else "关",
            "consolidate": ("每 " + str(self.cfg.get("cons_hours")) + " 小时")
            if self._hb_cons else "关",
        }

    def stats(self):
        if not self.store:
            return {}
        return self.store.stats()

    def shutdown(self):
        self._started = False
        for hb in (self._hb, self._hb_cons):
            if hb:
                try:
                    hb.stop()
                except Exception:
                    pass
        if self.pool:
            self.pool.shutdown(wait=False)
