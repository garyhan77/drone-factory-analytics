# Statistical analysis layer

The rest of this repo describes what happened in the simulated factory. This folder asks three questions that need statistics: **what caused** the defect spike, **how strongly** queue length drives waiting time, and **what would happen if** the factory changed. Each is checked against something the generator fixes, so I can tell whether the method works instead of just trusting its output.

All of the data is synthetic. Nothing here changes the generator's default output, the database, the SQL or the app. Everything runs from `analysis/` and needs `scipy` and `statsmodels`, which are in `requirements-dev.txt` only. A one-page summary for a non-statistician is in [MEMO.md](MEMO.md).

## Run it

```
make analysis        # causal, regression, pilot and experiment (a few minutes)
make analysis-test   # only the analysis tests
```

Or one step at a time: `python -m analysis.causal`, `python -m analysis.regression`, `python -m analysis.experiment pilot`, then `python -m analysis.experiment run`. Results are written to [results/](results/).

## What I added to the generator

A switch, off by default. With it off, the data is byte-identical to before (a test compares fingerprints). With it on (`analysis/sim.py`), inspectors are swamped in weeks 11 to 15, which raises the first-pass failure rate for every job in those weeks. Those are the same weeks the substitute fastener lots reach the line. So the weeks with substitute lots are also the weeks with more failures for another reason. That is a confounder, and I planted it on purpose so the methods have something to correct. The generator also now records the true cause of every failure, which no analyst would have, and the checks below use it.

## 1. Causal inference

**Question.** Does a drone whose Motor & Prop fasteners came from an emergency (spot-buy) lot fail first inspection more often *because of* that lot? The planted answer is +19.5 percentage points.

**Method.** Three estimators of the risk difference, each with a bootstrap interval, using only what an analyst sees (work orders, first inspections, lot traceability):

- *naive*: failure rate with a substitute lot minus without.
- *adjusted*: the same within each week, averaged (regression with a dummy for every week).
- *IPW*: inverse-probability weighting, with the chance of getting a substitute lot estimated within each week.

Two stations upstream of Motor & Prop (Airframe, Wing Assembly) serve as **placebos**: a later fastener lot cannot affect them, so the true effect is zero.

**Result.** 100 simulated datasets, 91 usable (about one in ten has no substitute lot at all):

| Estimator | Mean estimate (truth 19.5) | Bias | 95% interval covers truth |
| --- | --- | --- | --- |
| Naive | 25.9 points | +6.4 | 78% |
| Adjusted | 18.0 points | -1.5 | 91% |
| IPW | 19.5 points | 0.0 | 95% |

On the placebo stations the naive estimate finds a false effect of 6 to 7 points; the adjusted and IPW estimates find about zero. The naive method is not just imprecise; it gets the wrong answer in a predictable direction.

## 2. Regression

**Logistic regression**: first-pass failure on "got a substitute lot", controlling for time in three-week blocks. The model reports an odds ratio (median about 4.1) and the effect on the drones that got a substitute lot in percentage points, which is what gets compared with the planted truth: 20.0 points, bias +0.5, coverage 89%. Without the time control: 25.9 points, bias +6.4, coverage 76%. I used three-week blocks because a dummy for every week breaks down when a week has no failures at all.

The odds ratio has **no single true value** to check against, because the generator plants a constant difference in failure rates, not a constant ratio. That is why the percentage-point effect is the quantity compared.

**Linear regression**: the wait at Avionics against the number of drones already queued when one arrives, with standard errors that allow for waits being correlated over time. The slope is the extra wait per drone ahead in the queue: 6.05 hours (R² 0.95). The check is a separate calculation: in weeks when the queue never clears, Avionics completes about 26 jobs a week, so one more queued drone should add 168 / 26 = 6.17 hours. The two agree to within 15% in every one of the 91 datasets (median ratio 0.98). Note this is a throughput cross-check, not a planted value.

## 3. Experiment design

**Question.** Avionics is the bottleneck. Should the factory add a third lane? A fourth?

**Design, fixed before running.** The unit is a simulated 26-week run (a seed); every seed is run under all three arms (2, 3 and 4 lanes), which pairs the comparison and removes most of the between-run noise.

| Element | Choice |
| --- | --- |
| Primary outcome | Drones shipped by the end of the run |
| Secondary | Drones still queued at Avionics; average Avionics wait |
| Guardrail | Final Test wait, since a faster Avionics could just move the queue downstream; a rise over 24 hours counts as a breach |
| Comparisons | 3 vs 2, 4 vs 3, 4 vs 2, with Holm-adjusted p-values and simultaneous 95% intervals |
| Decision rule | Build a lane only if the lower end of its adjusted interval is at least **25 drones** shipped |
| Diminishing returns | Test the curvature (2-lane result minus twice the 3-lane result plus the 4-lane result) |
| Sample size | Power analysis on 30 separate pilot seeds, 80% power; never fewer than 20 seeds |
| Sanity check | A/A test: split runs of the same arm at random, confirm a 5% false-positive rate |

**Result** (20 fresh seeds):

| Comparison | Extra drones shipped | Adjusted 95% interval | Clears the 25-drone bar? |
| --- | --- | --- | --- |
| 3 lanes vs 2 | +58.1 | +50.0 to +66.2 | Yes |
| 4 lanes vs 3 | +7.8 | +2.0 to +13.6 | No |
| 4 lanes vs 2 | +65.9 | +56.2 to +75.6 | Yes |

The curvature is -50.3 drones (interval -58.4 to -42.2, p < 0.001): the third lane adds about 58 drones and the fourth about 8, so the returns diminish sharply. The fourth lane's gain is real (Holm p = 0.002) but far below the bar. Queue at the end of the run: 82, 24, 14 drones. Avionics wait: 162, 59, 44 hours. The guardrail holds: Final Test wait rises 1.4 hours (3 lanes) and 3.1 hours (4 lanes), well under 24. The A/A false-positive rate is 5.9%. A Welch test on randomly assigned arms (the unpaired design) agrees with the paired one, but would need about three times as many runs for the same precision.

## What this does not show

- **The data is synthetic.** I know the truth because I wrote the generator. That is the point (I can score the methods), and also the limit: real data does not come with an answer key.
- **I planted the confounder.** Week adjustment works here because the confounder is a function of week. Real confounders are rarely that observable, and no adjustment can fix one you have not measured.
- **The odds ratio has no single truth**, as described above.
- **The 25-drone bar is an assumption**, not derived from a cost model. A different bar could change "build the third, not the fourth".
- **Adding capacity to a bottleneck raising output is not a surprising result.** The value here is in the design: a pre-specified outcome and guardrail, a power analysis on separate seeds, multiple-comparison control, and an A/A check.
- **The simulated worlds are independent.** There is no interference between runs, no novelty effect and no peeking, all of which complicate real experiments.
- **The Avionics slope is checked against throughput**, not against a planted value.

## How the design changed

The first experiment compared only 2 and 3 lanes, on seeds 1000 to 1019 (+53.4 drones). I added the fourth lane after seeing that result, so the three-arm version uses fresh seeds (2000 to 2019). That makes it a replication of the first result (+58.1) as well as an extension. The first run reported a Final Test wait rise of 4.6 hours; on the fresh seeds it was 1.4 hours, so the direction is consistent but the size is not stable across seed sets. The first run's CSVs were overwritten by the three-arm run; its numbers are recorded here and in the `analysis/experiment.py` docstring.

## Files

| File | Contents |
| --- | --- |
| `sim.py` | Runs the generator with the confounder on or with other settings changed, restoring the config afterwards |
| `causal.py` | The three estimators, bootstrap, placebos, many-seed check |
| `regression.py` | Logistic and Avionics wait models, many-seed check |
| `experiment.py` | The experiment: pilot, power analysis, runs, tests, A/A check |
| `results/` | CSVs written by the commands above |
| `../tests/test_analysis_*.py` | 31 tests for the analysis code |
