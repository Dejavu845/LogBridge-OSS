"""White-balance CAT tests. WB is ACES2065-1 (AP0) scene-linear only."""

import numpy as np
import pytest

from color.gamuts import D65_XY
from color.wb import (
    apply_white_balance,
    bradford_cat_matrix,
    cct_to_xy,
    white_balance_matrix,
)
from color.working_space import DEFAULT_WORKING_LINEAR


def test_6504k_is_d65():
    xy = cct_to_xy(6504.0)
    np.testing.assert_allclose(xy, D65_XY, atol=5e-4)


def test_6504k_bradford_is_identity():
    m = bradford_cat_matrix(cct_to_xy(6504.0), D65_XY)
    np.testing.assert_allclose(m, np.eye(3), atol=5e-3)


def test_default_wb_space_is_ap0():
    assert DEFAULT_WORKING_LINEAR == "AP0"
    m = white_balance_matrix(6504.0, tint=0.0)
    np.testing.assert_allclose(m, np.eye(3), atol=5e-3)
    rgb = np.array([0.18, 0.18, 0.18])
    out = apply_white_balance(rgb, 6504.0)
    np.testing.assert_allclose(out, rgb, atol=1e-3)


def test_6504k_rgb_matrix_is_identity_on_aces2065():
    m = white_balance_matrix(6504.0, tint=0.0, rgb_space="AP0")
    np.testing.assert_allclose(m, np.eye(3), atol=5e-3)
    rgb = np.array([0.18, 0.18, 0.18])
    out = apply_white_balance(rgb, 6504.0, rgb_space="AP0")
    np.testing.assert_allclose(out, rgb, atol=1e-3)


def test_3200k_is_not_identity():
    m = white_balance_matrix(3200.0, rgb_space="AP0")
    diff = np.linalg.norm(m - np.eye(3))
    assert diff > 0.05
    rgb = np.array([0.18, 0.18, 0.18])
    out = apply_white_balance(rgb, 3200.0, rgb_space="AP0")
    assert not np.allclose(out, rgb, atol=1e-3)


def test_cat02_also_identity_at_6504k():
    m = white_balance_matrix(6504.0, rgb_space="Rec709", method="cat02")
    np.testing.assert_allclose(m, np.eye(3), atol=5e-3)


def test_tint_shifts_off_locus():
    m0 = white_balance_matrix(5600.0, tint=0.0, rgb_space="AP0")
    mg = white_balance_matrix(5600.0, tint=5.0, rgb_space="AP0")
    assert not np.allclose(m0, mg, atol=1e-6)


def test_wb_is_linear_operator():
    """Doubling scene-linear RGB doubles the result (no log-domain WB)."""
    rgb = np.array([0.04, 0.08, 0.16])
    a = apply_white_balance(rgb, 3200.0, rgb_space="AP0")
    b = apply_white_balance(2.0 * rgb, 3200.0, rgb_space="AP0")
    np.testing.assert_allclose(b, 2.0 * a, rtol=1e-12)


def test_ap0_cat_differs_from_ap1_on_chroma():
    """CAT conjugation is space-dependent; AP0 is the required domain."""
    rgb = np.array([0.10, 0.18, 0.30])
    ap0 = apply_white_balance(rgb, 3200.0, rgb_space="AP0")
    ap1 = apply_white_balance(rgb, 3200.0, rgb_space="AP1")
    assert not np.allclose(ap0, ap1, atol=1e-4)




def test_relative_cat_unmoved_as_shot_is_identity():
    """as-shot 3200, knobs still 3200 -> identity."""
    same = white_balance_matrix(src_cct=3200.0, dst_cct=3200.0)
    np.testing.assert_allclose(same, np.eye(3), atol=1e-12)


def test_relative_cat_as_shot_3200_user_5600():
    """3200 as-shot → 5600 user == CAT(user→D65)@inv(CAT(as→D65)), warms."""
    rel = white_balance_matrix(src_cct=3200.0, dst_cct=5600.0)
    cat_user = white_balance_matrix(5600.0)
    cat_shot = white_balance_matrix(3200.0)
    expected = cat_user @ np.linalg.inv(cat_shot)
    np.testing.assert_allclose(rel, expected, atol=1e-12)
    as_to_user = white_balance_matrix(src_cct=5600.0, dst_cct=3200.0)
    assert not np.allclose(rel, cat_user, atol=1e-3)
    assert not np.allclose(rel, as_to_user, atol=1e-3)
    grey = np.array([0.18, 0.18, 0.18])
    warmed = apply_white_balance(grey, src_cct=3200.0, dst_cct=5600.0)
    cooled = apply_white_balance(grey, src_cct=5600.0, dst_cct=3200.0)
    assert warmed[0] / warmed[2] > grey[0] / grey[2]
    assert cooled[0] / cooled[2] < grey[0] / grey[2]
