"""主动机制：每六个小时左右，自己醒一次。

间隔不是精确的六小时——是 6 小时 × 随机(0.7~1.4)，
所以可能是四小时多，也可能是八小时多。

"无保底"的意思是：醒了不等于要说话。
醒过来只是给了一次机会，说不说由它自己判断。
它可以说，也可以什么都不说，继续睡。
"""

import random
import threading
import time
from datetime import datetime


def next_wait(base_hours=6.0, jitter=(0.7, 1.4)):
    """下一次醒来的间隔秒数。"""
    return base_hours * 3600.0 * random.uniform(*jitter)


class Heartbeat:
    """后台计时器。到点就调 callback；callback 自己决定要不要说话。"""

    def __init__(self, callback, base_hours=6.0, jitter=(0.7, 1.4)):
        self.callback = callback
        self.base_hours = base_hours
        self.jitter = jitter
        self._stop = threading.Event()
        self._thread = None
        self.next_at = None          # 下一次醒来的时间戳
        self.triggered = 0           # 一共醒了几次
        self.spoke = 0               # 其中开口了几次

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            wait = next_wait(self.base_hours, self.jitter)
            self.next_at = time.time() + wait
            # 用 Event.wait 而不是 sleep：退出时能立刻停，不用等完
            if self._stop.wait(wait):
                return
            self.triggered += 1
            try:
                if self.callback():
                    self.spoke += 1
            except Exception as e:
                print(f"\n[主动机制出错] {e}")

    def stop(self):
        self._stop.set()

    def status(self):
        if not self.next_at:
            return "未启动"
        left = max(0, self.next_at - time.time())
        h = int(left // 3600)
        m = int((left % 3600) // 60)
        return f"下一次 {h} 小时 {m} 分后（醒了 {self.triggered} 次，开口 {self.spoke} 次）"
