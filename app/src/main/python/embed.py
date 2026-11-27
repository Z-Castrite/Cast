"""本地 embedding 客户端（走 Ollama，零成本）。

为什么要它：检索靠字符二元组，本质是"字面上有同样的字才能找到"。
你问"我那条伤"，它搜不到"肌肉空洞"——因为一个字都不一样。
词向量知道这两个意思是近的，字符不知道。

所以：写入时把条目编码成向量存下来，读取时把 query 编码成向量，
比余弦相似度。这一步是真正的语义检索，不是字面匹配。

全部本地跑，不走 API，不花钱，不联网。
"""

import json
import urllib.error
import urllib.request


def _post(url, payload, timeout=15):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def embed(text, base_url, model, timeout=15):
    """返回向量（list[float]）。失败抛异常，由调用方决定回退。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("空文本没有向量")

    base = base_url.rstrip("/")

    # 新接口 /api/embed（Ollama 0.2+）
    try:
        body = _post(f"{base}/api/embed",
                     {"model": model, "input": text}, timeout)
        vecs = body.get("embeddings") or []
        if vecs and vecs[0]:
            return vecs[0]
    except urllib.error.HTTPError:
        pass   # 接口不存在，走旧的
    except (urllib.error.URLError, OSError, ValueError):
        raise

    # 旧接口 /api/embeddings
    body = _post(f"{base}/api/embeddings",
                 {"model": model, "prompt": text}, timeout)
    vec = body.get("embedding")
    if not vec:
        raise RuntimeError("embedding 返回为空")
    return vec


def cosine(a, b):
    """余弦相似度。纯 Python，不引依赖。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))
