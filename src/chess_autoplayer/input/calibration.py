"""Pure calibration solver mapping viewport/client coordinates to macOS screen coordinates."""

from dataclasses import dataclass


class CalibrationError(Exception):
    """Raised when calibration data is invalid, degenerate, or cannot be solved."""


@dataclass(frozen=True)
class CalibrationModel:
    """Affine mapping between viewport client coordinates and physical screen coordinates.

    Formula: screen = scale * client + offset
    """

    scale_x: float
    offset_x: float
    scale_y: float
    offset_y: float

    def client_to_screen(self, client_x: float, client_y: float) -> tuple[float, float]:
        """Convert browser viewport client coordinates to screen coordinates."""
        sx = self.scale_x * client_x + self.offset_x
        sy = self.scale_y * client_y + self.offset_y
        return sx, sy

    def screen_to_client(self, screen_x: float, screen_y: float) -> tuple[float, float]:
        """Convert physical screen coordinates to browser client coordinates."""
        cx = (screen_x - self.offset_x) / self.scale_x
        cy = (screen_y - self.offset_y) / self.scale_y
        return cx, cy


def solve_calibration(
    screen_pt1: tuple[float, float],
    client_pt1: tuple[float, float],
    screen_pt2: tuple[float, float],
    client_pt2: tuple[float, float],
) -> CalibrationModel:
    """Solve for scale and offset mapping client coordinates to screen coordinates.

    Raises CalibrationError if input points are degenerate (same client coordinate
    or non-positive scale).
    """
    sx1, sy1 = screen_pt1
    cx1, cy1 = client_pt1
    sx2, sy2 = screen_pt2
    cx2, cy2 = client_pt2

    dcx = cx2 - cx1
    dcy = cy2 - cy1

    if abs(dcx) < 1e-4:
        raise CalibrationError(f"Degenerate client X coordinates: cx1={cx1}, cx2={cx2}")
    if abs(dcy) < 1e-4:
        raise CalibrationError(f"Degenerate client Y coordinates: cy1={cy1}, cy2={cy2}")

    scale_x = (sx2 - sx1) / dcx
    scale_y = (sy2 - sy1) / dcy

    if scale_x <= 0 or scale_y <= 0:
        raise CalibrationError(f"Invalid non-positive scale: scale_x={scale_x}, scale_y={scale_y}")

    offset_x = sx1 - scale_x * cx1
    offset_y = sy1 - scale_y * cy1

    return CalibrationModel(
        scale_x=scale_x,
        offset_x=offset_x,
        scale_y=scale_y,
        offset_y=offset_y,
    )
