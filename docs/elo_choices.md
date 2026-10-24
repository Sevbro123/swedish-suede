# Elo results rating

Added 2026-10-23 after an audit of inputs the model was missing.

**What it is.** Each franchise has a rating (1500 = average). Games are processed in start-time order; a
game's row holds both ratings *before* the game, then they move by
`k * ln(|goal margin| + 1) * (result - expected)`, with
`expected = 1 / (1 + 10^(-(R_home - R_away + hfa) / 400))` (no `hfa` at neutral sites). Overtime and
shootout wins count as wins, as the moneyline settles them. Between seasons a rating keeps `carry` of its
distance from 1500. Code: `src/nhlmodel/features/elo.py`; tests: `tests/test_elo.py` (arithmetic, carryover,
and that scrambling later results leaves earlier ratings unchanged).

**Settings, fixed in advance (not tuned):** `k = 6`, `hfa = 35`, `carry = 0.7` (`configs/features/base.yaml`
`elo`). These are conventional hockey Elo values, picked before any run. The model sees the home-minus-away
rating difference like every other input (`features: full_rapm_elo`).

**Why it adds something.** The matrix already has goal shares, but over windows of at most 20 games or
the season to date. Elo keeps a long memory across seasons and scores results against opponent strength,
which carries finishing and goaltending signal that xG shares smooth away.

**Results** (paired log-loss difference vs the previous live model, 95% day-block bootstrap; negative = Elo
better):

| Comparison | Dev 2012-18 (n=6,911) | Test 2018-26 (n=9,781) |
| --- | --- | --- |
| `el_logreg_full_C0.001` - `rp_logreg_full_C0.001` | -0.00026 [-0.00049, -0.00005] | -0.00055 [-0.00084, -0.00026] |
| `el_logreg_full_actual_C0.001` - `rp_logreg_full_actual_C0.001` | -0.00026 [-0.00048, -0.00005] | -0.00053 [-0.00081, -0.00024] |

Better on dev, then on test, so the live model switched to the `el_logreg_full` configs.

**Tested in the same audit, not adopted** (added to the live model; scratch code, not in the repo):

| Candidate | Dev | Test |
| --- | --- | --- |
| Travel km into the game and over 7 days, road-trip and homestand game number | +0.00010 [-0.00019, +0.00039] | +0.00013 [-0.00009, +0.00035] |
| Team's own home-vs-road win split (2 seasons, shrunk) | +0.00006 [-0.00003, +0.00015] | 0.00000 [-0.00010, +0.00010] |
| Projected starter's days since his last start, and started yesterday | -0.00003 [-0.00028, +0.00023] | +0.00007 [-0.00010, +0.00026] |

Rest days, back-to-backs and time-zone change already cover the schedule.
