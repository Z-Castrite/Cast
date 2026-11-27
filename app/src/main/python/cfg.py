"""配置的唯一入口。

之前配置是各模块各读各的，结果 test 时传了未拍平的原始 config，
筛选器拿不到 screener_model 直接崩——这种 bug 不该靠运气避免。
从现在起只有这一处知道 config.json 长什么样。
"""

import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_config(path=None):
    """读配置。App 里的 config 在 filesDir，所以允许指定路径。"""
    path = path or os.path.join(ROOT, "config.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    lang = raw.get("language") or {}
    emb = raw.get("embedding") or {}
    rk = raw.get("rerank") or {}
    return {
        "api": raw["api"],
        "mind": raw["mind"],
        "memory": raw["memory"],
        "loop": raw["loop"],
        # 拍平筛选器那一段，其他模块不用知道它是嵌套的
        "screener_model": raw["screener"]["model"],
        "screener_temperature": raw["screener"]["temperature"],
        "screener_max_tokens": raw["screener"]["max_tokens"],
        "threshold": raw["screener"]["importance_threshold"],
        # 情感判断：切分制情绪分布。独立一份模型，prompt 和索引器完全分开
        "affect_enabled": bool((raw.get("affect") or {}).get("enabled", False)),
        "affect_model": (raw.get("affect") or {}).get("model") or raw["screener"]["model"],
        "affect_temperature": (raw.get("affect") or {}).get("temperature", 0.2),
        "affect_max_tokens": (raw.get("affect") or {}).get("max_tokens", 300),
        # 语言板块：独立一份模型配置
        "language_enabled": bool(lang.get("enabled", False)),
        "language_model": lang.get("model") or raw["mind"]["model"],
        "language_temperature": lang.get("temperature", 0.3),
        "language_max_tokens": lang.get("max_tokens", 1024),
        # 向量检索：本地 Ollama（当前关闭，DeepSeek 没有 embedding 接口）
        "embedding": {
            "enabled": bool(emb.get("enabled", False)),
            "base_url": emb.get("base_url", "http://127.0.0.1:11434"),
            "model": emb.get("model", "nomic-embed-text"),
            "timeout": emb.get("timeout", 15),
        },
        # 检索重排：这才是"检索用模型"的 API 版实现
        "rerank_enabled": bool(rk.get("enabled", False)),
        "rerank_model": rk.get("model") or raw["screener"]["model"],
        "rerank_k": rk.get("k", 4),
        # 发声
        "voice_enabled": bool((raw.get("voice") or {}).get("enabled", False)),
        "voice_name": (raw.get("voice") or {}).get("voice", "zh-CN-YunjianNeural"),
        "voice_rate": (raw.get("voice") or {}).get("rate", "+0%"),
        "voice_volume": (raw.get("voice") or {}).get("volume", "+0%"),
        # 消息主动机制
        "hb_enabled": bool((raw.get("heartbeat") or {}).get("enabled", False)),
        "hb_base_hours": (raw.get("heartbeat") or {}).get("base_hours", 6),
        "hb_jitter": ((raw.get("heartbeat") or {}).get("jitter_low", 0.7),
                      (raw.get("heartbeat") or {}).get("jitter_high", 1.4)),
        "hb_min_idle": (raw.get("heartbeat") or {}).get("min_idle_minutes", 30),
        # 记忆整理
        "cons_enabled": bool((raw.get("consolidate") or {}).get("enabled", False)),
        "cons_hours": (raw.get("consolidate") or {}).get("every_hours", 24),
    }


def has_key(cfg):
    k = (cfg.get("api") or {}).get("api_key") or ""
    return bool(k.strip()) and "填" not in k


def load_persona(path=None):
    p = path or os.path.join(ROOT, "persona.txt")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    return "我是一个有记忆的对话者。说话直接，不绕弯子。"


def save_snapshot(cfg, persona):
    """启动快照。注意：key 绝不落盘——快照是给人看的，不是给贼看的。"""
    d = os.path.join(ROOT, "checkpoints")
    os.makedirs(d, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(d, f"persona-{ts}.txt"), "w", encoding="utf-8") as f:
        f.write(persona)
    safe = json.loads(json.dumps(cfg))
    if isinstance(safe.get("api"), dict):
        safe["api"]["api_key"] = "***"
    with open(os.path.join(d, f"config-{ts}.json"), "w", encoding="utf-8") as f:
        json.dump(safe, f, ensure_ascii=False, indent=1)
    return ts
