# VYOMA
## India's Intelligent EV Energy Orchestration Network

Open **results/dashboard.html** in a browser to explore the completed simulation. Select a scenario and metro to inspect demand, delivered energy, ready packs, reserves, tariffs and EBITDA. The dashboard works offline.

### Run

Use Python 3.11 or 3.12. From the extracted VYOMA folder:

```sh
python -m pip install -r requirements.txt
python run.py
python verify.py
```

The default run uses seed 42, four scenarios and two consecutive operating days. A longer independent run can use a separate output directory:

```sh
python run.py --scenario "Feeder squeeze" --days 7 --seed 817 --out week
python verify.py week
python benchmark.py
```

### Decision model

At 18:00 a fleet may need both an available charger and a fully charged replacement pack. A spare megawatt cannot fulfil a swap if the last ready pack went out at 17:00. VYOMA therefore tracks three separate resources at each metro: feeder headroom, stationary stored energy and integer ready packs. A pack charged during an hour becomes eligible for service the following hour.

1. **Forecast.** Fit six multi-output ridge regression targets per metro on hourly synthetic observations from January 2020 through December 2024. Demand is split into retail, ride-hailing and logistics charging plus swap energy. Two further targets estimate renewable generation and IEX price. Features capture heat above 29°C, cloud cover, daylight, wind speed squared, weekday and city-specific morning and evening peaks. The final 90 days form a chronological holdout before refitting on all five years. Validation includes weather forecast errors and reports weighted absolute percentage error alongside the same hour one week earlier. Future weather outlooks are noisy proxies for weather forecasts. Weather residuals and the customer response curve are scenario inputs.
2. **Nominate renewable energy.** Each metro keeps its local nomination up to expected demand. The network allocates transferable surplus in proportion to other metros’ deficits. Unplaced volume stays with its originating contract. The same allocation rule runs on current telemetry at execution. Aggregate entitlements are conserved. This assumes fungible open-access contracts with sufficient transfer rights. Each receiving feeder remains physically constrained.
3. **Post customer prices.** Evaluate 41 prices spanning 80–120% of the previous day's mean posted tariff. For segment j, requests at tariff p equal base demand times 1.28 / [1 + 0.28 exp(kⱼ(p/p₀ − 1))], with k = (5.0, 3.6, 2.8, 3.5). The initial tariff p₀ is a fixed local competitive reference. Score candidates by estimated contribution on serviceable energy minus ₹12 per kWh of forecast service below 93%. The pricing stage uses feeder headroom and the cheaper forecast grid offer as a marginal-cost proxy. The dispatch stage resolves the physical schedule. A swap costs 40 times the posted per-kWh price.
4. **Bid day ahead.** Solve the 24-hour dispatch plan for each cluster. Submit one simulated price–quantity pair for each quarter-hour, repeating the hourly nominated MW. The limit equals the ₹6.65/kWh DISCOM alternative, rising by ₹0.90 when expected demand exceeds 80% of feeder capacity. A block clears in full at its simulated clearing price if that price is within the limit. Cleared IEX volumes are fixed for intraday execution. Four blocks share one hourly clearing price in this case. No exchange credentials or live orders are involved.
5. **Dispatch hourly.** Replace the current forecast with measured requests and available renewable power. Re-solve the remaining hours of that delivery day, execute the first decision, carry actual inventory forward and repeat. The executed hour requires whole packs for refills and swaps. Later hours use continuous pack equivalents. DISCOM purchases, stationary cycling, pack refills and renewable curtailment provide recourse. Closed-day inventory floors prevent borrowing tomorrow's stock to improve today's results.

### Installed network and assumptions

| Metro | Combined MW | DC MW | Swap MW | Stationary MWh | Pack MWh | Feeder MW | Initial ₹/kWh |
|---|---:|---:|---:|---:|---:|---:|---:|
| Delhi NCR | 300 | 180 | 120 | 90 | 60 | 207 | 11.0 |
| Mumbai MMR | 270 | 162 | 108 | 81 | 54 | 170.1 | 11.5 |
| Bengaluru | 240 | 144 | 96 | 72 | 48 | 163.2 | 10.5 |
| Hyderabad | 210 | 126 | 84 | 63 | 42 | 136.5 | 10.8 |
| Chennai | 180 | 108 | 72 | 54 | 36 | 111.6 | 11.2 |
| **Network** | **1,200** | **720** | **480** | **360** | **240** | **788.4** | |

Metro allocations, storage split and feeder values are design assumptions. The brief supplies the aggregate installed assets, reference sourcing mix and KPI baselines. The simulation operates 24 hours per day in IST. Historical renewable contract generation is scaled to 35% of estimated gross historical demand, using 94% blended delivery efficiency for sizing. Actual sourcing shares change with weather, curtailment and demand.

| Dispatch input | Value or treatment |
|---|---|
| Contracted renewables | ₹3.25/kWh on all nominated generation, including curtailment |
| DISCOM and IEX | DISCOM ₹6.65/kWh, up to 48% of cluster MW. IEX quantities up to 42%. Both share the feeder with renewables. |
| Network and chargers | 98.4% distribution efficiency, 95.9% DC conversion, 95.6% pack recharge efficiency |
| Stationary storage | 95.8% efficiency each way (91.8% round trip). Shared inverter capped at 12% of cluster MW × state of health. |
| Health and wear | Simulated health declines by 0.8 percentage points across the history, with different starting ages per city. Latest health derates stationary capacity, inverter power and serviceable pack counts. Health is fixed for each short operating run. |
| Inventory | Standard usable 40 kWh pack. The reserve is rounded up to 5% of serviceable packs. Idle maintenance tops up 0.012% of opening ready energy per hour. Returned packs re-enter the depleted pool. |
| Emergency reserve | Withhold 5% of DC power, swap charging power, usable stationary energy and serviceable pack stock. Each hour's swaps draw only from opening ready stock above reserve. |
| Inventory boundaries | Stationary energy starts at 50% of usable capacity. Ready stock starts at 55%, rounded up. Each delivery day closes at or above both opening design levels. |
| Operating costs | ₹0.65 per stationary kWh of half-throughput, ₹0.24 per kWh packed, ₹0.85 per kWh sold, plus ₹1,050 per installed MW-hour for site, staff and network overhead. |
| Market context | The ₹3.80/kWh synthetic IEX intercept is adjusted for weather, evening demand and noise. IEX reported an FY25 DAM clearing price of ₹4.47/kWh. Procurement parameters and customer tariffs are illustrative landed-cost assumptions. |

[Indian Energy Exchange market snapshot and block convention](https://www.iexindia.com/market-data/day-ahead-market/market-snapshot) · [IEX FY25 market release filed with NSE](https://nsearchives.nseindia.com/corporate/IEX_04042025081458_Signed_IEX_Media_Release_Power_Market_Update_Mar25.pdf)

### Dispatch formulation

Quantities below are MWh per one-hour interval except ready inventory P, refills F and swaps S, which count packs. Let A be grid-side input from used renewables, DISCOM and cleared IEX, E be customer DC output, C and D be stationary bus-side charge and discharge, B be stored energy and W be spilled bus energy.

- Bus balance: 0.984 A + D = E/0.959 + C + 0.04(F + 0.00012 P_open)/0.956 + W.
- Stationary balance: B_close = B_open + 0.958 C − D/0.958.
- Pack balance: P_close = P_open + F − S. Enforce S ≤ P_open − reserve and F ≤ serviceable stock − P_open.
- Service: E ≤ charging requests and 95% of DC nameplate times conversion efficiency. S ≤ swap requests. Pack charging power and source imports have their own hourly upper bounds.
- Objective: minimize purchase cost plus throughput wear and a small spill penalty, less service credits of ₹45 per delivered DC kWh and ₹48 per delivered swap kWh. These priority weights affect scheduling only. Customer revenue uses posted tariffs. The renewable contract is a sunk take-or-pay cost within dispatch and appears in full in the financial ledger.

Every executed hour checks energy conservation, pack and stationary reserves, tariff bounds and feeder limits. The exported audit reconciles purchased energy with delivery, four loss components, spill and changes in both storage balances. Unused renewable nominations appear separately as curtailment.

### Decision scorecard

Reliability uses delivered DC MWh plus completed swaps × 0.04 MWh, divided by pre-price forecast demand in the same units. The denominator stays fixed when prices change. The capped-service diagnostic additionally limits credit to each hour's forecast per service. Request fulfilment instead measures service against realized demand after customers respond to price. The loss rate divides distribution, conversion, stationary cycling and idle top-up losses by admitted source energy. EBITDA margin equals revenue less the modeled purchase and operating costs, divided by revenue. The network margin is revenue-weighted. The dashboard separately checks the weakest metro against the strict 12% floor.

| Two-day simulation | Network reliability | Network loss | Lowest metro EBITDA margin |
|---|---:|---:|---:|
| Reference | 90.82% | 6.00% | 27.01% |
| Heatwave | 89.80% | 5.95% | 25.03% |
| Monsoon lull | 90.82% | 5.92% | 22.42% |
| Feeder squeeze | 84.65% | 6.00% | 28.89% |
| Case targets | ≥89.70% | ≤8.00% | >12.00% |

Against the supplied 78% reliability and 10% loss baselines, the reference run delivers 12.82 percentage points of additional reliability and 4.00 points of lower losses. These comparisons use the brief's historical benchmarks. They are simulated outcomes under assumed equipment efficiencies, demand response and available supply.

Heatwave adds 9°C and an evening market shock. The network narrowly meets its reliability target while Hyderabad and Chennai miss it. Monsoon reduces wind by 3 m/s and raises cloud fraction by 0.46, compressing margins through replacement procurement. Feeder squeeze removes 52% of evening feeder capacity in the three largest metros and 36% in the other two. A higher margin in that scenario coincides with weaker service. Financial performance alone would reward the wrong decision.

Reference revenue is ₹23.38 crore over 48 hours and modeled EBITDA is ₹6.83 crore. The network has approximately ₹4.02 crore of additional operating-cost headroom before its aggregate margin reaches 12% at the same sales volume. Individual metro headroom is EBITDA minus 12% of that metro's revenue. This is an operating case for existing assets. It does not establish capital payback or annual realized performance.

### Scaling and outputs

Renewable nomination takes one pass across clusters for each delivery hour. After nomination each cluster has its own dispatch problem, allowing independent deployment by metro. Each 24-hour plan has 264 decision variables and 168 constraint rows. Only current-hour refill and swap counts require integer decisions during execution. The included benchmark repeats the five metro profiles at 5, 25 and 100 logical clusters, timing three sequential day-ahead batches at each size. The measured medians on the packaging machine were approximately 0.02, 0.09 and 0.34 seconds. These timings exclude data generation, bid settlement and hourly recourse. Full four-scenario execution timings are in run.json.

| File in results | Contents |
|---|---|
| dashboard.html | Self-contained scenario dashboard with network and metro filters |
| dispatch.csv | Hourly requests, sales, reserve, energy flows, four loss components and P&L |
| day_ahead_bids.csv | Quarter-hour buy quantities, limits, clearing prices and accepted energy |
| scorecard.csv | Network and metro performance, conservative service credit and request fulfilment |
| forecast_validation.csv | Held-out WAPE by city and target against weekly persistence |
| scaling.csv | Measured solve timings across network sizes |
| run.json | Seed, duration and full simulation runtime per scenario |

Each scenario uses the same underlying random draws to isolate the modeled shock. All operating data and validation results are synthetic. The model assumes pooled metro inventory, fixed-size usable packs, no intercity pack trucking, no within-hour queues and no partial market clearing. Field validation would require metered feeder losses, observed price response, local open-access rights and asset-level availability.
