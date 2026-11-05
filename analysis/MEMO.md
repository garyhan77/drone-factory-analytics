# Memo: Should the factory add Avionics lanes?

**To:** Production lead and operations planning  **From:** Data analysis  **Basis:** simulated factory (synthetic data), 20 simulated 26-week runs per option

## Recommendation

**Add a third Avionics lane. Do not add a fourth.**

- A third lane ships about **58 more drones** over 26 weeks (95% interval 50 to 66), roughly 9% more output.
- A fourth lane adds only about **8 more** (interval 2 to 14). That is real but well under the 25 drones we set as the minimum worth building for.

| Avionics lanes | Drones shipped | Drones still queued at Avionics at the end | Average Avionics wait |
| --- | --- | --- | --- |
| 2 (today) | 615 | 82 | 162 h |
| 3 | 673 | 24 | 59 h |
| 4 | 681 | 14 | 44 h |

## Why the first lane helps and the next barely does

About 31 drones arrive at Avionics each week and two lanes can start about 26, so the queue grows every week. A third lane removes most of that shortfall. Once the queue is nearly gone, another lane has little left to clear, and the bottleneck moves elsewhere.

## What to watch

Faster Avionics can push the queue downstream. We checked Final Test: its wait rose about 1.4 hours with three lanes and 3.1 with four, against a limit of 24 hours. The size of that rise varied between our two test rounds (4.6 and 1.4 hours with three lanes), so treat it as small but not precisely known.

## How sure are we, and what could change the answer

- **The 25-drone threshold is our assumption.** It stands in for what a lane costs. If a lane is much cheaper, the fourth could be worth it; if it is dearer, even the third needs a second look. Please replace it with the real cost.
- **This is a simulation.** The factory is synthetic, and the result that more capacity at a bottleneck raises output is expected. What the exercise shows is how the decision should be tested: one pre-set outcome, a guardrail, enough runs to detect the smallest difference that matters, and a corrected comparison across the three options.
- **A real trial would be messier.** Real lanes have ramp-up time, staffing and learning effects that this model leaves out, and a real test would need running over weeks, not a single extract.

## Appendix: method

Each of 20 random simulated runs was played out under all three options, so the options are compared on identical conditions. The number of runs came from a power analysis on separate pilot runs (80% power; the analysis said 6 to 9, and we used 20 as a floor). Results are paired differences with Holm-corrected p-values and simultaneous 95% intervals, confirmed by a permutation test. An A/A check (splitting runs of the same option at random) produced false positives 5.9% of the time, as it should at a 5% level. The diminishing-returns result is tested directly: the fourth lane's gain minus the third's is -50 drones (interval -58 to -42). Details, caveats and the history of the design are in [README.md](README.md).
