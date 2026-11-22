import json
from pathlib import Path

def render(path, rows, scores, meta):
    keys = ["scenario","city","time","forecast_mwh","sold_mwh","renewable_mwh","soc_mwh",
            "price_inr_kwh","ready_packs","served_swaps","reserve_packs","grid_limit_mw"]
    compact = [{k:round(float(r[k]),3) if k not in keys[:3] else r[k] for k in keys} for r in rows]
    template = Path(__file__).with_name("dashboard.html.in").read_text(encoding="utf-8")
    path.write_text(template.replace("__DATA__",json.dumps([compact,scores,meta],separators=(",",":"))),
                    encoding="utf-8")
