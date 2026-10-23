"""Tests for viewport-to-screen calibration solver."""

import pytest

from chess_autoplayer.input.calibration import (
    CalibrationError,
    solve_calibration,
)


def test_solve_calibration_recovers_known_parameters() -> None:
    # Known mapping: screen_x = 2.0 * client_x + 50.0, screen_y = 1.5 * client_y + 100.0
    c1 = (100.0, 150.0)
    s1 = (2.0 * 100.0 + 50.0, 1.5 * 150.0 + 100.0)

    c2 = (400.0, 600.0)
    s2 = (2.0 * 400.0 + 50.0, 1.5 * 600.0 + 100.0)

    model = solve_calibration(s1, c1, s2, c2)
    assert abs(model.scale_x - 2.0) < 1e-6
    assert abs(model.offset_x - 50.0) < 1e-6
    assert abs(model.scale_y - 1.5) < 1e-6
    assert abs(model.offset_y - 100.0) < 1e-6

    # Test round trip
    test_client = (250.0, 350.0)
    screen_pt = model.client_to_screen(*test_client)
    recovered_client = model.screen_to_client(*screen_pt)
    assert abs(recovered_client[0] - test_client[0]) < 1e-6
    assert abs(recovered_client[1] - test_client[1]) < 1e-6


def test_solve_calibration_rejects_degenerate_inputs() -> None:
    # Identical client X
    s1 = (100.0, 100.0)
    c1 = (50.0, 50.0)
    s2 = (200.0, 200.0)
    c2 = (50.0, 100.0)
    with pytest.raises(CalibrationError, match="Degenerate client X"):
        solve_calibration(s1, c1, s2, c2)

    # Identical client Y
    c3 = (100.0, 50.0)
    with pytest.raises(CalibrationError, match="Degenerate client Y"):
        solve_calibration(s1, c1, s2, c3)

    # Negative scale (inverted coordinates)
    s_inv = (50.0, 50.0)
    c_inv = (200.0, 200.0)
    with pytest.raises(CalibrationError, match="Invalid non-positive scale"):
        solve_calibration(s1, c1, s_inv, c_inv)
