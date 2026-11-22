import argparse
import csv
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
import numpy as np
from forecast import CITIES, CAPACITY, BASE_TARIFF, SCENARIOS, PACK, build
from dispatch import (solve, R,G,I,C,D,E,F,S,B,P,W, GRID_EFF, DC_EFF, BAT_EFF,
                      PACK_EFF, IDLE, PPA, DISCOM, WEAR)
from report import render

def response(price, base):
    slope = np.array([5.0, 3.6, 2.8, 3.5])
    return 1.28 / (1 + .28 * np.exp(slope * (price / base - 1)))

def prices(pred, cap, anchor, base, feeder):
    tariffs = []
    for y, limit in zip(pred, feeder):
        best = -np.inf
        selected = anchor
        for p in np.linspace(.8*anchor,1.2*anchor,41):
            demand = y[:4]*response(p,base)
            available = min(.95*cap,limit)*.94
            sales = min(demand.sum(), available)
            cost = min(DISCOM,y[5]) + 1.65
            score = (p-cost)*sales - 12*max(0,.93*y[:4].sum()-sales)
            if score > best:
                best, selected = score, p
        tariffs.append(selected)
    return np.array(tariffs)

def nominate(supply, demand):
    local = np.minimum(supply,demand)
    deficit = np.maximum(demand-local,0)
    excess = supply-local
    transfer = np.minimum(excess.sum(axis=0),deficit.sum(axis=0))
    return (local + deficit*transfer/np.maximum(deficit.sum(axis=0),1e-9)
            + excess*(1-transfer/np.maximum(excess.sum(axis=0),1e-9)))

def simulate(scenario, seed, days):
    started = perf_counter()
    data = [build(i,seed,days,scenario) for i in range(5)]
    f, a = (np.stack([item[j] for item in data]) for j in [0,1])
    for values in [f,a]:
        values[:,:,4] = nominate(values[:,:,4],values[:,:,:4].sum(axis=2)/.94)
    rows, bids, validation = [], [], []
    for i, city in enumerate(CITIES):
        cap, base = CAPACITY[i], BASE_TARIFF[i]
        soh = data[i][3]
        stock = int(cap*.20*soh/PACK)
        state = (cap*.30*soh*.50, int(np.ceil(stock*.55)))
        anchor = base
        for j, field in enumerate(["retail","ride_hailing","logistics","swaps","renewables","iex"]):
            validation.append(dict(city=city,target=field,model_wape=data[i][4][j],
                                   weekly_wape=data[i][5][j]))
        for day in range(days):
            sl = slice(day*24,day*24+24)
            pred, seen = f[i,sl].copy(), a[i,sl].copy()
            peak = (np.arange(24)>=16)&(np.arange(24)<=22)
            feeder = np.full(24, cap*[.69,.63,.68,.65,.62][i])
            if scenario == "Feeder squeeze":
                feeder[peak] *= .48 if i < 3 else .64
            if scenario == "Heatwave":
                pred[peak,5] += 1.4
                seen[peak,5] += 2.5
            tariff = prices(pred,cap,anchor,base,feeder)
            elastic = np.stack([response(p,base) for p in tariff])
            expected = pred[:,:4]*elastic
            actual = seen[:,:4]*elastic
            requested = np.rint(actual[:,3]/PACK)
            plan = solve(expected[:,:3].sum(axis=1),expected[:,3]/PACK,pred[:,4],
                         pred[:,5],cap,feeder,soh,state)
            limit = np.minimum(10, DISCOM+.9*(expected.sum(axis=1)>.8*feeder))
            booked = plan[:,I]*(seen[:,5]<=limit)
            for h in range(24):
                for q in range(4):
                    bids.append(dict(scenario=scenario,city=city,day=day+1,hour=h,minute=15*q,
                                     bid_mw=plan[h,I],block_mwh=plan[h,I]/4,
                                     limit_inr_kwh=limit[h],clearing_inr_kwh=seen[h,5],
                                     accepted_mwh=booked[h]/4))
                demand = expected[h:,:3].sum(axis=1)
                demand[0] = actual[h,:3].sum()
                swaps = expected[h:,3]/PACK
                swaps[0] = requested[h]
                available = pred[h:,4].copy()
                available[0] = seen[h,4]
                v = solve(demand,swaps,available,pred[h:,5],cap,feeder[h:],soh,state,
                          booked[h:],True)[0]
                ready, fills, served = (int(round(v[k])) for k in [P,F,S])
                sold = v[E]+served*PACK
                revenue = sold*1000*tariff[h]
                cost = 1000*(seen[h,4]*PPA+v[G]*DISCOM+v[I]*seen[h,5]+
                             WEAR*(v[C]+v[D])/2+.24*fills*PACK+.85*sold)+cap*1050
                source = v[R]+v[G]+v[I]
                distribution = source*(1-GRID_EFF)
                conversion = v[E]*(1/DC_EFF-1)+fills*PACK*(1/PACK_EFF-1)
                stationary = v[C]*(1-BAT_EFF)+v[D]*(1/BAT_EFF-1)
                idle = state[1]*PACK*IDLE/PACK_EFF
                loss = distribution+conversion+stationary+idle
                delta = v[B]-state[0]+(ready-state[1])*PACK
                assert abs(source-sold-loss-v[W]-delta)<1e-5
                assert served<=state[1]-math.ceil(.05*stock)+1e-5 and served<=requested[h]
                assert ready >= math.ceil(.05*stock) and fills<=stock-state[1]
                assert v[B]>=.05*cap*.30*soh-1e-6 and min(v[C],v[D])<1e-5
                assert source<=feeder[h]+1e-5 and .8*anchor-1e-8<=tariff[h]<=1.2*anchor+1e-8
                reference = pred[h,:4].sum()
                credit = min(v[E],pred[h,:3].sum())+min(served*PACK,pred[h,3])
                timestamp = datetime(2025,1,1)+timedelta(days=day,hours=h)
                rows.append(dict(scenario=scenario,city=city,time=timestamp.isoformat(),
                    hour=h,forecast_mwh=reference,forecast_dc_mwh=pred[h,:3].sum(),
                    forecast_swaps=pred[h,3]/PACK,requests_mwh=demand[0]+requested[h]*PACK,
                    requested_swaps=int(requested[h]),served_dc_mwh=v[E],served_swaps=served,
                    sold_mwh=sold,credited_mwh=credit,ppa_mwh=seen[h,4],renewable_mwh=v[R],
                    curtailed_mwh=seen[h,4]-v[R],discom_mwh=v[G],iex_mwh=v[I],input_mwh=source,
                    charge_mwh=v[C],discharge_mwh=v[D],soc_mwh=v[B],packs_charged=fills,
                    ready_packs=ready,reserve_packs=math.ceil(.05*stock),soh=soh,grid_limit_mw=feeder[h],
                    spill_mwh=v[W],distribution_loss=distribution,conversion_loss=conversion,
                    stationary_loss=stationary,idle_loss=idle,loss_mwh=loss,price_inr_kwh=tariff[h],
                    previous_day_tariff=anchor,swap_price_inr=tariff[h]*40,revenue_inr=revenue,
                    cost_inr=cost,ebitda_inr=revenue-cost,temperature_c=data[i][2][0][day*24+h],
                    cloud_fraction=data[i][2][1][day*24+h],wind_ms=data[i][2][2][day*24+h]))
                state = v[B],ready
            anchor = tariff.mean()
    return rows,bids,validation,perf_counter()-started

def metrics(rows):
    total = lambda field: sum(r[field] for r in rows)
    return dict(reliability=100*total("sold_mwh")/total("forecast_mwh"),
                capped_service=100*total("credited_mwh")/total("forecast_mwh"),
                fulfillment=100*total("sold_mwh")/total("requests_mwh"),
                loss=100*total("loss_mwh")/total("input_mwh"),
                margin=100*total("ebitda_inr")/total("revenue_inr"),
                ebitda=total("ebitda_inr"), revenue=total("revenue_inr"),
                curtailment=total("curtailed_mwh"),sold=total("sold_mwh"))

def write_csv(path, rows):
    with path.open("w",newline="",encoding="utf-8") as out:
        writer=csv.DictWriter(out,fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

def main():
    parser=argparse.ArgumentParser(description="VYOMA hourly network simulation")
    parser.add_argument("--days",type=int,default=2,choices=range(1,32),metavar="1..31")
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--scenario",choices=["all",*SCENARIOS],default="all")
    parser.add_argument("--out",type=Path,default=Path(__file__).parent/"results")
    args=parser.parse_args()
    if args.seed<0:
        parser.error("seed must be nonnegative")
    args.out.mkdir(parents=True,exist_ok=True)
    all_rows,all_bids,summaries,timings = [],[],[],{}
    for name in SCENARIOS if args.scenario=="all" else [args.scenario]:
        rows,bids,validation,seconds=simulate(name,args.seed,args.days)
        for label in ["Network",*CITIES]:
            part = rows if label=="Network" else [r for r in rows if r["city"]==label]
            summaries.append(dict(scenario=name,city=label,**metrics(part)))
        all_rows.extend(rows)
        all_bids.extend(bids)
        timings[name]=round(seconds,3)
        print(f"{name} | {len(rows)} cluster-hours | {seconds:.2f} s",flush=True)
    for file, records in [("dispatch",all_rows),("day_ahead_bids",all_bids),
                          ("scorecard",summaries),("forecast_validation",validation)]:
        write_csv(args.out/(file+".csv"),records)
    meta=dict(seed=args.seed,days=args.days,seconds=timings)
    (args.out/"run.json").write_text(json.dumps(meta,indent=2))
    render(args.out/"dashboard.html",all_rows,summaries,meta)

if __name__=="__main__":
    main()
