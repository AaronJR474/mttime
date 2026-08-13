"""Regression checks for the weighted normal-equation implementation."""

import numpy as np


def test_row_scaled_weighting_matches_dense_diagonal_form():
    rng = np.random.default_rng(91)
    for n_data, n_model in ((8, 5), (37, 6), (257, 6)):
        G = rng.normal(size=(n_data, n_model))
        d = rng.normal(size=n_data)
        w = rng.uniform(0.01, 2.0, size=n_data)

        expected_gtd = G.T @ np.diag(w) @ d
        expected_gtg = G.T @ np.diag(w) @ G

        actual_gtd = G.T @ (w * d)
        actual_gtg = G.T @ (w[:, None] * G)

        np.testing.assert_allclose(actual_gtd, expected_gtd, rtol=1e-13, atol=1e-13)
        np.testing.assert_allclose(actual_gtg, expected_gtg, rtol=1e-13, atol=1e-13)
