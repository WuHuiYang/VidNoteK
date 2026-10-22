"""Restore letters Douyin burns in place of sensitive finance words.

Captions often keep the pinyin initial and hide one character: 爆C is 爆仓,
L润 is 利润, N市 is 牛市. Replacements are whole tokens with a word boundary
around the Latin letter, so strings such as A股, CEO, and C位 are left alone.
The table is conservative and can be extended or turned off.
"""

from __future__ import annotations

import re

# Masked form -> restored form. One ASCII letter, the rest Chinese.
_DEFAULT_PAIRS: tuple[tuple[str, str], ...] = (
    # 仓
    ("爆C", "爆仓"),
    ("建C", "建仓"),
    ("平C", "平仓"),
    ("补C", "补仓"),
    ("加C", "加仓"),
    ("减C", "减仓"),
    ("持C", "持仓"),
    ("空C", "空仓"),
    ("满C", "满仓"),
    ("重C", "重仓"),
    ("轻C", "轻仓"),
    ("清C", "清仓"),
    ("开C", "开仓"),
    ("斩C", "斩仓"),
    # 利
    ("L润", "利润"),
    ("盈L", "盈利"),
    ("L率", "利率"),
    ("L息", "利息"),
    ("L好", "利好"),
    ("L空", "利空"),
    ("红L", "红利"),
    ("毛L", "毛利"),
    ("净L", "净利"),
    ("复L", "复利"),
    ("套L", "套利"),
    ("暴L", "暴利"),
    ("薄L", "薄利"),
    # 抄 / 牛 / 熊
    ("C底", "抄底"),
    ("N市", "牛市"),
    ("N股", "牛股"),
    ("X市", "熊市"),
    # 亏 / 损. Q亏 is the usual mask for 全亏 (全 quan).
    ("Q亏", "全亏"),
    ("K损", "亏损"),
    ("亏S", "亏损"),
    ("浮K", "浮亏"),
    ("止S", "止损"),
    ("S失", "损失"),
    # 套 / 割 / 股 / 停
    ("T牢", "套牢"),
    ("被T", "被套"),
    ("解T", "解套"),
    ("G肉", "割肉"),
    ("G票", "股票"),
    ("G价", "股价"),
    ("G市", "股市"),
    ("G东", "股东"),
    ("G民", "股民"),
    ("G杆", "杠杆"),
    ("Z停", "涨停"),
    ("D停", "跌停"),
    ("打B", "打板"),
    ("Z家", "庄家"),
    ("J菜", "韭菜"),
    ("S户", "散户"),
)


def parse_unmask_extra(raw: str) -> dict[str, str]:
    """Parse ``爆C=爆仓,L润=利润`` into a dictionary. Blank input is empty."""
    pairs: dict[str, str] = {}
    if not raw:
        return pairs
    for part in re.split(r"[,;\n]", raw):
        piece = part.strip()
        if not piece or "=" not in piece:
            continue
        src, dst = piece.split("=", 1)
        src, dst = src.strip(), dst.strip()
        if src and dst:
            pairs[src] = dst
    return pairs


def restore_masked_terms(text: str, extra: dict[str, str] | None = None) -> str:
    """Replace known masked finance tokens. ``extra`` overrides the defaults."""
    if not text:
        return text
    rules = dict(_DEFAULT_PAIRS)
    if extra:
        rules.update(extra)
    for src, dst in sorted(rules.items(), key=lambda item: len(item[0]), reverse=True):
        text = _replace_token(text, src, dst)
    return text


def _replace_token(text: str, src: str, dst: str) -> str:
    if not any(ch.isascii() and ch.isalpha() for ch in src):
        return text.replace(src, dst)
    body = "".join(
        ch if ch.isascii() and ch.isalpha() else re.escape(ch)
        for ch in src
    )
    pattern = rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"
    return re.sub(pattern, dst, text, flags=re.IGNORECASE)
