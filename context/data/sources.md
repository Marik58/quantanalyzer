# Data sources: what we use, how far to trust it, and what's missing

As of 2026-10-07. **Trust tiers:**
- **A:** official or research-grade; used as the decider
- **B:** reliable, but unofficial or community-maintained; used, then cross-checked
- **C:** suggests candidates only; never used on its own

Facts about other providers are marked with how they were checked.

## In use

| Source | What we take | Tier | License / terms | Known problems |
|---|---|---|---|---|
| **SEC EDGAR**: company facts, submissions, full-text search, ticker list (`backend/edgar.py`) | Annual financials, as first filed; company IDs, names, filing dates | A | US government data, free. Requests must name a contact (kept in `.env`) | Machine-readable history starts around 2009–2011. Some filings mis-scale numbers (McDonald's tagged 732.3 shares for 2023, meaning 732.3 million). Labels change over time (General Mills' revenue was `SalesRevenueGoodsNet` until 2018). Holding-company reorganizations split a company's history across two IDs (Disney 2019, Exxon, BlackRock). Banks don't report a standard revenue line |
| **S&P 500 membership history**, [github.com/fja05680/sp500](https://github.com/fja05680/sp500) | Who was in the index on each date, back to 1996 | B | MIT | Community-maintained; cross-checked against Wikipedia and the SEC in the ticker-to-company map |
| **Wikipedia** S&P 500 lists ([current](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies), [changes](https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500)) | Company names and IDs, as a second source for the ticker map | C | CC BY-SA | Editable by anyone; used only to suggest a match the SEC then confirms |
| **Yahoo Finance** via `yfinance` | Daily prices (split-adjusted and total-return), split history | B | Unofficial access; Yahoo's terms don't allow republishing the data | **No delisted stocks.** History follows renames (FB is under META). Adjusted prices are imperfect around spinoffs |
| **Kenneth French Data Library** (Dartmouth) | Fama-French 5 factors plus momentum, daily | A | Free for research | Published with about a two-month lag |
| Yahoo RSS headlines | News card and archive | C | Unofficial | Short history (archived daily since 2026-10) |

**How the sources are combined:** several sources suggest an answer, and the official one
decides. Disagreements are flagged, not resolved by guessing. The ticker-to-company map
(`backend/cik_map.py`) is the working example.

## The biggest gap: prices for delisted companies

About 12% of S&P 500 member-months since 2011 belong to companies that no longer trade
(bought out or failed). Yahoo has no prices for them. In 2011 it's about a quarter of the
index; by 2025 it's under 2%. Free data can't close this gap. Options checked on
2026-10-07:

| Option | What it offers | Cost | Checked how |
|---|---|---|---|
| **WRDS (CRSP and Compustat)** through Temple | The research standard: every US stock, delisting returns included | **Temple subscribes.** The Fox School lists CRSP, Compustat, IBES and Fama-French factors through WRDS: "create an account and select Temple University as your affiliated institution"; questions go to the Fox research office (contact on that page). Whether undergraduates qualify isn't stated; elsewhere they often use a professor's **class account** | [Fox research resources](https://www3.fox.temple.edu/discover/research-at-fox/resources/), read directly; [WRDS class accounts](https://wrds-www.wharton.upenn.edu/pages/about/wrds-account-types/student-guide-enrolling-in-a-class-account/) (search summary) |
| **Norgate Data**, Platinum | US prices back to 1990, **delisted securities and historical index constituents included** | $630/year (Diamond, back to 1950: $787.50; Silver and Gold exclude delisted) | [Norgate packages page](https://norgatedata.com/stockmarketpackages.php), read directly |
| **Tiingo** | 30+ years of price history; delisted tickers included when covered and the ticker hasn't been reused (search summary, unverified) | Free: 500 symbols a month, 50 requests an hour, 1,000 a day, **internal use only** ("you may not display or share the data with another person or organization"). Power: $30/month | [Tiingo pricing](https://www.tiingo.com/about/pricing), read directly |
| **EODHD** | "26,000+ US stock tickers (mostly from Jan 2000)" of delisted data; "Delisted tickers are available in any of our packages" | Historian (end-of-day prices, 30+ years): $19.99/month or $199/year; Equity Analyst (adds fundamentals): $59.99/month. **Students: 50% off for 12 months.** Free plan: 20 calls a day | [EODHD pricing](https://eodhd.com/pricing) and [delisted FAQ](https://eodhd.com/financial-academy/financial-faq/historical-stock-prices-for-delisted-companies), read directly |
| **Sharadar** (Nasdaq Data Link) | Active and delisted US stocks; prices from 1998, fundamentals from 1990 | Behind a login | [QuantRocket's Sharadar page](https://www.quantrocket.com/pricing/data/sharadar/), read directly |
| **FactSet** | Professional-grade everything | Through the school, if available. A FactSet connector exists for this AI assistant but isn't authorized yet | Not checked |

**If money goes to one place (recommendation, 2026-10-07):**
1. **First, free:** ask for WRDS through Temple (CRSP has every US stock's prices, with
   delisting returns).
2. **If that fails, EODHD Historian** with the student discount (about $100 for the first
   year). It closes the biggest gap, prices for companies that no longer trade, at the
   lowest cost.
3. **Norgate Platinum** ($630/year) is the step up: cleaner, research-grade data that also
   includes historical index membership.

Test any paid source on a month's subscription first. Check that it has the 11,146 missing
member-months (for example Pepsi Bottling, Burlington Northern) before paying for a year.

**Licensing matters for a public app.** Most of these allow personal or internal research
but not showing their raw data to other people. Backtest *results* (summary statistics)
are generally fine to publish; raw prices on a public page may not be. Check each license
before anything reaches users.

## Planned (from the charters)

- **ALFRED/FRED** (St. Louis Fed): economic data as first released, for the Macro Strategist.
- **SEC Form 4**: insider purchases, for the Growth Hunter and Quality & Value.
