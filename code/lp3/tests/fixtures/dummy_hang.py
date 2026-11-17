"""测试用假模块：卡住不返回。"""
import time


def run(ctx):
    time.sleep(120)
    return [], {}
