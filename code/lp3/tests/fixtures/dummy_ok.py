"""测试用假模块：正常产出两行。"""
VERSION = '9.9.9'


def run(ctx):
    rows = [{'protocol': 'Dummy', 'chain': 'Test', 'pool': 'p1', 'name': 'A / B', 'tvl': 1e6, 'vol24': 1e5, 'tokens': [['A', 'a'], ['B', 'b']],
             'asset_class': '代币', 'why_out': '', 'notes': '', 'apy_7d': 5.0},
            {'protocol': 'Dummy', 'chain': 'Test', 'pool': 'p2', 'name': 'C / D', 'tvl': 6e5, 'vol24': 0, 'tokens': [['C', 'c'], ['D', 'd']],
             'asset_class': '股票和商品', 'why_out': '部署 3 天', 'notes': ''}]
    return rows, {'n_raw': 2, 'archive': [{'pool': 'm1', 'tvl': 10.0, 'vol24': 5.0, 'meme_label': 'meme'}]}
