"""测试用假模块：模块内部直接 sys.exit。"""
import sys


def run(ctx):
    sys.exit(3)
