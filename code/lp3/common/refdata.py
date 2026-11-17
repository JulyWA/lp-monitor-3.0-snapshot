"""lp3 共享参考数据：股票名单、Solana 代币标签缓存。只读本地文件，运行时不调用 CoinGecko。

路径与 mvp3/collect.py 相同（stage0/out 下的快照），可用环境变量覆盖。
每次读取都返回文件指纹（路径、修改时间、sha256 前 12 位），写进模块输出，便于追溯当天用的是哪一版名单。
"""
import datetime
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STOCKLIST = os.environ.get('LP3_STOCKLIST', os.path.join(ROOT, 'mvp3', 'stage0', 'out', 'stocklist-raw-2026-11-11.json'))
SOL_LABELS = os.environ.get('LP3_SOL_LABELS', os.path.join(ROOT, 'mvp3', 'stage0', 'out', 'sol-token-labels.json'))
SGT = datetime.timezone(datetime.timedelta(hours=8))


def fingerprint(path):
    if not os.path.exists(path):
        return {'path': path, 'exists': False}
    with open(path, 'rb') as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()[:12]
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path), SGT).isoformat(timespec='seconds')
    return {'path': os.path.relpath(path, ROOT), 'exists': True, 'mtime': mtime, 'sha256_12': digest}


def stock_index(path=None):
    """与 mvp3/collect.py 的 stock_index() 相同：{合约地址（0x 小写）: CoinGecko id}。"""
    s = json.load(open(path or STOCKLIST))
    idx = {}
    for i in set(x for v in s['members'].values() for x, _, _ in v):
        for chain, a in s['platforms'].get(i, {}).items():
            if a:
                idx[a.lower() if a.startswith('0x') else a] = i
    return idx


def sol_labels(path=None):
    """与 mvp3/collect.py 的 sol_labels() 相同：文件不存在时返回空字典。"""
    p = path or SOL_LABELS
    return json.load(open(p)) if os.path.exists(p) else {}
