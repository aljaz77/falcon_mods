"""Small robust Levenberg-Marquardt solver (keeps SciPy out of the frozen executable).

Minimises sum(rho((r_i / f_scale)^2)) with the soft-L1 loss rho(z) = 2(sqrt(1+z) - 1),
using iteratively re-weighted least squares, Marquardt diagonal scaling, forward-difference
Jacobians and box bounds (by clipping).
"""
from types import SimpleNamespace

import numpy as np


def _jacobian(fun, x, r0, args):
    J = np.empty((r0.size, x.size))
    for j in range(x.size):
        h = 1e-6 * (1.0 + abs(x[j]))
        xp = x.copy()
        xp[j] += h
        J[:, j] = (fun(xp, *args) - r0) / h
    return J


def least_squares(fun, x0, args=(), f_scale=1.0, bounds=None, max_iter=60, tol=1e-10):
    lo, hi = (bounds if bounds is not None else (np.full(len(x0), -np.inf), np.full(len(x0), np.inf)))
    x = np.clip(np.asarray(x0, float), lo, hi)

    def weights(r):
        z = (r / f_scale) ** 2
        return 1.0 / np.sqrt(1.0 + z)

    def cost(r):
        z = (r / f_scale) ** 2
        return float(np.sum(2.0 * (np.sqrt(1.0 + z) - 1.0))) * f_scale ** 2

    r = fun(x, *args)
    c = cost(r)
    lam = 1e-3
    nfev = 1
    for _ in range(max_iter):
        J = _jacobian(fun, x, r, args)
        nfev += x.size
        w = weights(r)
        Jw = J * w[:, None]
        A = J.T @ Jw
        g = Jw.T @ r
        d = np.diag(A).copy()
        d[d <= 0] = 1e-12
        improved = False
        for _ in range(12):
            try:
                step = np.linalg.solve(A + lam * np.diag(d), -g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            xn = np.clip(x + step, lo, hi)
            rn = fun(xn, *args)
            nfev += 1
            cn = cost(rn)
            if np.isfinite(cn) and cn < c:
                rel = (c - cn) / max(c, 1e-300)
                x, r, c = xn, rn, cn
                lam = max(lam / 5, 1e-12)
                improved = True
                break
            lam *= 10
        if not improved or rel < tol:
            break
    return SimpleNamespace(x=x, fun=r, cost=c, nfev=nfev)
