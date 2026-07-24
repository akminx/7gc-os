# Derived oracle snapshot

**GENERATED — do not edit.** `python evals/oracle/derive.py`

Every value here is computed from `primitives.yaml`. Nothing in this
file was typed by hand, which is the entire point: two fixer cycles
failed on hand-maintained derived cells.

## Totals

| Fund | Date | Held | Reported | Tracker | Delta | Unsupported | Approved FV |
|---|---|---:|---:|---:|---:|---:|---:|
| fund_ii | 2023-12-31 | 4 | 6000000 | 4000000 | 2000000 | 6000000 | null |
| fund_ii | 2024-12-31 | 7 | 10548515 | 10548515 | 0 | 7548515 | null |
| fund_ii | 2025-12-31 | 8 | 25648515 | 25648515 | 0 | 25648515 | null |
| fund_i | 2023-12-31 | 5 | 5970000 | 5970000 | 0 | 4970000 | null |
| fund_i | 2024-12-31 | 5 | 5905000 | 5905000 | 0 | 4905000 | null |
| fund_i | 2025-12-31 | 5 | 5881000 | 5881000 | 0 | 4881000 | null |

## Per-requirement verdicts

`✓` sufficient · `~` partial · `✗` missing/insufficient · `·` not applicable

| Holding | Date | Reported | R1 | R2 | R3 | R4 | R5 | Row | Labels |
|---|---|---:|:--:|:--:|:--:|:--:|:--:|---|---|
| banzai | 2023-12-31 | 120000 | ~ | ✓ | · | · | · | partial | — |
| because_market | 2023-12-31 | 1000000 | ✗ | ✗ | · | · | · | missing | — |
| capsule | 2023-12-31 | 600000 | ✗ | ✗ | · | · | · | missing | — |
| jackpocket | 2023-12-31 | 2000000 | ✗ | ✗ | · | · | · | missing | — |
| jio | 2023-12-31 | 1000000 | ✓ | ✓ | · | · | · | sufficient | — |
| mom_project | 2023-12-31 | 2750000 | ✗ | ✗ | · | · | · | missing | cross_class_policy |
| moonfare | 2023-12-31 | 1000000 | ✗ | ✓ | · | · | · | missing | — |
| roofstock | 2023-12-31 | 1500000 | ✓ | ✓ | ✗ | · | · | missing | — |
| sway | 2023-12-31 | 2000000 | ~ | ~ | · | · | · | partial | — |
| anthropic | 2024-12-31 | 2000000 | ✗ | ✗ | · | · | · | insufficient | — |
| banzai | 2024-12-31 | 55000 | ~ | ✓ | · | · | · | partial | — |
| because_market | 2024-12-31 | 1000000 | ✗ | ✗ | ✗ | · | · | missing | — |
| capsule | 2024-12-31 | 600000 | ✗ | ✗ | ✗ | · | · | missing | — |
| fluidstack | 2024-12-31 | 1000000 | ✓ | ✓ | · | · | · | sufficient | — |
| jackpocket | 2024-12-31 | — | · | · | · | ✓ | · | sufficient | — |
| jio | 2024-12-31 | 1000000 | ✓ | ✓ | · | · | · | sufficient | — |
| lucra | 2024-12-31 | 1500000 | ~ | ✗ | · | · | · | insufficient | — |
| mom_project | 2024-12-31 | 2750000 | ✗ | ✗ | ✗ | · | · | missing | cross_class_policy |
| moonfare | 2024-12-31 | 1048515 | ✗ | ✓ | · | · | · | missing | — |
| poolside | 2024-12-31 | 2000000 | ✓ | ✓ | · | · | · | sufficient | — |
| roofstock | 2024-12-31 | 1500000 | ✓ | ✓ | ✗ | · | · | missing | — |
| sway | 2024-12-31 | 2000000 | ~ | ~ | ✗ | · | · | missing | — |
| anthropic | 2025-12-31 | 8000000 | ✗ | ✗ | · | · | · | insufficient | — |
| banzai | 2025-12-31 | 31000 | ~ | ✓ | · | · | · | partial | — |
| because_market | 2025-12-31 | 1000000 | ✗ | ✗ | ✗ | · | · | missing | — |
| capsule | 2025-12-31 | 600000 | ✗ | ✗ | ✗ | · | · | missing | — |
| dream | 2025-12-31 | 5000000 | ✗ | ~ | · | · | ✓ | missing | cross_class_policy, pro_forma |
| fluidstack | 2025-12-31 | 6000000 | ~ | ~ | · | · | ✓ | partial | cross_class_policy, pro_forma |
| jio | 2025-12-31 | 1000000 | ✓ | ✓ | · | · | · | sufficient | subsequent_evidence |
| lucra | 2025-12-31 | 2250000 | ~ | ~ | · | · | · | partial | cross_class_policy |
| mom_project | 2025-12-31 | 2750000 | ✗ | ✗ | ✗ | · | · | missing | cross_class_policy |
| moonfare | 2025-12-31 | 1048515 | ✗ | ✗ | ✗ | · | · | missing | — |
| poolside | 2025-12-31 | 2000000 | ✓ | ✓ | ✗ | · | · | missing | — |
| roofstock | 2025-12-31 | 1500000 | ✓ | ✓ | ✗ | · | · | missing | — |
| sway | 2025-12-31 | 350000 | ~ | ~ | · | · | ✓ | partial | pro_forma |

## Calibration required (R3)

| Holding | Date | Stale components |
|---|---|---|
| because_market | 2024-12-31 | valuation |
| sway | 2024-12-31 | valuation |
| because_market | 2025-12-31 | valuation |
| moonfare | 2025-12-31 | underlying_valuation |
| poolside | 2025-12-31 | valuation |
| roofstock | 2023-12-31 | valuation |
| capsule | 2024-12-31 | valuation |
| mom_project | 2024-12-31 | equity_valuation, note_valuation |
| roofstock | 2024-12-31 | valuation |
| capsule | 2025-12-31 | valuation |
| mom_project | 2025-12-31 | equity_valuation, note_valuation |
| roofstock | 2025-12-31 | valuation |

## Entry cost

| Lot | Shares | PPS | Computed | Stated | Check |
|---|---:|---:|---:|---:|---|
| bm_1 | 625000 | 1.60 | 1000000 | 1000000 | pass |
| mf_1 | — | — | — | None | not_applicable |
| sway_1 | 800000 | 2.50 | 2000000 | 2000000 | pass |
| anth_1 | 40000 | 50.00 | 2000000 | 2000000 | pass |
| lucra_1 | 750000 | 2.00 | 1500000 | 1500000 | pass |
| pool_1 | 50000 | 40.00 | 2000000 | 2000000 | pass |
| fluid_1 | 100000 | 10.00 | 1000000 | 1000000 | pass |
| fluid_2 | 100000 | 15.00 | 1500000 | 1500000 | pass |
| dream_1 | 625000 | 3.20 | 2000000 | 2000000 | pass |
| jack_1 | 500000 | 4.00 | 2000000 | 2000000 | pass |
| caps_1 | 500000 | 4.00 | 2000000 | 2000000 | pass |
| mom_1 | 400000 | 2.50 | 1000000 | 1000000 | pass |
| mom_2 | 100000 | 5.00 | 500000 | 500000 | pass |
| mom_3 | — | — | — | None | not_applicable |
| roof_1 | 60000 | 25.00 | 1500000 | 1500000 | pass |
| jio_1 | — | — | — | None | not_applicable |
| banz_1 | 50000 | 10.00 | 500000 | 500000 | pass |
