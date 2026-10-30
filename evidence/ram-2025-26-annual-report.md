# RAM 2025–26 Annual Report — Bluey reconciliation (2026-10-31)

Verified from freshly downloaded primary source (facts and short extracts only).

## Primary source

- Report index: https://www.ramint.gov.au/about-us/compliance-and-reporting/annual-reports
- Full report: https://www.ramint.gov.au/sites/default/files/2026-10/2025-26%20Annual%20Report_B5_PROOF%20V10.pdf
  (7,185,572 bytes, 132 pages as extracted; Bluey collector rows on report pp. 90–92,
  Appendix E Table E1 "Collector coin production (2025–26)")
- Extraction: direct PDF text extraction (PyMuPDF), cross-checked page by page.
- Note: the 2025–26 report labels the collector table Appendix E (prior years: Appendix D/E
  with the same "Collector coin production" title). The routine's "Appendix D" = this table.

## Catalogue-mapped Bluey rows (all first appearances — none in 2024–25 appendices)

| Catalog id | RAM product name | Year | Code | Qty (issueQuantity) | Mintage | Check |
|---|---|---|---|---|---|---|
| s2_xmas_silv | $1 Coloured Fine Silver Proof Coin – Bluey Christmas | 2025 | 11981 | 10,000 | 10,000 | Qty = mintage, OK |
| s2_xmas_unc | $1 Coloured Uncirculated Coin – Bluey Christmas | 2025 | 11982 | 125,000 | 125,000 | Qty = mintage, OK |
| s3_folder | $2 Uncirculated Collection Folder and Five-Coin Set – Bluey | 2026 | 11956 | 15,000 | Unlimited | OK |
| s3_proof_silv | $2 Coloured Silver Proof Coin – Bluey – The Heeler Family | 2026 | 11996 | 10,800 | 12,000 | under mintage, OK |
| s3_proof_ab | $2 Coloured Proof Coin – Bluey – The Heeler Family | 2026 | 11997 | 9,800 | 10,500 | under mintage, OK |
| s3_rain_privy | $2 'Envelope' Privy Mark Uncirculated Coin – Bluey – Rain | 2026 | 12001 | 20,000 | 20,500 | under mintage, OK |
| s3_sleepytime_privy | $2 'Envelope' Privy Mark Uncirculated Coin – Bluey – Sleepytime | 2026 | 12003 | 20,000 | 20,500 | OK |
| s3_camping_privy | $2 'Envelope' Privy Mark Uncirculated Coin – Bluey – Camping | 2026 | 12005 | 20,000 | 20,500 | OK |
| s3_babyrace_privy | $2 'Envelope' Privy Mark Uncirculated Coin – Bluey – Baby Race | 2026 | 12007 | 20,000 | 20,500 | OK |
| s3_granny_privy | $2 'Envelope' Privy Mark Uncirculated Coin – Bluey – Granny Mobile | 2026 | 12009 | 20,000 | 20,500 | OK |

Change: added `issueQuantity` to these 10 rows in `index.html`. No mintage changed.
No total exceeds its mintage. Nothing summed: each code appears in one report only
(verified absent from RAM-2024-25 appendices), so no double-count risk on these rows.

## Cross-checks (coin + PNC pairs reconcile exactly to shared mintage)

- Rain: 12001 (20,000) + 12002 PNC (500) = 20,500 = mintage. Same pattern for
  Sleepytime (12003+12004), Camping (12005+12006), Baby Race (12007+12008),
  Granny Mobile (12009+12010).
- Heeler Family AlBr proof: 11997 (9,800) + 12022 PNC (700) = 10,500 = mintage.
- Heeler Family silver proof: 11996 (10,800) + 12021 PNC (1,200) = 12,000 = mintage.
- Christmas: both rows fully struck to mintage (10,000/10,000; 125,000/125,000).

## Prior-report comparison (no double-count)

- Codes 11491–11508, 11641 and 11679 appear identically in both the 2023–24 and 2024–25
  appendices (verified by text search: same code lists on 2023–24 pp. 5/7/8 and 2024–25
  pp. 3/4). Per the routine rule these are per-release-year restatements, NOT additive —
  nothing was summed and no s1 catalogue figures were touched.
- All 27 new 2025–26 Bluey codes (11955, 11956, 11981, 11982, 11989, 11992–11994,
  11996, 11997, 12001–12012, 12019–12022, 12220) return zero hits in the 2024–25
  appendices PDF. First appearance = current-year production.

## Not changed (needs owner decision before mapping)

- Series 4 Cricket (s4_cricket_unc 12077, s4_cricket_proof 12078): zero hits in the
  2025–26 report ("Cricket" absent). Catalogue unchanged; existing RAM-shop specs stand.
- RAM envelope-privy PNCs (12002, 12004, 12006, 12008, 12010, all Qty 500) and other
  RAM PNC rows (11989, 11992–11994, 12012, 12019, 12020, 12021, 12022, 12220) have no
  matching catalogue records — catalogue only holds AusPost PNCs (s3_pnc_bluey/bingo).
  No new records created; awaiting James's call on whether to list RAM PNCs separately.
- Sachet rows 11955 ($2 Coloured UNC Bluey Sachet, 1,250,000) and 12011 ($2 UNC Bingo
  Sachet, 1,250,000) are candidate matches for s3_till_bluey / s3_till_bingo, which
  currently carry no productCode. Left unmapped pending confirmation.
- s3_sleepytime_insert derived scarcity: folder-set production is now 15,000 tubes
  (11956), implying ~1,500 coloured inserts at 1-in-10. Catalogue note still describes
  the derivation as pending; derived figure not written — confirm before publishing.

## Tests

- `python -m unittest discover -s . -p "test_*.py"` — result recorded in PR checks.
