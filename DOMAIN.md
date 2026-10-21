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

| Station | Code | Lanes | Typical cycle | First-pass fail rate | Capacity (measured) |
|---|---|---|---|---|---|
| Airframe | AFL | 3 | 3.0 h | 3.0% | about 68 a week |
| Wing Assembly | WNG | 3 | 3.5 h | 3.5% | about 58 a week |
| Motor & Prop | MTR | 2 | 2.0 h | 2.5% (22% on drones with a substitute-lot fastener) | about 70 a week |
| Avionics | AVN | 2 | 4.4 h | 5.0% | about 29 a week |
| Final Test | FNT | 3 | 3.0 h | 4.0% | about 68 a week |

A failed inspection adds 1 to 2.5 hours of rework, and a second inspection then passes.

Weekly releases: 18 in week 1, rising to 30 by week 12, then to 34 by week 26. Avionics capacity is about 29 a week, so a queue forms around week 12, when releases reach 30; by week 26 Avionics is at about 116% of capacity while the next-tightest station (Wing Assembly) is at about 59%. (Capacities are measured by saturating each station in the simulation, with lanes, lognormal cycle times and rework; jobs that cannot finish before the end of a shift wait for the next one, which costs 12 to 19% of nominal capacity. Avionics was tuned from 5.0 h to 4.4 h: at 5.0 h the queue formed around week 5 and reached 25 days; 4.4 h was chosen after comparing 4.2 to 4.6 h across 10 random seeds, where it gave a clear queue from week 12 and about 6 days of wait by the end.)

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
| Meridian Electronics | radios, boards, harnesses, batteries | 21 days |
| Cobalt Motion | motors, servos, propellers | 18 days |
| Summit Polymers | foam, resin, film | 10 days |
| Vector Avionics | flight controller, GPS, IMU | 28 days |
| Granite Packaging | crates, foam, labels | 5 days |
| Spot-buy distributor | emergency buys only; source of the substitute fastener lot | n/a |

- Normal supplier behaviour: 8% of shipments late by 1 to 3 days, 3% short.
- Ridgeline, on shipments expected to arrive in weeks 9-11: 95% late by 8 to 14 days and 60% short (40 to 70% of the quantity). This is a multi-week supplier crisis, severe enough that a healthy stock buffer cannot absorb it; milder settings left the outage dependent on luck in some seeds.
- Reorder point = launch demand x (lead time + 12 days). Orders go up to 28 days of recent demand.
- Line-side stock is replenished each weekday from the warehouse, targeting 2 days of demand, limited by a pieces-per-day kitting cap per station (see How supply and inventory work). A part is "starved" when line-side on-hand is below one day of demand (from the BOM and recent starts).
- Finished drones are packed 4 to 24 working hours after passing Final Test (random; packing happens during shifts, so a drone that passes late on Friday is packed on Monday) and ship in one batch each weekday at 16:00: anything packed by then ships that day, anything later waits for the next weekday. Carrier capacity is unlimited, so shipping never backs up. The data is extracted at 14:00 on the last Friday, so that day's drones are packed but not yet shipped.
- Planted errors hit 1 to 3% of the relevant rows for each type, with a minimum of 3.

## Parts and bill of materials

40 parts, 8 per station. Part IDs are the station code and a number (for example `MTR-003`). Ridgeline Hardware's parts include the three Motor & Prop fasteners (motor mount, prop nut, thread locker) that the defect spike depends on.

| Part ID | Part | Supplier | Unit cost | Qty per drone |
|---|---|---|---|---|
| AFL-001 | Carbon fibre sheet | Northgate Composites | $85 | 4 |
| AFL-002 | Foam core block | Summit Polymers | $22 | 2 |
| AFL-003 | Epoxy resin kit | Summit Polymers | $35 | 1 |
| AFL-004 | Fuselage mould insert | Northgate Composites | $140 | 1 |
| AFL-005 | Vacuum bagging film | Summit Polymers | $12 | 2 |
| AFL-006 | Structural fastener kit | Ridgeline Hardware | $18 | 1 |
| AFL-007 | Release agent | Summit Polymers | $9 | 1 |
| AFL-008 | Peel ply section | Northgate Composites | $7 | 3 |
| WNG-001 | Wing spar | Northgate Composites | $95 | 2 |
| WNG-002 | Wing skin panel | Northgate Composites | $60 | 2 |
| WNG-003 | Servo | Cobalt Motion | $28 | 4 |
| WNG-004 | Control horn | Ridgeline Hardware | $3 | 4 |
| WNG-005 | Hinge pin set | Ridgeline Hardware | $5 | 2 |
| WNG-006 | Wing connector | Meridian Electronics | $16 | 2 |
| WNG-007 | Foam rib set | Summit Polymers | $14 | 2 |
| WNG-008 | Pushrod | Ridgeline Hardware | $4 | 4 |
| MTR-001 | Brushless motor | Cobalt Motion | $120 | 2 |
| MTR-002 | Propeller | Cobalt Motion | $45 | 2 |
| MTR-003 | Motor mount | Ridgeline Hardware | $14 | 2 |
| MTR-004 | Speed controller | Meridian Electronics | $55 | 2 |
| MTR-005 | Prop nut | Ridgeline Hardware | $1.5 | 2 |
| MTR-006 | Thread locker | Ridgeline Hardware | $6 | 1 |
| MTR-007 | Motor wiring harness | Meridian Electronics | $18 | 2 |
| MTR-008 | Vibration damper | Summit Polymers | $4 | 4 |
| AVN-001 | Flight controller | Vector Avionics | $310 | 1 |
| AVN-002 | GPS module | Vector Avionics | $75 | 1 |
| AVN-003 | IMU sensor | Vector Avionics | $90 | 2 |
| AVN-004 | Radio transceiver | Meridian Electronics | $130 | 1 |
| AVN-005 | Battery pack | Meridian Electronics | $480 | 1 |
| AVN-006 | Power distribution board | Meridian Electronics | $65 | 1 |
| AVN-007 | Avionics harness | Meridian Electronics | $40 | 1 |
| AVN-008 | Parachute release module | Vector Avionics | $160 | 1 |
| FNT-001 | Payload bay door | Northgate Composites | $70 | 1 |
| FNT-002 | Latch assembly | Ridgeline Hardware | $15 | 2 |
| FNT-003 | Calibration label kit | Granite Packaging | $3 | 1 |
| FNT-004 | Packaging foam set | Granite Packaging | $18 | 1 |
| FNT-005 | Shipping crate | Granite Packaging | $85 | 1 |
| FNT-006 | Gasket set | Summit Polymers | $8 | 1 |
| FNT-007 | Test seal kit | Summit Polymers | $11 | 1 |
| FNT-008 | Quick-start card | Granite Packaging | $2 | 1 |


## How supply and inventory work

Supply and production are one coupled simulation. Stock that runs out delays work, so shortages show up in the data as delays and defects, not just as numbers on a risk list.

- **Starting stock.** The data begins mid-history, so each part starts with warehouse stock and line-side stock that arrived before week 1. That stock appears in `receiving` as pre-launch shipments dated December 2025, one lot per part, so every lot ID used in traceability has a matching shipment.
- **Two stock locations per part.** Shipments arrive at the warehouse on weekdays, one lot per shipment. Parts are consumed from line-side stock.
- **Reordering.** At the end of each weekday, if warehouse + line-side + on-order stock is at or below the reorder point, an order is placed up to the reorder point plus 28 days of recent demand (trailing 14-day average). The reorder point is sized from launch demand (weeks 1 to 4) x (lead time + 12 days), so it falls behind as volume ramps.
- **Delivery.** A shipment arrives on its expected date plus any delay, moved to a weekday. Delays and short shipments follow the supplier behaviour above.
- **Replenishment to the line.** Each weekday at 06:00 kitters move parts from the warehouse to line-side, up to a target of 2 days of demand. Each station has a pieces-per-day kitting cap, and kitters work down the kit list in order, so when the cap binds the last parts on the list are the ones that run empty at the line while the warehouse still has stock.
- **Consumption and blocking.** A job can start only when every part in its BOM is available line-side. Parts come from the oldest lot first (FIFO). If one is missing, the job waits for the next top-up.
- **Emergency buy.** Only Ridgeline parts are eligible. If a Ridgeline part has blocked work on 2 working days in a row *and the warehouse has nothing left to kit* (a part blocked only because kitters ran out of time is not a supply problem), the spot-buy distributor ships a new lot: 2-day lead time, 7 days of recent demand, lot ID prefixed `SUB`.
- **Substitute lot effect.** If any of a drone's Motor & Prop fasteners (motor mount, prop nut, thread locker) came from a spot-buy lot, its first-pass failure rate at Motor & Prop is 22% instead of 2.5%, and 75% of those failures are coded `MTR-LOOSE-FASTENER`.
- **Traceability.** `drone_part_lots` records, for every drone and every part installed, the lot it came from (the lot of the first unit, if a drone's quantity spans two lots).
- **What is planted and what emerges.** Planted: Ridgeline runs late and short on shipments expected in weeks 9 to 11. Everything else follows from the simulation: when the fasteners run out, when the spot-buy lot is used, which drones carry it, when the defect spike happens, which parts end up starved at the line. The kitting cap is 200 pieces a day per station (tuned: at 175 Wing Assembly, which has 22 pieces per drone, becomes a second bottleneck; at 250 nothing is starved).

## The story: a new line scaling faster than its support systems

One root cause drives everything: weekly releases ramp up (starting at 18 drones a week) faster than planning, capacity and supply can follow. All data stories, and all planted data errors, hang off this.

| Weeks | What happens | What the data shows |
|---|---|---|
| 1-8 | Launch. Releases start at 18 a week and climb. Reorder points are sized from launch-volume demand. | Healthy yield, short queues, comfortable stock |
| 9-11 | The hardware/fasteners supplier ships late and short as volume rises. Fastener stock runs thin. Substitute fastener lots are issued against the wrong part numbers. | Late and short receipts. **Negative inventory** on fastener parts. The substitute lot is bought from a spot-buy distributor and arrives with its own lot ID. |
| 12-15 | The line runs on the substitute lot, and loose-fastener failures spike at Motor & Prop (22% on drones that got the substitute lot, against 2.5% otherwise). Inspectors are swamped, and relabelled rework units get mistyped serials. The supplier's catch-up shipments over-ship. | Yield dip at Motor & Prop. **Missing defect codes**, **orphan inspections** and **over-receipts** cluster here. `drone_part_lots` records which drones got the substitute lot. |
| 12-26 | Rework returns to the line in bursts and releases keep climbing past what Avionics can handle. A queue builds in front of it; completions plateau while starts keep rising. WIP piles up and work orders get re-keyed by hand. Drones wait at Avionics, so they reach Final Test and shipping later. | Queue wait at Avionics grows. Output flattens. Lead time from first station to shipped grows. Dwell time from test pass to shipped stays normal, because the delay is upstream. **Duplicate work orders** and **end-before-start** errors cluster at Avionics. |
| 16-26 | Reorder points are still sized for launch volume while weekly releases climb toward almost double that, so usage outgrows the stock rules. Long-lead parts run thinnest, because they have the longest wait for the next delivery. Replenishment from warehouse to the line also lags the ramp. | About half the parts look at risk of running out before their next delivery, mostly long-lead suppliers. Ridgeline is still the least reliable supplier, so a risk measure that plans for a bad delivery puts more of its parts on the list. For some parts the warehouse looks fine while `LINE_SIDE` stock is empty. |

The weeks in this table are targets. The shortage, the spot-buy and the defect spike now emerge from the simulated supply chain, so the measured weeks may differ by a week or two. This table is updated to the measured values once the simulation is tuned.

### Measured (default seed 42)

The simulation was tuned and checked across seeds; these are the real events in the default dataset.

- Ridgeline's fastener shipments expected on 9 March (week 10) arrive 8 to 11 days late, and two of the three are short (139 of 212 and 49 of 106).
- The thread locker hits zero total stock in weeks 11 and 12 (1 and 3 days); the other fasteners run down to an empty warehouse in week 10. Emergency lots are ordered on 16 and 18 March (week 11) and arrive on 18 and 20 March.
- 58 drones carry a substitute-lot fastener, in weeks 11, 12, 14 and 15 (a double hump: older regular stock is used first). They fail first inspection at Motor & Prop 20.7% of the time against 2.2% for the rest, and weekly Motor & Prop yield dips to 88-91% in weeks 11-12 and 84-88% in weeks 14-15.
- Avionics wait grows from about 11 hours (weeks 1-10) to 36 (week 12), 78 (week 14), 271 (week 20) and 427 (week 26). Wing Assembly's wait peaks at about 110 hours; the other stations stay under 10.
- Ridgeline has the lowest on-time-in-full rate (0.75 against 0.87 to 0.91).
- Of 738 drones released, 620 passed Final Test, 609 shipped, 6 are packed and waiting for the next batch, and 5 are not yet packed. The other 118 are still on the line at the extract, mostly queued at Avionics.
- Lead time from first station to shipped grows from 3.7 days (drones shipped in weeks 4-9) to 19.6 days (weeks 20-25), while dwell from test pass to shipped stays at about 1.9 days. The delay is upstream. Caveat for any analysis: lead time is only measurable for drones that have shipped, so the longest waits (drones still stuck at Avionics) are missing from the recent weeks and the real growth is understated.
- Across seeds 0 to 5, the first emergency buy for a spike fastener is placed in weeks 10 to 13 in every seed, and substitute-lot drones fail more than three times as often as the rest.
- Supply risk at the extract: about 21 of 40 parts look at risk (days of stock less than days to the next delivery), mostly parts from long-lead suppliers (Northgate, Meridian, Vector), because reorder points sized for launch volume fall behind a ramp that nearly doubles usage. Only 5 of Ridgeline's 8 parts are on the list when lateness is averaged. A measure that plans for a bad delivery (each supplier's 90th-percentile lateness, not the average) puts about half of Ridgeline's parts at risk against about 38% of the others, because its bad case is the week 9-11 crisis. The list is long either way, so the app ranks parts by days of cushion left and puts the most urgent first.

### What an analysis should be able to find

1. Late and short hardware shipments, then thin fastener stock, then a defect spike at Motor & Prop a few weeks later.
2. A queue at Avionics that grows as releases pass its capacity, made worse by rework bursts.
3. A ranked list of parts at risk of running out: mostly long-lead parts, because reorder points sized for launch volume fall behind the ramp, with Ridgeline's parts moving up when risk is measured against a bad delivery.
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
| `receiving` | one row per shipment (one supplier lot each, with the shipping supplier) | ERP purchase order receipts |
| `work_orders` | drone x station | MES work order / operation records |
| `inspections` | one inspection attempt | MES / quality system, traceable by serial number |
| `drone_part_lots` | drone x part installed | traceability system: which lot went into which drone |
| `finished_goods` | one row per drone that passed Final Test | ERP / warehouse: packed and shipped status |

## Planted data errors

The generator corrupts a small number of rows and records exactly which ones in an answer key (`data/answer_key.json`), so each check can be scored on what it caught, missed, or wrongly flagged. Errors are placed by the story, not scattered randomly: each window is found from the data (the outage, the spike, the queue building), so the errors land where the story is wherever it falls.

| Planted error | Rows | Table | Where it lands (event window, measured for seed 42) | What it looks like | Answer-key record |
|---|---|---|---|---|---|
| Negative inventory | 8 | inventory_snapshots | Spike-fastener rows with stock, from the first empty warehouse to 5 days after the last emergency lot arrives (11-25 March, 50 eligible) | Sign of on_hand flipped | `date\|part\|location` |
| Missing defect code | 4 | inspections | First-attempt failures at Motor & Prop while substitute-lot drones are inspected (19 March to 14 April, 13 eligible) | Code is NULL, empty, or whitespace (a mix) | inspection_id |
| Orphan inspections | 3 | inspections | Rework re-inspections at Motor & Prop in the same window (13 eligible) | Serial changed to `DF-9...`, a drone that does not exist | inspection_id |
| Over-receipt | 3 | receiving | Ridgeline regular lots received in the 3 weeks after the first emergency lot (11 eligible) | qty_received is 20 to 50% above qty_expected | shipment_id |
| Duplicate work orders | 12 | work_orders | Avionics jobs from the first week its average wait exceeds 24 hours (week 12 on, 393 eligible) | A re-keyed copy: new wo_id, same drone, station and times | wo_id of the copy |
| End before start | 8 | work_orders | Completed Avionics jobs in the same window (391 eligible, never a job that was duplicated) | end_ts 30 minutes to 4 hours before start_ts | wo_id |

Counts are lower if a window holds fewer eligible rows (tests confirm every error is planted in other seeds too). After planting, the only anomalies in the data are the planted ones: tests compare the corrupted tables with the clean ones and confirm nothing else differs.

The answer key records the copy's wo_id for duplicates, so the Phase 3 check should report every work order in a duplicated group except the earliest.

Not planted: unknown part in receiving (same pattern as orphan inspections).

Guard checks (nothing planted; each should flag zero rows): status vs. end timestamp on work orders; every `lot_id` in `drone_part_lots` exists in `receiving`; every serial in `drone_part_lots` exists in `work_orders`; every drone in `finished_goods` has a passing Final Test inspection; test passed <= packed <= shipped.

## Data quality checks

25 checks, each one SQL file in `sql/checks/` with a severity, a category and a description. A check returns one row per offending record.

| Category | Checks | Purpose |
|---|---|---|
| planted | 6 | One per planted error; scored against the answer key |
| guard | 5 | Relationships nothing was planted into (status vs. end time, lot and serial references, finished goods passed test and are in time order); should flag nothing |
| sanity | 13 | Standard validation rules (unknown part, station and supplier IDs; allowed values for status, result, attempt and location; duplicates; required fields; a passing inspection with a defect code); should flag nothing here |
| operational | 1 | A warning, not a data error: shipments still in transit more than 3 days after their expected date; not scored |

Scoring: for every scored check, rows flagged that are not in the answer key count as false positives, so a perfect run means every planted error caught and nothing else flagged. The answer key, the results per check and the flagged records are stored in the database (`dq_answer_key`, `dq_results`, `dq_flagged`) so the app can show them. Result on the default dataset: 38 of 38 planted errors caught, 0 missed, 0 false positives across 24 scored checks.

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
