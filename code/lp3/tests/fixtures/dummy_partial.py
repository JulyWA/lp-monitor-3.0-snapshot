"""测试用假模块：部分接口失败。"""
from lp3.tests.fixtures.dummy_ok import run as _run


def run(ctx):
    rows, meta = _run(ctx)
    meta['errors'] = ['第 3 页 429']
    return rows, meta
