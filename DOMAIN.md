# The simulated factory

Design spec. Numbers are starting values and get tuned once the simulation runs.

## Questions the project answers

1. Which station limits output?
2. Which parts will run out first?
3. Can we trust the data?

## Line

Five stations in a fixed order: Airframe, Wing Assembly, Motor & Prop, Avionics, Final Test.

Avionics is the bottleneck. Motor & Prop is where the defect spike happens.

Two shifts, 06:00 to 22:00, Monday to Friday (80 working hours a week). Starting values, to be tuned once the simulation runs:

| Station | Code | Lanes | Typical cycle | First-pass fail rate | Capacity |
|---|---|---|---|---|---|
| Airframe | AFL | 3 | 3.0 h | 3.0% | about 80 a week |
| Wing Assembly | WNG | 3 | 3.5 h | 3.5% | about 68 a week |
| Motor & Prop | MTR | 2 | 2.0 h | 2.5% (22% in weeks 12-15) | about 80 a week |
| Avionics | AVN | 2 | 5.0 h | 5.0% | about 30 a week |
| Final Test | FNT | 3 | 3.0 h | 4.0% | about 80 a week |

A failed inspection adds 1 to 2.5 hours of rework, and a second inspection then passes.

Weekly releases: 18 in week 1, rising to 30 by week 12, then to 34 by week 26. Avionics capacity is about 30, so a queue forms around week 12.

## Stack

Python for data generation and the app, PostgreSQL for storage and all SQL, Streamlit for the dashboard.

## Scale

26 weeks of history, about 40 parts (8 per station), 10 tables (see Tables).

## Supply

40 parts (8 per station) from 8 suppliers. Starting values:

| Supplier | Supplies | Quoted lead time |
|---|---|---|
| Ridgeline Hardware (unreliable) | 8 fastener and hardware parts | 10 days |
| Northgate Composites | carbon fibre, spars, skins | 21 days |
| Meridian Electronics | radios, boards, harnesses | 21 days |
| Cobalt Motion | motors, servos, propellers | 18 days |
| Summit Polymers | foam, resin, film | 10 days |
| Vector Avionics | flight controller, GPS, IMU | 28 days |
| Granite Packaging | crates, foam, labels | 5 days |
| Spot-buy distributor | emergency buys only; source of the substitute fastener lot | n/a |

- Normal supplier behaviour: 8% of shipments late by 1 to 3 days, 3% short.
- Ridgeline in weeks 9-11: about 55% late by 3 to 9 days, about 30% short (60 to 90% of the quantity).
- Reorder point = launch demand x (lead time + 5 days). Orders go up to 21 days of recent demand.
- Line-side stock is replenished daily from the warehouse, targeting 2 days of demand. Replenishment capacity grows slower than the ramp, which starves the line from week 16. A part is "starved" when line-side on-hand is below one day of demand (from the BOM and recent starts).
- Finished drones are packed within 4 to 24 hours of passing test and shipped in a daily batch.
- Planted errors hit 1 to 3% of the relevant rows for each type, with a minimum of 3.

## The story: a new line scaling faster than its support systems

One root cause drives everything: weekly releases ramp up (starting at 18 drones a week) faster than planning, capacity and supply can follow. All data stories, and all planted data errors, hang off this.

| Weeks | What happens | What the data shows |
|---|---|---|
| 1-8 | Launch. Releases start at 18 a week and climb. Reorder points are sized from launch-volume demand. | Healthy yield, short queues, comfortable stock |
| 9-11 | The hardware/fasteners supplier ships late and short as volume rises. Fastener stock runs thin. Substitute fastener lots are issued against the wrong part numbers. | Late and short receipts. **Negative inventory** on fastener parts. The substitute lot is bought from a spot-buy distributor and arrives with its own lot ID. |
| 12-15 | The line runs on the substitute lot, and loose-fastener failures spike at Motor & Prop (roughly 2.5% to 22%). Inspectors are swamped, and relabelled rework units get mistyped serials. The supplier's catch-up shipments over-ship. | Yield dip at Motor & Prop. **Missing defect codes**, **orphan inspections** and **over-receipts** cluster here. `drone_part_lots` records which drones got the substitute lot. |
| 12-26 | Rework returns to the line in bursts and releases keep climbing past what Avionics can handle. A queue builds in front of it; completions plateau while starts keep rising. WIP piles up and work orders get re-keyed by hand. Drones wait at Avionics, so they reach Final Test and shipping later. | Queue wait at Avionics grows. Output flattens. Lead time from first station to shipped grows. Dwell time from test pass to shipped stays normal, because the delay is upstream. **Duplicate work orders** and **end-before-start** errors cluster at Avionics. |
| 16-26 | Reorder points are still sized for launch volume, so long-lead parts run thin. The hardware supplier's parts are the most exposed. Replenishment from warehouse to the line lags the ramp. | Stockout risk concentrated on that supplier's parts. For some parts the warehouse looks fine while `LINE_SIDE` stock is empty. |

### What an analysis should be able to find

1. Late and short hardware shipments, then thin fastener stock, then a defect spike at Motor & Prop a few weeks later.
2. A queue at Avionics that grows as releases pass its capacity, made worse by rework bursts.
3. A short list of parts at risk of running out, mostly from the hardware supplier.
4. Recall scope: which drones contain the substitute fastener lot, and how many of them have already shipped.
5. Right part, wrong place: parts with healthy warehouse stock but an empty line-side location.
6. Avionics queueing delays what customers see: lead time from first station to shipped grows, while dwell time after test stays flat, which shows the delay is upstream.
7. Bad data that hides the story if it is not cleaned. Missing defect codes shrink the apparent spike, and negative fastener stock exaggerates the shortage.

The causal links are planted by the generator. The README should say so.

## Tables

Ten tables, each tied to a source system the IQME team works with. Exact columns are in `sql/schema.sql`.

| Table | Grain | Closest real-world source |
|---|---|---|
| `stations` | one row per station | MES routing / work centre master |
| `suppliers`, `parts` | one row per supplier / part | ERP vendor and item master |
| `bom` | station x part | ERP bill of materials |
| `inventory_snapshots` | part x day x location (WAREHOUSE or LINE_SIDE) | ERP inventory balance, snapshotted daily |
| `receiving` | one row per shipment (one supplier lot each) | ERP purchase order receipts |
| `work_orders` | drone x station | MES work order / operation records |
| `inspections` | one inspection attempt | MES / quality system, traceable by serial number |
| `drone_part_lots` | drone x part installed | traceability system: which lot went into which drone |
| `finished_goods` | one row per drone that passed Final Test | ERP / warehouse: packed and shipped status |

## Planted data errors

The generator corrupts a small share of rows and records exactly which ones in an answer key, so each check can be scored on what it caught, missed, or wrongly flagged. Errors are placed by the story, not scattered randomly.

| Planted error | Table | Where it lands | What it breaks |
|---|---|---|---|
| Negative inventory | inventory_snapshots | fastener parts, weeks 9-12 | days of stock remaining |
| Missing defect code | inspections | failures at Motor & Prop, weeks 12-15 | defect Pareto (row is kept and labelled UNCODED, not dropped) |
| Orphan inspections | inspections | reworked units at Motor & Prop, weeks 12-15 | link between yield and the work it measures |
| Over-receipt | receiving | hardware supplier catch-up shipments, weeks 12-14 | supplier on-time-in-full |
| Duplicate work orders | work_orders | Avionics, weeks 16-26 | output counts and cycle times |
| End before start | work_orders | Avionics, weeks 16-26 | cycle time (negative durations) |

Not planted: unknown part in receiving (same pattern as orphan inspections).

Guard checks (nothing planted; each should flag zero rows): status vs. end timestamp on work orders; every `lot_id` in `drone_part_lots` exists in `receiving`; every serial in `drone_part_lots` exists in `work_orders`; every drone in `finished_goods` has a passing Final Test inspection; test passed <= packed <= shipped.

## Matching the IQME team description

The project is meant to cover what the posting says the team does. This is how each part is covered.

| The posting says | In the project |
|---|---|
| Parts and materials in the right place at the right time | `receiving`, plus warehouse vs. line-side stock in `inventory_snapshots` |
| Receiving, warehouse storage, staging at the line | `location` column: WAREHOUSE or LINE_SIDE |
| Finished goods ready to ship | `finished_goods` (packed and shipped times) |
| Data from ERP, MES and traceability tools | ERP tables, MES tables, and `drone_part_lots` for traceability |
| Standing up new lines and scaling fast | the ramp-up story |
| Validating datasets and catching issues | SQL data quality checks scored against planted errors |
| Open-ended questions from the floor and leadership | README frames the questions as coming from a production lead, a quality engineer and a material planner |


## README

First person and plain, with a short "why this project" paragraph in my own words about drones and Zipline's mission, public facts only. The README states that the data is synthetic and that the story's causal links are planted by the generator.
