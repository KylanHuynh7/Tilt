"""Maximum-likelihood logistic regression by Newton's method, pure Python.

Small, dependency-free, and exact enough for the handful of interpretable
coefficients the live win-probability models use (methodology §12s).
"""

from __future__ import annotations

import math
from typing import Sequence


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def fit(xs: Sequence[Sequence[float]], ys: Sequence[float], *, iterations: int = 30,
        tol: float = 1e-10) -> list[float]:
    """Coefficients β maximizing the Bernoulli likelihood of ys given xs.
    Each x must already include the intercept column. ys may be fractional
    (e.g. 0.5 for ties), which is still a valid likelihood target.
    """
    k = len(xs[0])
    beta = [0.0] * k
    for _ in range(iterations):
        g = [0.0] * k
        h = [[0.0] * k for _ in range(k)]
        for x, y in zip(xs, ys):
            p = sigmoid(sum(b * v for b, v in zip(beta, x)))
            w = p * (1 - p)
            r = y - p
            for i in range(k):
                g[i] += r * x[i]
                wi = w * x[i]
                for j in range(i, k):
                    h[i][j] += wi * x[j]
        for i in range(k):
            for j in range(i):
                h[i][j] = h[j][i]
        step = _solve(h, g)
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < tol:
            break
    return beta
