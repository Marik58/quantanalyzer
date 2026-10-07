---
id: news-analyst
kind: agent-evidence
editable_by: code (backend/agent_evidence.py)
updated: 2026-10-07
sources: context/research/base_rates.json, context/research/backtests/2026-10-07-screens-v1-data-v2/summary.json
---

# Evidence for news-analyst

## Reading SEC Form 8-K filings (item codes)

Companies must file an 8-K within four business days of these events. Titles as printed on
the SEC's Form 8-K (sec.gov/files/form8-k.pdf):

| Item | Event |
|---|---|
| 1.01 | Entry into a Material Definitive Agreement |
| 1.02 | Termination of a Material Definitive Agreement |
| 1.03 | Bankruptcy or Receivership |
| 1.05 | Material Cybersecurity Incidents |
| 2.01 | Completion of Acquisition or Disposition of Assets |
| 2.02 | Results of Operations and Financial Condition |
| 2.03 | Creation of a Direct Financial Obligation |
| 2.05 | Costs Associated with Exit or Disposal Activities |
| 2.06 | Material Impairments |
| 3.01 | Notice of Delisting or Failure to Satisfy a Continued Listing Rule |
| 4.02 | Non-Reliance on Previously Issued Financial Statements |
| 5.01 | Changes in Control of Registrant |
| 5.02 | Departure or Election of Directors or Certain Officers |
| 5.07 | Submission of Matters to a Vote of Security Holders |
| 7.01 | Regulation FD Disclosure |
| 8.01 | Other Events |

**Use it this way:** before reading a big move as hype or momentum, check for an 8-K. Example
from the data: PTC rose 33% on 2026-10-05, the day its 8-K reported Item 1.01 (a material
agreement): Schneider Electric agreed to buy it for $205 a share in cash. A cash buyout
caps the price near the deal price. That's news, not a trend.
