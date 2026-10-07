---
id: source-checker
kind: agent-evidence
editable_by: code (backend/agent_evidence.py)
updated: 2026-10-07
sources: context/research/base_rates.json, context/research/backtests/2026-10-07-screens-v1-data-v2/summary.json
---

# Evidence for source-checker

## Source trust tiers (full list: context/data/sources.md)

- **Tier A, decides:** official or research-grade. SEC EDGAR filings, Kenneth French's data
  library, government statistics (FRED/ALFRED), peer-reviewed research.
- **Tier B, used and cross-checked:** reliable but unofficial or community-maintained. Yahoo
  Finance prices, the GitHub S&P 500 membership history, reputable press.
- **Tier C, suggests only:** Wikipedia, search results, headlines. Never enough on its own.

The house pattern: several sources suggest, the official one decides, and disagreements are
shown, not resolved by guessing.

## Known data hazards, and how the pipeline guards against them

Check any packet against these (counts from the latest backtest data build):
- **Scale typos in filings** (McDonald's tagged 732.3 shares for 2023, meaning millions):
  2,008 rows had a ratio blanked as a likely typo;
  1,825 market values used the cover-page share count instead.
- **Reused tickers** (BBT is now a different bank): prices are looked up by the company's
  ticker today, from its SEC ID, never by the old ticker.
- **A company ID that took over a ticker later** (IR was Gardner Denver until 2020):
  33 rows excluded.
- **Holding-company reorganizations** (Google to Alphabet): linked only when the new company's
  first annual report shows the old one's revenue, two years matching within 0.5%.
- **Unverified company IDs are excluded, never guessed**:
  4,079 rows.
- **Companies that no longer trade** have no free prices:
  11,146 rows. This survivorship gap is the
  biggest limit on every backtest number.
- **Restatements**: every financial number is the first-filed value, used only after its
  filing date.

Rules for quoting numbers: context/project/honesty-rules.md.
