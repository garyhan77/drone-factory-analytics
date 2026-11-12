# The simulated factory

Design spec for the synthetic data. The project tells one story: a supplier's delivery is late, a part runs out, the line buys
a substitute lot, that lot fails inspection far more often, and the lot number identifies exactly which drones are affected.

## Questions the project answers

1. Which delivery was late, and what did it cause?
2. Which lots are failing inspection far more often than the rest?
3. Which drones contain the bad lots, and where are they now?

## Line

Five stations in a fixed order: Airframe, Wing Assembly, Motor & Prop, Avionics, Final Test. Two shifts, 06:00 to 22:00,
Monday to Friday. Drones are released at a steady 20 a week for 12 weeks (240 drones), which is below every station's
capacity, so there are no queues and the only thing that goes wrong is the supply chain.

| Station | Code | Lanes | Typical cycle | Inspection fail rate |
|---|---|---|---|---|
| Airframe | AFL | 3 | 3.0 h | 3.0% |
| Wing Assembly | WNG | 3 | 3.5 h | 3.5% |
| Motor & Prop | MTR | 2 | 2.0 h | 2.5% (50% on drones with a substitute-lot prop nut) |
| Avionics | AVN | 2 | 4.4 h | 5.0% |
| Final Test | FNT | 3 | 3.0 h | 4.0% |

A failed inspection adds 1 to 2.5 hours of rework, and a second inspection then passes.

## Stack

Python for data generation and the app, PostgreSQL for storage and all SQL, Streamlit for the dashboard.

## Scale

12 weeks of history (5 January to 27 March 2026), 12 parts, 8 suppliers, 10 tables, 240 drones.

## Parts and suppliers

| Part ID | Part | Supplier | Unit cost | Per drone |
|---|---|---|---|---|
| AFL-001 | Carbon fibre sheet | Northgate Composites | $85 | 4 |
| AFL-002 | Epoxy resin kit | Summit Polymers | $35 | 1 |
| WNG-001 | Wing spar | Northgate Composites | $95 | 2 |
| WNG-002 | Servo | Cobalt Motion | $28 | 4 |
| MTR-001 | Brushless motor | Cobalt Motion | $120 | 2 |
| MTR-002 | Propeller | Cobalt Motion | $45 | 2 |
| MTR-003 | Motor mount | Cobalt Motion | $14 | 2 |
| MTR-004 | Prop nut | Ridgeline Hardware | $1.5 | 2 |
| MTR-005 | Speed controller | Meridian Electronics | $55 | 2 |
| AVN-001 | Flight controller | Vector Avionics | $310 | 1 |
| AVN-002 | Battery pack | Meridian Electronics | $480 | 1 |
| FNT-001 | Shipping crate | Granite Packaging | $85 | 1 |

Ridgeline Hardware is the unreliable supplier and supplies only the prop nut. The eighth supplier, the spot-buy distributor,
is used for emergency buys only and supplies none of the regular parts.

- Normal supplier behaviour: 8% of shipments late by 1 to 3 days, 3% short.
- Ridgeline, on shipments expected in weeks 4 to 6: 95% late by 8 to 14 days and 60% short (40 to 70% of the quantity).
- Reorder point = launch demand x (lead time + 12 days), except Ridgeline's prop nut, which is stocked thin (4 days). Orders go up to 28 days of recent demand, or 7 days for the prop nut, which is ordered little and often.
- Finished drones are packed 4 to 24 working hours after passing Final Test and ship in one batch each weekday at 16:00. The data is extracted at 14:00 on the last Friday.

## How supply and inventory work

Supply and production are one coupled simulation. Stock that runs out delays work, so a shortage shows up in the data as a delay and then as defects.

- **Starting stock.** Each part starts with warehouse and line-side stock, recorded in `receiving` as one pre-launch shipment per part, so every lot used in traceability has a matching shipment.
- **Two stock locations per part.** Shipments arrive at the warehouse on weekdays, one lot per shipment. Parts are consumed from line-side stock.
- **Reordering.** At the end of each weekday, if warehouse + line-side + on-order stock is at or below the reorder point, an order is placed.
- **Delivery.** A shipment arrives on its expected date plus any delay, moved to a weekday.
- **Replenishment to the line.** Each weekday morning the line-side shelf is topped up from the warehouse to 2 days of demand.
- **Consumption and blocking.** A job can start only when every part in its bill of materials is on the line-side shelf. Parts come from the oldest lot first. If one is missing, the job waits for the next top-up.
- **Emergency buy.** Only Ridgeline parts are eligible. If the prop nut blocks work on 2 working days in a row and the warehouse has nothing left, the spot-buy distributor ships a new lot: 2-day lead time, 7 days of demand, lot ID prefixed `SUB`.
- **Substitute lot effect.** If a drone's prop nut came from a spot-buy lot, its failure rate at Motor & Prop is 50% instead of 2.5%, and 75% of those failures are coded `MTR-LOOSE-FASTENER`.
- **Traceability.** `drone_part_lots` records, for every drone and every part installed, the lot it came from.
- **What is set and what emerges.** Set: Ridgeline runs late and short in weeks 4 to 6, and the 50% failure rate on substitute lots. Everything else follows from the simulation: when the prop nut runs out, when the emergency buy happens, which drones carry the lot and how many of them fail.

## What the data shows (default seed 42)

- Ridgeline's prop nut delivery due 12 February arrives 11 days late. It is late on 1 of its 4 deliveries.
- The prop nut runs out and the line buys 2 emergency lots from the spot-buy distributor. 40 drones carry them, 20 per lot.
- 40% and 55% of the drones that received those lots failed inspection at Motor & Prop, against about 5% for a typical lot.
- All 40 drones have already shipped, so a recall would reach customers.
- A regular lot can look elevated if it went into the same drones as an emergency lot, which is why lots are flagged only at 20% or more (the regular Motor & Prop lots sit around 15%).

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

## Metrics

Four views in total; definitions are in the comments of `sql/metrics/`.

| Metric | Definition |
|---|---|
| Deliveries | One row per shipment that has arrived: days late (0 when on time or early), whether it was short, and whether it was an emergency buy. Pre-launch shipments are excluded |
| Lot failure rate | Per lot, the share of the drones it went into that failed inspection at the station where it was installed |
| Recall scope | Per lot, every drone containing it and whether each has shipped, is packed, or is still in the line |

## README

First person and plain, with a short "why this project" paragraph in my own words about drones and Zipline's mission, public facts only. The README states that the data is synthetic and that the story's causal links are set by the generator.
