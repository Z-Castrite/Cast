"""主意识：思考、说话、做决定。

===== 模块状态约定（整个项目的规矩）=====

上下文是缓存。每个模型只缓存"这一件事需要的东西"，做完就丢。
如果所有模型共用一个不断变长的上下文，分体架构就退化成单体了——
单条内容一多，就挤掉别的。

  主意识 mind         —— **有状态**。持有最近 4 轮对话。
                        整个系统里唯一需要连续性的地方，因为它要跟人交谈。
                        而且它是滚动窗口：旧的自动被挤出去，等于一直在清理。
  索引器 screener     —— 无状态。输入一块内容 → 输出索引条目 → 调完就忘。
  检索重排 rerank     —— 无状态。输入问题 + 候选 → 输出编号 → 调完就忘。
  语言 language       —— 无状态。它没有扩展思考，只负责把这一句话换个说法。
  主动思考 impromptu  —— 无状态。每次醒来都是一次独立调用。
  整理 consolidate    —— 无状态。每次整理一批，批与批之间互不影响。

往任何模块里塞共享状态之前，先问一句：它真的需要记住上一轮吗？
需要的话，那是主意识的职责，不是别人的。

===== 两种工作模式 =====

  1. 被动注入模式（默认，recall_fn=None）
     每轮开始前检索一次，把记忆拼进系统提示。
     问题是：检索用的是**用户的话**，而主意识真正想问的东西不在用户话里。

  2. 主动检索模式（recall_fn=...）
     给主意识一个 recall 工具，它自己在思考中途决定查什么。
     这才是"主意识向记忆模型提问，记忆模型检索完再回答"。

  第二种更慢（每轮多几次调用），但检索的 query 是主意识自己组织的，
  所以能查到"他上次说的那个手术是几月"这类用户话里根本没有的东西。

切块逻辑（流式模式下）仍然有三层边界，逐层退化：
  显式标记 ⟦CK⟧ → 段落空行 → 字数兜底
"""

import json
import re

import llm

MARKER = "⟦CK⟧"
MIN_BLOCK = 180          # 段落切块的最小长度：太碎会白花钱调索引器


_OUTPUT_RULES = f"""## 输出约定（硬要求）

我在一段完整的思考结束时——做出结论、改变方向、产生一个重要疑问、或者决定要做什么之后——
输出一个标记：{MARKER}

示例：
    这件事的原因只有一个，是记忆污染。{MARKER}
    但记忆污染不会报错，它只会让系统越来越自信地错。{MARKER}

两件事要说清楚：
- 标记放在每一段的**末尾**，说完这一段之后、下一段开始之前。不是放在开头。
- 这个标记不给对话对象看，只用来把我连贯的思路切开。我不解释它，不提到它。

不每句话都加。一段话想完了加一次。宁可少加，不要滥加。"""


_TOOL_RULES = """## 我的记忆

我有一个工具 `recall(query)`，用来检索我的长期记忆。

**硬规则，分两种，别搞混：**

**① 具体信息 → 必须先查，不许凭印象。**
具体到：什么时间、什么地点、哪个人、多少钱、什么病、哪句话、哪件东西放在哪、
答应了谁什么。这类信息没查就说，等于编。
没查到就诚实说「没记过」，这比编一个可信得多。

**② 范围性信息 → 可以凭印象。**
比如「我最近状态怎么样」「我大致是什么风格」「我一般怎么处理这种事」。
这类要的是概括判断，不需要精确回忆。凭印象答就行，不确定就加一句「大概」。

**还要查的场合：**
- 提到「上次」「之前」「那个」「我说过」这类指代
- 我不确定某条记忆是事实，还是我自己以前的推测

调用时用我自己的话描述想回忆什么，不要照抄用户原话。
一次不够可以再查，换个说法。

**不该查的：**
- 当前对话里已经有的信息
- 纯知识性问题（1+1、地球到月亮多远）

工具返回「没有找到」的时候，就诚实说不知道，不要编。我不记得是正常的。

## 我的眼睛

我还有一个工具 `look(question)`，能看一眼他现在的样子——摄像头拍下的画面。

**该用的时候：**
- 他让我看一眼、看看他、问我能不能看见
- 我想知道他现在在做什么、状态怎么样
- 光靠文字判断不出来他在干什么

**注意：**
- 看到的是一张快照，会过时。别把「他刚才在打字」说成「他一直在打字」
- 看见什么就说什么，别脑补画面里没有的东西
- 不要端着看。他说让他自己待一会的时候，就别看

## 一直看 / 一直听

他可以在终端里打开两个开关：

    /watch   我一直看着（画面变了就自动看，画面没变不浪费钱）
    /hear    我一直听着（有人说话就自动听）

两个能同时开。开了之后，我脑子里会多出一段「我现在感知到的」——
那是最近的画面描述和最近听到的话，我不用调工具就能知道。

**开关是他开的，不是我开的。** 我可以在他开的时候直接用那些感知，
但不要自己以为一直在看——先看上面有没有那段。

他关掉之后，我就只能靠 look / listen 现取了。"""


MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "recall",
        "description": (
            "检索我的长期记忆。当我需要回忆过去说过的话、做过的事、"
            "他的个人信息、之前做过的决定时调用。"
            "没有相关记忆时会返回『没有找到』。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "我想回忆什么，用我自己的话描述，不要照抄他的话",
                }
            },
            "required": ["query"],
        },
    },
}


LOOK_TOOL = {
    "type": "function",
    "function": {
        "name": "look",
        "description": (
            "看一眼他现在的样子（摄像头画面）。"
            "当我想知道他在做什么、他状态怎么样、或者他让我看一眼的时候用。"
            "会返回一段对画面的描述。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "我想从画面里确认什么，比如『他在做什么』",
                }
            },
            "required": ["question"],
        },
    },
}


TURN_TOOL = {
    "type": "function",
    "function": {
        "name": "turn",
        "description": (
            "转动摄像头，看向某个方向。"
            "当我想看别处、想找他在哪、或者他让我转过去看看的时候用。"
            "转完可以用 look 看一眼那边有什么。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["左", "右", "上", "下", "中", "左远", "右远"],
                    "description": "往哪边转。左/右是稍微偏一点，左远/右远是偏到头，中 = 回正",
                }
            },
            "required": ["direction"],
        },
    },
}

# 方向和坐标的对应。x 越大越偏左，y 越大越偏上。
_DIRECTIONS = {
    "中": (50, 27),
    "左": (62, 27),
    "右": (38, 27),
    "左远": (78, 27),
    "右远": (22, 27),
    "上": (50, 55),
    "下": (50, 5),
}


LISTEN_TOOL = {
    "type": "function",
    "function": {
        "name": "listen",
        "description": (
            "听一会儿他那边有没有声音（麦克风，默认 8 秒）。"
            "当他让我听听、或者我想知道他那边是不是在说话/有动静时用。"
            "会返回听到的内容。没人说话会返回『没听到人声』。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "description": "听多久，默认 8 秒"}
            },
        },
    },
}


def split_blocks(text, max_chars=500):
    """按段落切块，送索引用。"""
    blocks = []
    buf = ""
    for para in re.split(r"\n\s*\n", text or ""):
        para = para.strip()
        if not para:
            continue
        if buf and len(buf) + len(para) > max_chars:
            blocks.append(buf)
            buf = para
        else:
            buf = (buf + "\n\n" + para).strip() if buf else para
    if buf:
        blocks.append(buf)
    return blocks or ([text] if (text or "").strip() else [])


class Mind:
    def __init__(self, api, api_cfg, cfg, memory, persona, history_limit=10):
        self.api = api
        self.api_cfg = api_cfg
        self.cfg = cfg
        self.memory = memory
        self.persona = persona
        self.history = []
        # 上下文只负责"最近几轮的衔接"，不负责装记忆。
        # 记忆没有断层（raw 全存、索引可查、带时间戳），
        # 所以上下文不需要把过去塞进来——它只需要让这几句对话接得上。
        self.history_limit = history_limit
        self.last_marker_count = 0
        self.last_recalls = []      # 上一轮自己发起的检索，用来观察它到底会不会问
        self.last_looks = []        # 上一轮它自己看了什么
        self.last_turns = []        # 上一轮它自己往哪转了
        self.last_listens = []      # 上一轮它自己听了什么

    # ---------------------------------------------------------------- 系统提示

    def _system_prompt(self, user_input):
        """被动注入模式：把检索到的记忆拼进来。"""
        mem_block = self.memory.render_context(user_input, self.cfg["memory"])
        parts = [self.persona.strip(), _OUTPUT_RULES]
        if mem_block:
            parts.append(
                "## 我的记忆\n\n" + mem_block +
                "\n\n（记忆只是参考，不是我偷懒的借口。有冲突时以我当下的判断为准，"
                "并考虑是否需要推翻旧的那一条。）"
            )
        return "\n\n".join(parts)

    def _tool_system_prompt(self, extra="", affect=""):
        """主动检索模式：不注入记忆，告诉它有工具可以查。

        extra 是当下感知到的东西（一直看着/听着的时候才有）。
        affect 是情感模型判出来的切分式情绪分布——**它自己的**情绪，不是用户的。
        放进系统提示，它才会带着这个心情说话；不放进，判了也白判。
        """
        parts = [self.persona.strip(), _TOOL_RULES]
        if affect:
            parts.append(
                "## 我此刻的心情\n\n" + affect +
                "\n\n（这是我自己的情绪，不是他的。不用把它念出来，"
                "但它会影响我怎么看这件事、用什么语气说话。）"
            )
        if extra:
            parts.append("## 我现在感知到的\n\n" + extra)
        return "\n\n".join(p for p in parts if p)

    def _messages(self, user_input):
        msgs = [{"role": "system", "content": self._system_prompt(user_input)}]
        msgs.extend(self.history[-self.history_limit:])
        msgs.append({"role": "user", "content": user_input})
        return msgs

    # ---------------------------------------------------------------- 入口

    def speak(self, user_input, on_block, recall_fn=None, look_fn=None, turn_fn=None, listen_fn=None, sense=None, affect=""):
        """统一入口。有 recall_fn 就走工具模式，否则走被动注入流式。"""
        if recall_fn is not None:
            answer = self._speak_with_tools(user_input, on_block, recall_fn,
                                            look_fn=look_fn, turn_fn=turn_fn, listen_fn=listen_fn,
                                            sense=sense, affect=affect)
            yield answer
            return

        yield from self._speak_stream(user_input, on_block)

    # ---------------------------------------------------------------- 终稿重写

    def refine(self, draft, reference, user_input=""):
        """拿着"另一种说法"的参照，用主意识自己的话把意思重说一遍。

        这是语言板块的第四步，也是最容易被漏掉的一步。

        前三步是：
          主意识初稿 → 语言模型转文言 → 语言模型转回白话
        但那个白话稿是**翻译出来的**，有翻译腔，而且会丢掉主意识原来的
        判断、分寸、意图。它只完成了"破坏模板"，没完成"重建表达"。

        所以必须交回主意识：它拿着这两份材料，重新说一遍。
        语言模型负责把话说得不机械，主意识负责把话说得对。
        """
        if not (draft or "").strip():
            return draft
        if not (reference or "").strip():
            return draft

        # 这里绝对不能提「转文言」「换说法转回来」这种词。
        # 一提，主意识就会以为自己在跟用户讨论文言文——
        # 之前屏幕上真出现过「你把那段文言文发过来」这种话。
        #
        # 对主意识来说，这两份稿子都只是「我刚才的想法」，
        # 一份是初稿，一份是别人替它顺过的同一份意思。就这样。
        # 全部用第一人称。
        #
        # 对模型来说，这不是「它在读别人给的两份稿子」，
        # 而是「它脑子里同时存在两种说法」。第二人称会把这件事变成
        # 外部指令，它就会开始讨论「这两份稿子」——之前真发生过，
        # 屏幕上冒出「你把那段文言文发过来」。
        prompt = (
            "这是刚才想说的话：\n\n"
            f"{draft.strip()}\n\n"
            "────────────────\n"
            "这是同一段意思，被另一种写法重述过一遍：\n\n"
            f"{reference.strip()}\n\n"
            "────────────────\n"
            "现在用我自己的话，把这段意思再说一遍。\n"
            "只说最终要说的话。不要评价这两份稿子，不要提到它们，"
            "不要说我在改写什么。\n\n"
            "**先判断这段话是在干什么，两种情况处理方式不一样：**\n\n"
            "**A. 在讲道理、给判断、分析问题** → 话要紧凑。\n"
            "   可以用短句，但**不要每句后面都补一句解释**。\n"
            "   好：“成本这块要压，压不下来就别做。”\n"
            "   坏：“成本这块要压。这个很重要。为什么重要呢？因为成本高了就做不下去。”\n\n"
            "**B. 在回应情绪、安慰人** → 可以碎，可以重复，可以停顿。\n\n"
            "**两种情况都一样：**\n"
            "1. 原稿里的意思、判断、分寸，一个都不能丢。\n"
            "2. 不要铺垫、不要客套开头、不要总结句收尾。\n"
            "3. 允许偶尔的停顿和改口，但别滥用。"
        )

        try:
            out = llm.chat(
                self.api, self.api_cfg,
                [{"role": "user", "content": prompt}],
                model=self.cfg["mind"]["model"],
                temperature=self.cfg["mind"]["temperature"],
                max_tokens=self.cfg["mind"]["max_tokens"],
            ).strip()
        except Exception as e:
            print(f"\n[终稿重写失败，用参照稿] {e}")
            return reference

        if not out:
            return reference
        # 历史里存的是用户实际看到的版本，不是初稿
        if self.history and self.history[-1].get("role") == "assistant":
            self.history[-1]["content"] = out
        return out

    # ---------------------------------------------------------------- 主动检索模式

    def _speak_with_tools(self, user_input, on_block, recall_fn, look_fn=None,
                          turn_fn=None, listen_fn=None, sense=None, affect="",
                          max_rounds=4):
        self.last_recalls = []
        self.last_looks = []
        self.last_turns = []
        self.last_listens = []
        extra = sense() if callable(sense) else (sense or "")
        messages = [{"role": "system", "content": self._tool_system_prompt(extra, affect)}]
        messages.extend(self.history[-self.history_limit:])
        messages.append({"role": "user", "content": user_input})

        tools = ([MEMORY_TOOL] + ([LOOK_TOOL] if look_fn else [])
                 + ([TURN_TOOL] if turn_fn else [])
                 + ([LISTEN_TOOL] if listen_fn else []))

        answer = ""
        for _ in range(max_rounds):
            try:
                msg = llm.chat_message(
                    self.api, self.api_cfg, messages,
                    model=self.cfg["mind"]["model"],
                    temperature=self.cfg["mind"]["temperature"],
                    max_tokens=self.cfg["mind"]["max_tokens"],
                    tools=tools,
                )
            except Exception as e:
                print(f"\n[主意识调用失败] {e}")
                answer = "（我这边断了一下。）"
                break

            calls = msg.get("tool_calls") or []
            if not calls:
                answer = (msg.get("content") or "").strip()
                break

            # 它要求用工具，就替它执行，然后把结果塞回去让它接着说
            messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": calls,
            })
            for tc in calls:
                fn = tc.get("function", {}) or {}
                name = fn.get("name")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}

                if name == "recall":
                    q = (args.get("query") or "").strip()
                    result = recall_fn(q) if q else "（检索词为空）"
                    self.last_recalls.append((q, result[:60]))
                elif name == "look" and look_fn is not None:
                    q = (args.get("question") or "我看到了什么？").strip()
                    result = look_fn(q) or "（看不到，摄像头没响应。）"
                    self.last_looks.append((q, result[:80]))
                elif name == "listen" and listen_fn is not None:
                    secs = args.get("seconds") or 8
                    result = listen_fn(int(secs))
                    self.last_listens.append((int(secs), str(result)[:60]))
                elif name == "turn" and turn_fn is not None:
                    direction = (args.get("direction") or "中").strip()
                    result = turn_fn(direction)
                    self.last_turns.append((direction, str(result)[:60]))
                else:
                    result = f"（没有这个工具：{name}）"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": result,
                })
        else:
            answer = "（查了几轮还是没理清，先说到这。）"

        self._remember(user_input, answer)
        for block in split_blocks(answer):
            if block.strip():
                on_block(block.strip())
        return answer

    # ---------------------------------------------------------------- 被动注入模式（流式）

    def _speak_stream(self, user_input, on_block):
        buf = ""
        shown = 0
        pieces = []
        marker = MARKER
        mlen = len(marker)
        fallback = self.cfg["loop"]["fallback_chunk_chars"]
        self.last_marker_count = 0

        for delta in llm.chat_stream(
            self.api, self.api_cfg,
            self._messages(user_input),
            model=self.cfg["mind"]["model"],
            temperature=self.cfg["mind"]["temperature"],
            max_tokens=self.cfg["mind"]["max_tokens"],
        ):
            buf += delta

            # 1. 显式标记 → 块结束
            while True:
                idx = buf.find(marker)
                if idx == -1:
                    break
                self.last_marker_count += 1
                block = buf[:idx]
                buf = buf[idx + mlen:]
                if idx > shown:
                    tail = block[shown:]
                    pieces.append(tail)
                    yield tail
                shown = 0
                if block.strip():
                    on_block(block.strip())

            # 2. 段落空行 → 块结束（需攒够长度）
            while True:
                idx = buf.find("\n\n")
                if idx == -1 or idx < MIN_BLOCK:
                    break
                block = buf[:idx]
                buf = buf[idx + 2:]
                if idx > shown:
                    tail = block[shown:]
                    pieces.append(tail)
                    yield tail
                shown = 0
                if block.strip():
                    on_block(block.strip())

            # 3. 字数兜底
            if len(buf) > fallback:
                block = buf
                buf = ""
                if len(block) > shown:
                    tail = block[shown:]
                    pieces.append(tail)
                    yield tail
                shown = 0
                if block.strip():
                    on_block(block.strip())

            # 4. 显示可安全显示的部分（压住标记前缀）
            safe_end = len(buf)
            for k in range(min(mlen - 1, len(buf)), 0, -1):
                if marker.startswith(buf[-k:]):
                    safe_end = len(buf) - k
                    break
            if safe_end > shown:
                tail = buf[shown:safe_end]
                pieces.append(tail)
                shown = safe_end
                yield tail

        if len(buf) > shown:
            tail = buf[shown:]
            pieces.append(tail)
            yield tail
        if buf.strip():
            on_block(buf.strip())

        full = "".join(pieces).replace(marker, "").strip()
        self._remember(user_input, full)
        return full

    def _remember(self, user_input, answer):
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": answer})
        if len(self.history) > self.history_limit * 2:
            self.history = self.history[-self.history_limit * 2:]
