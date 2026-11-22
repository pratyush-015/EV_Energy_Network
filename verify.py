import csv
import math
import sys
from collections import defaultdict
from pathlib import Path
from forecast import CITIES, CAPACITY, PACK

def verify(root):
    def read(name):
        with (root/(name+".csv")).open(newline="") as stream:
            return list(csv.DictReader(stream))
    def near(x,y):
        if not math.isclose(x,y,abs_tol=1e-5,rel_tol=1e-9):
            raise ValueError(f"{x} differs from {y}")
    accepted=defaultdict(float)
    for bid in read("day_ahead_bids"):
        energy=float(bid["block_mwh"])
        near(energy,float(bid["bid_mw"])/4)
        clear=float(bid["clearing_inr_kwh"])<=float(bid["limit_inr_kwh"])
        near(float(bid["accepted_mwh"]),energy*clear)
        accepted[bid["scenario"],bid["city"],int(bid["day"]),int(bid["hour"])]+=energy*clear
    groups=defaultdict(list)
    for row in read("dispatch"):
        groups[row["scenario"],row["city"]].append(row)
    scores={(r["scenario"],r["city"]):r for r in read("scorecard")}
    for (scenario,city),rows in groups.items():
        cap=CAPACITY[CITIES.index(city)]
        health=float(rows[0]["soh"])
        stock=int(cap*.20*health/PACK)
        ready=math.ceil(.55*stock)
        soc=cap*.15*health
        for t,r in enumerate(rows):
            v=lambda k:float(r[k])
            near(v("iex_mwh"),accepted[scenario,city,t//24+1,t%24])
            near(v("ready_packs"),ready+v("packs_charged")-v("served_swaps"))
            near(v("input_mwh"),v("sold_mwh")+v("loss_mwh")+v("spill_mwh")+
                 v("soc_mwh")-soc+(v("ready_packs")-ready)*PACK)
            near(v("cost_inr")+v("ebitda_inr"),v("revenue_inr"))
            if (v("served_swaps")>ready-math.ceil(.05*stock) or
                v("input_mwh")>v("grid_limit_mw")+1e-6 or
                v("served_dc_mwh")>.95*.60*cap*.959+1e-6 or
                v("packs_charged")*PACK/.956>.95*.40*cap+1e-6):
                raise ValueError(f"Capacity discrepancy in {city} at hour {t}")
            soc,ready=v("soc_mwh"),v("ready_packs")
            if t%24==23 and (soc<cap*.15*health-1e-5 or ready<math.ceil(.55*stock)):
                raise ValueError("Closing inventory below target")
        total=lambda k:sum(float(r[k]) for r in rows)
        score=scores[scenario,city]
        for key,num,den in [("margin","ebitda_inr","revenue_inr"),
                            ("loss","loss_mwh","input_mwh"),
                            ("reliability","sold_mwh","forecast_mwh")]:
            near(float(score[key]),100*total(num)/total(den))
    print(f"Verified {sum(map(len,groups.values()))} cluster-hours and {len(groups)} scorecards.")

if __name__=="__main__":
    verify(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parent/"results")
