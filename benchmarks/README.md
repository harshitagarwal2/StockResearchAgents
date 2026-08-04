# Company analytics conformance benchmarks

These fixtures are small, synthetic oracle cases for deterministic analytics behavior. They were authored specifically for `tradingagents-portable`, are released under the repository's MIT license, and contain no market data, proprietary research, or copied benchmark records.

In particular, no fixture or expected result was copied or derived from QF-Bench, Seeking Alpha, vendor feeds, or any other proprietary or restricted dataset. Company names and prices are intentionally fictional.

| Fixture | Contract under test |
| --- | --- |
| `ohlcv_dirty.v1.json` | Host-adapter normalization policy for chronological, unique, internally consistent OHLCV bars |
| `point_in_time_restatement.v1.json` | Facts and amendments are visible only after their declared `available_at` time |
| `ratio_valuation.v1.json` | Decimal ratio and DCF calculators reproduce independently declared oracle values |
| `time_split.v1.json` | Financial time splits remain chronological, unshuffled, purged, and embargo-declared |
| `forecast_scoring.v1.json` | Resolved forecast outcomes produce deterministic kind-specific scorecards |

The OHLCV fixture is deliberately a pre-contract adapter oracle. Analytics v1 does not currently publish an OHLCV bar class or normalizer, so the test harness validates the minimum boundary policy a future host adapter must implement. It does not claim that production normalization already exists.

