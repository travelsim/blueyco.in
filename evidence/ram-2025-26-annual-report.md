# RAM 2025–26 Annual Report — Bluey reconciliation (2026-10-31, re-verified 2026-11-09)

Verified from primary sources downloaded directly from ramint.gov.au (facts and short extracts only).

## Primary sources

1. Report index: https://www.ramint.gov.au/about-us/compliance-and-reporting/annual-reports
2. Full report (pre-publication proof, October 2026):
   https://www.ramint.gov.au/sites/default/files/2026-10/2025-26%20Annual%20Report_B5_PROOF%20V10.pdf
   7,185,572 bytes, 132 pages, SHA-256 `84FDD441D8C948C44979CE5E63382EE91271B098323BACD3351EE41F3B840909`.
3. Published coin-production appendices (November 2026 — final):
   https://www.ramint.gov.au/sites/default/files/2026-11/2025-26%20Annual%20Report%20-%20Coin%20production.pdf
   196,824 bytes, 9 pages, PDF creation date 2026-11-03,
   SHA-256 `86F56D9B679023665AAD1C849FC1AD5F6A8DC3CA935CC4F51ABD2CEAF8D63DA1`.
   Table E1 "Collector coin production (2025–26)" runs pp. 88–93 of the appendices file.

The report numbers the collector table **Appendix E, Table E1**. Prior years used Appendix D
with the same title, so the routine's "Appendix D" refers to this table. Extraction was direct
PDF text extraction (PyMuPDF) and was cross-checked code by code across both PDFs.

## 2026-11-09 re-check: published appendices match the proof exactly

The November 2026 standalone appendix was published after the proof we extracted from. Every
Bluey-related product code was re-read from the published file and compared with the proof:

| Code | Product | Qty | Mintage | Proof vs published |
|---|---|---|---|---|
| 11955 | $2 Coloured Uncirculated Coin – Bluey – Sachet | 1,250,000 | Unlimited | identical |
| 11956 | $2 Uncirculated Collection Folder and Five-Coin Set – Bluey | 15,000 | Unlimited | identical |
| 11981 | $1 Coloured Fine Silver Proof Coin – Bluey Christmas | 10,000 | 10,000 | identical |
| 11982 | $1 Coloured Uncirculated Coin – Bluey Christmas | 125,000 | 125,000 | identical |
| 11989 | $2 Coloured Uncirculated Coin – Bluey – PNC | 11,500 | Unlimited | identical |
| 11992–11994 | $2 Uncirculated Coin – Bluey – Camping / Baby Race / Granny Mobile – PNC | 500 each | Unlimited | identical |
| 11996 | $2 Coloured Silver Proof Coin – Bluey – The Heeler Family | 10,800 | 12,000 | identical |
| 11997 | $2 Coloured Proof Coin – Bluey – The Heeler Family | 9,800 | 10,500 | identical |
| 12001–12010 | $2 'Envelope' Privy Mark coins and PNCs (Rain, Sleepytime, Camping, Baby Race, Granny Mobile) | 20,000 coin / 500 PNC each | 20,500 | identical |
| 12011 | $2 Uncirculated Coin – Bluey – Bingo – Sachet | 1,250,000 | Unlimited | identical |
| 12012 | $2 Uncirculated Coin – Bluey – Bingo – PNC | 11,500 | Unlimited | identical |
| 12019–12022 | Bluey PNC variants (Rain, Sleepytime, Heeler Family silver, Heeler Family AlBr) | 500 / 500 / 1,200 / 700 | Unlimited / Unlimited / 12,000 / 10,500 | identical |
| 12220 | $2 Uncirculated Coin – Bluey – Sleepytime (Special edition) – PNC | 4,500 | Unlimited | identical |

Result: **no figure changed between the October proof and the published November appendix.**
All 27 Bluey codes were checked individually; 27/27 identical. No catalogue value needs revising.

## Catalogue-mapped rows (applied 2026-10-31, live on main as a2770bb)

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

The ten `issueQuantity` values are on `main` (commit a2770bb, 2026-10-31). No mintage changed.
No total exceeds its mintage. Nothing was summed: each code appears in one report year only,
so there is no double-count risk on these rows.

## Cross-checks (coin + PNC pairs reconcile exactly to shared mintage)

- Rain: 12001 (20,000) + 12002 PNC (500) = 20,500 = mintage. Same pattern for
  Sleepytime (12003+12004), Camping (12005+12006), Baby Race (12007+12008), Granny Mobile (12009+12010).
- Heeler Family AlBr proof: 11997 (9,800) + 12022 PNC (700) = 10,500 = mintage.
- Heeler Family silver proof: 11996 (10,800) + 12021 PNC (1,200) = 12,000 = mintage.
- Christmas: both rows fully struck to mintage (10,000/10,000; 125,000/125,000).

## Prior-report comparison (no double-count)

- Codes 11491–11508, 11641 and 11679 appear identically in both the 2023–24 and 2024–25
  appendices (same code lists on 2023–24 pp. 5/7/8 and 2024–25 pp. 3/4). Per the routine rule
  these are per-release-year restatements, NOT additive — nothing was summed and no s1
  catalogue figures were touched.
- All 27 new 2025–26 Bluey codes (11955, 11956, 11981, 11982, 11989, 11992–11994,
  11996, 11997, 12001–12012, 12019–12022, 12220) return zero hits in the 2024–25
  appendices PDF. First appearance = current-year production.

## Coverage check against the live catalogue (2026-11-09)

Every catalogue row whose `productCode` appears in Table E1 already carries an
`issueQuantity`: 0 gaps out of 56 rows with a product code (55 with a quantity). 43 catalogue
product codes are absent from the 2025–26 table because they are 2023–24 / 2024–25 releases
carried from the earlier appendices, Australia Post stamp/pin covers, or the two 2027 Cricket
coins.

## Not changed (needs owner decision before mapping)

- Series 4 Cricket (`s4_cricket_unc` 12077, `s4_cricket_proof` 12078): zero hits in the
  published 2025–26 appendix ("Cricket" absent). Both are 2027 releases, so this is expected.
  Catalogue unchanged; existing RAM-shop specs stand.
- RAM envelope-privy PNCs (12002, 12004, 12006, 12008, 12010, Qty 500 each) and other RAM PNC
  rows (11989, 11992–11994, 12012, 12019, 12020, 12021, 12022, 12220) have no matching
  catalogue records — the catalogue only holds AusPost PNCs (`s3_pnc_bluey`/`s3_pnc_bingo`).
  No new records created; awaiting the owner's call on whether to list RAM PNCs separately.
- `s3_folder_chase` and `s3_sleepytime_insert` carry a derived scarcity of ~1,500 coins
  (1-in-10 hit across 15,000 tube sets) in `issueQuantity`. That is a derived figure for a
  shared RAM product code (11956), not a Table E1 production quantity. Worth confirming the
  display never presents it as RAM production.
