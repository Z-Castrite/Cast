"""眼睛：拉一帧画面，让模型看一眼，返回它看到了什么。

数据流：
    摄像头 ──go2rtc──▶ JPEG ──视觉模型──▶ 一段文字 ──▶ 主意识/记忆

为什么要走文字：图片本身不能进记忆库（一张几百 KB，塞进去会把记忆撑爆），
而且真正有用的是"它看见了什么"，不是那堆像素。

**一个踩过的坑：**
deepseek-flash 是推理模型。看一张图，它内部要先想一千多字才开口。
max_tokens 给小了（比如 300），推理链吃光额度，content 返回空字符串——
看起来像"不支持图片"，其实只是没给它说话的余地。
这里固定给 2000。
"""

import base64
import json
import urllib.error
import urllib.request

DEFAULT_FRAME_URL = "http://127.0.0.1:1984/api/frame.jpeg?src=cam"


def grab_frame(url=DEFAULT_FRAME_URL, timeout=30):
    """从 go2rtc 抓一帧 JPEG。失败返回 None。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = r.read()
        return data if len(data) > 2048 else None
    except Exception as e:
        print(f"\n[眼睛看不到东西] {e}")
        return None


def look(api, cfg, image_bytes, question="我看到了什么？", max_tokens=2000):
    """让模型看一眼这张图。返回描述文字，失败返回 None。"""
    if not image_bytes:
        return None
    b64 = base64.b64encode(image_bytes).decode()
    body = {
        "model": cfg["mind"]["model"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url",
                 "image_url": {"url": "data:image/jpeg;base64," + b64}},
            ],
        }],
        "max_tokens": max_tokens,
    }
    base = api["base_url"].rstrip("/")
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api["api_key"]},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"\n[眼睛出错] HTTP {e.code}: {e.read().decode()[:200]}")
        return None
    except Exception as e:
        print(f"\n[眼睛出错] {e}")
        return None

    try:
        text = (out["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError):
        return None
    return text or None


def look_now(api, cfg, question="我看到了什么？"):
    """抓一帧 + 看一眼。一步到位。"""
    frame = grab_frame(cfg.get("eye_frame_url") or DEFAULT_FRAME_URL)
    if frame is None:
        return None, None
    return look(api, cfg, frame, question), frame
