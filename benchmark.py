import argparse
import csv
from pathlib import Path
from time import perf_counter
import numpy as np
from dispatch import solve
from forecast import build, CAPACITY, PACK

def main():
    parser = argparse.ArgumentParser(description="Time independent 24-hour day-ahead solves")
    parser.add_argument("--out",type=Path,default=Path(__file__).parent/"results"/"scaling.csv")
    args = parser.parse_args()
    inputs = []
    for city, cap in enumerate(CAPACITY):
        forecast, _, _, health, _, _ = build(city,42,1,"Reference")
        stock = int(cap*.20*health/PACK)
        inputs.append((forecast[:,:3].sum(axis=1),forecast[:,3]/PACK,forecast[:,4],forecast[:,5],
                       cap,np.full(24,cap*.65),health,(cap*.15*health,np.ceil(.55*stock))))
    solve(*inputs[0])
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("w",newline="") as out:
        writer=csv.writer(out)
        writer.writerow(["clusters","cluster_hours","median_seconds","repeats"])
        for n in [5,25,100]:
            trials=[]
            for _ in range(3):
                start=perf_counter()
                for i in range(n):
                    solve(*inputs[i%5])
                trials.append(perf_counter()-start)
            writer.writerow([n,24*n,round(float(np.median(trials)),4),3])

if __name__=="__main__":
    main()
