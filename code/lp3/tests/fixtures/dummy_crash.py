"""测试用假模块：上游字段变了，抛 KeyError（mvp3 主循环拦不住这类异常）。"""


def run(ctx):
    return {}['tvlUsdc'], {}
