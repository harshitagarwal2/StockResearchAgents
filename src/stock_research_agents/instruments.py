"""Production symbol normalization shared by every StockResearchAgents entry point."""

from __future__ import annotations

_ALIASES = {"XAUUSD": "GC=F", "SPX500": "^GSPC", "US500": "^GSPC"}
_CRYPTO_QUOTES = ("USD", "USDT", "USDC")
_CRYPTO_BASES = frozenset({"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB"})
_CURRENCIES = frozenset({"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY", "INR"})


def normalize_instrument_symbol(raw: str) -> str:
    """Normalize common aliases without provider access or harness coupling."""
    if not isinstance(raw, str):
        raise TypeError("symbol must be a string")
    symbol = raw.strip().upper().rstrip("+")
    if not symbol:
        raise ValueError("symbol must be non-empty")
    if symbol in _ALIASES:
        return _ALIASES[symbol]
    compact = symbol.replace("-", "")
    for quote in _CRYPTO_QUOTES:
        base = compact[: -len(quote)] if compact.endswith(quote) else ""
        if base in _CRYPTO_BASES:
            return f"{base}-USD"
    if len(symbol) == 6 and symbol[:3] in _CURRENCIES and symbol[3:] in _CURRENCIES:
        return f"{symbol}=X"
    return symbol
