"""常驻能力：定时触发 / 事件触发 / 崩溃续跑 / 完成通知。

刻意保持包 __init__ 为空 —— loop.py 要 import checkpoint，这里再 import loop 就成环了。
"""
