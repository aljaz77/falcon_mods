import numpy as np

from falcon_bedgrid import lm


def test_fits_exponential_with_outliers():
    rng = np.random.default_rng(1)
    x = np.linspace(0, 4, 200)
    y = 3.0 * np.exp(-0.7 * x) + 0.5 + rng.normal(0, 0.01, x.size)
    y[::25] += 2.0  # outliers

    def res(p):
        return p[0] * np.exp(-p[1] * x) + p[2] - y

    out = lm.least_squares(res, np.array([1.0, 0.1, 0.0]), f_scale=0.05)
    assert np.allclose(out.x, [3.0, 0.7, 0.5], atol=0.02)


def test_bounds_respected():
    out = lm.least_squares(lambda p: p - 10.0, np.array([0.0]),
                           bounds=(np.array([-1.0]), np.array([2.0])))
    assert out.x[0] <= 2.0 + 1e-12
