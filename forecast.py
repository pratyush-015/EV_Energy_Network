from datetime import date
import numpy as np

CITIES = ["Delhi NCR", "Mumbai MMR", "Bengaluru", "Hyderabad", "Chennai"]
CAPACITY = [300, 270, 240, 210, 180]
BASE_TARIFF = [11.0, 11.5, 10.5, 10.8, 11.2]
HISTORY = (date(2025, 1, 1) - date(2020, 1, 1)).days * 24
SCENARIOS = ["Reference", "Heatwave", "Monsoon lull", "Feeder squeeze"]
PACK = .04

def features(t, temp, cloud, wind, city):
    h = t % 24
    day = t // 24
    angle = h * np.pi / 12
    shift = [0, 1, -1, 0, 1][city]
    morning = np.exp(-((h - 9 - shift) / 2.6)**2)
    evening = np.exp(-((h - 19 - shift) / 3.1)**2)
    sun = np.maximum(0, np.sin((h - 6) * np.pi / 12))
    return np.column_stack([np.ones(len(t)), np.sin(angle), np.cos(angle), morning,
                            evening, ((day + 2) % 7 >= 5), np.maximum(temp - 29, 0),
                            sun * (1 - cloud), wind**2, cloud, evening * cloud])

def samples(t, city, rng, scenario):
    day = t // 24
    hour = t % 24
    season = np.sin(2 * np.pi * (day - 70) / 365.25)
    temp = 27 + (6 - .5 * city) * season + 4 * np.sin((hour - 9) * np.pi / 12)
    temp += rng.normal(0, 1.2, len(t)) + 9 * (scenario == "Heatwave")
    cloud = np.clip(.35 + .14 * season + rng.normal(0, .13, len(t)) +
                    .46 * (scenario == "Monsoon lull"), .02, .99)
    wind = np.clip(5 + city * .3 + rng.normal(0, 1, len(t)) -
                   3 * (scenario == "Monsoon lull"), 1, 10)
    x = features(t, temp, cloud, wind, city)
    cap = CAPACITY[city]
    retail = cap * (.105 + .037*x[:,3] + .115*x[:,4] + .003*x[:,6] + .014*x[:,5])
    ride = cap * (.067 + .085*x[:,3] + .047*x[:,4] + .001*x[:,6])
    logistics = cap * (.051 + .035*x[:,2] + .024*x[:,4] - .011*x[:,5])
    swaps = cap * (.058 + .075*x[:,3] + .085*x[:,4] + .002*x[:,6])
    renew = cap * (.35*x[:,7] + .00205*x[:,8])
    price = 3.8 + 2.4*x[:,4] + .075*x[:,6] - .9*x[:,7] + .55*cloud
    y = np.column_stack([retail, ride, logistics, swaps, renew, price])
    y *= rng.lognormal(-.5*.053**2, .053, y.shape)
    y[:,3] = np.round(y[:,3] / PACK) * PACK
    return x, y, (temp, cloud, wind)

def build(city, seed, days, scenario):
    rng = np.random.default_rng([seed, city])
    t = np.arange(HISTORY)
    x, y, history_weather = samples(t, city, rng, "Reference")
    split = len(t) - 24 * 90
    def fit(a, b):
        return np.linalg.solve(a.T @ a + .05*np.eye(a.shape[1]), a.T @ b)
    validation_rng = np.random.default_rng([seed, city, 901])
    ht, hc, hw = (w[split:] for w in history_weather)
    count = len(ht)
    holdout = features(t[split:], ht+validation_rng.normal(0,1.6,count),
                       np.clip(hc+validation_rng.normal(0,.09,count),0,1),
                       np.clip(hw+validation_rng.normal(0,.65,count),.5,12), city)
    validation = np.maximum(0, holdout @ fit(x[:split], y[:split]))
    truth = y[split:]
    previous_week = y[split-168:-168]
    score = lambda pred: (100 * np.abs(pred-truth).sum(axis=0) / truth.sum(axis=0)).tolist()
    weights = fit(x, y)
    renewable_scale = .35 * y[:,:4].sum() / (.94 * y[:,4].sum())
    future = np.arange(HISTORY, HISTORY + days*24)
    _, actual, weather = samples(future, city, rng, scenario)
    temp, cloud, wind = weather
    outlook = features(future, temp+rng.normal(0,1.6,len(temp)),
                       np.clip(cloud+rng.normal(0,.09,len(temp)),0,1),
                       np.clip(wind+rng.normal(0,.65,len(temp)),.5,12), city)
    forecast = np.maximum(.001, outlook @ weights)
    forecast[:,4] *= renewable_scale
    actual[:,4] *= renewable_scale
    soh = .99 - .012*city - .008*(t / HISTORY)
    return forecast, actual, weather, float(soh[-1]), score(validation), score(previous_week)
