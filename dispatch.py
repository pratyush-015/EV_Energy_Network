import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from forecast import PACK

FIELDS = ["renew", "discom", "iex", "charge", "discharge", "dc", "refill", "swaps", "soc", "ready", "spill"]
R, G, I, C, D, E, F, S, B, P, W = range(len(FIELDS))
GRID_EFF, DC_EFF, BAT_EFF, PACK_EFF, IDLE = .984, .959, .958, .956, .00012
PPA, DISCOM, WEAR = 3.25, 6.65, .65

def solve(load, swap, renew, market, cap, feeder, soh, state, bookings=None, execute=False):
    n, k = len(load), len(FIELDS)
    bmax = cap*.30*soh
    pmax = int(cap*.20*soh/PACK)
    reserve = int(np.ceil(.05*pmax))
    low = np.zeros((n,k))
    high = np.full((n,k), np.inf)
    high[:,R] = renew
    high[:,G] = cap*.48
    high[:,I] = cap*.42
    if bookings is not None:
        low[:,I] = high[:,I] = bookings
    high[:,C] = high[:,D] = cap*.12*soh
    high[:,E] = np.minimum(load, .95*.6*cap*DC_EFF)
    high[:,F] = .95*.4*cap*PACK_EFF/PACK
    high[:,S] = swap
    low[:,B], high[:,B] = .05*bmax, bmax
    low[:,P], high[:,P] = reserve, pmax
    low[-1,B] = max(low[-1,B], .50*bmax)
    low[-1,P] = max(low[-1,P], np.ceil(.55*pmax))
    cost = np.zeros((n,k))
    cost[:,G], cost[:,I] = DISCOM, market
    cost[:,C], cost[:,D] = WEAR/2, WEAR/2
    cost[:,E], cost[:,S] = -45, -48*PACK
    cost[:,W] = .02
    matrix = lil_matrix((7*n,n*k))
    lower = np.full(7*n,-np.inf)
    upper = np.zeros(7*n)
    for t in range(n):
        row = 7*t
        def add(i, pairs):
            for j, value in pairs:
                matrix[row+i,t*k+j] = value
        add(0,[(R,GRID_EFF),(G,GRID_EFF),(I,GRID_EFF),(D,1),(C,-1),(E,-1/DC_EFF),
               (F,-PACK/PACK_EFF),(W,-1)])
        upper[row] = (state[1] if t==0 else 0)*PACK*IDLE/PACK_EFF
        if t:
            matrix[row,(t-1)*k+P] = -PACK*IDLE/PACK_EFF
        add(1,[(B,1),(C,-BAT_EFF),(D,1/BAT_EFF)])
        add(2,[(P,1),(F,-1),(S,1)])
        add(3,[(S,1)])
        add(4,[(F,1)])
        if t:
            matrix[row+1,(t-1)*k+B] = -1
            matrix[row+2,(t-1)*k+P] = -1
            matrix[row+3,(t-1)*k+P] = -1
            matrix[row+4,(t-1)*k+P] = 1
        else:
            upper[row+1:row+3] = state
        upper[row+3] = (state[1] if t==0 else 0) - reserve
        upper[row+4] = pmax - (state[1] if t==0 else 0)
        lower[row:row+3] = upper[row:row+3]
        add(5,[(G,1),(I,1),(R,1)])
        upper[row+5] = feeder[t]
        add(6,[(C,1),(D,1)])
        upper[row+6] = cap*.12*soh
    integer = np.zeros((n,k))
    if execute:
        integer[0,[F,S]] = 1
    result = milp(cost.ravel(),integrality=integer.ravel(),bounds=Bounds(low.ravel(),high.ravel()),
                  constraints=LinearConstraint(matrix.tocsr(),lower,upper),
                  options={"mip_rel_gap":0})
    if not result.success:
        raise RuntimeError(result.message)
    return result.x.reshape(n,k).clip(0)
