"""M2 探针：只证明 Python 在手机里跑起来了。

真正的引擎从下一步开始搬，先确认运行时、版本、调用链这三样没问题。
"""

import sys


def greet():
    return "python " + sys.version.split()[0] + " @ " + sys.platform
