"""Pure human mouse trajectory generation with Fitts's law, Bezier curves, and overshoot."""

import math
import random
from typing import NamedTuple


class Point3D(NamedTuple):
    """A 2D coordinate on screen with a time delta in milliseconds from the previous point."""

    x: float
    y: float
    dt_ms: float


def compute_fitts_duration_ms(
    distance: float,
    target_width: float,
    rng: random.Random | None = None,
) -> float:
    """Calculate movement duration in ms using Fitts's Law.

    Formula: a + b * log2(distance / width + 1) with a ≈ 120ms, b ≈ 150ms.
    Clamped to [180.0, 900.0] ms.
    """
    # NOTE: Fitts's law duration - زمان جابجایی دست انسان تابعی لگاریتمی از فاصله تا هدف و اندازه خانه است؛
    # حرکت به خانه‌های دورتر زمان بیشتری نسبت به خانه‌های مجاور می‌برد و سرعت خطی ثابت نشانگر قطعی بات است.
    r = rng if rng is not None else random.Random()
    w = max(1.0, target_width)
    base = 120.0 + 150.0 * math.log2(distance / w + 1.0)
    noise = r.gauss(0.0, 20.0)
    duration = base + noise
    return max(180.0, min(900.0, duration))


def _cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    """Evaluate a cubic Bezier curve at parameter t in [0, 1]."""
    u = 1.0 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    x = uuu * p0[0] + 3.0 * uu * t * p1[0] + 3.0 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3.0 * uu * t * p1[1] + 3.0 * u * tt * p2[1] + ttt * p3[1]
    return x, y


def _ease_in_out(t: float) -> float:
    """Smoothstep ease-in-out parameter mapping."""
    # NOTE: Smoothstep acceleration - مفاصل دست انسان با شتاب ملایم حرکت را آغاز کرده و پیش از توقف کند می‌شوند.
    return t * t * (3.0 - 2.0 * t)


def _generate_step_dts(
    total_duration_ms: float,
    rng: random.Random,
) -> list[float]:
    """Generate dt_ms intervals between 8.0 and 12.0 ms summing close to total_duration_ms."""
    num_steps = max(5, int(round(total_duration_ms / 10.0)))
    raw_dts = [rng.uniform(8.5, 11.5) for _ in range(num_steps)]
    s = sum(raw_dts)
    scale = total_duration_ms / s if s > 0 else 1.0

    dts: list[float] = []
    for raw in raw_dts:
        dt = max(8.0, min(12.0, raw * scale))
        dts.append(dt)
    return dts


def generate_drag_path(
    start: tuple[float, float],
    end: tuple[float, float],
    square_size: float,
    force_overshoot: bool = False,
    rng: random.Random | None = None,
) -> list[Point3D]:
    """Generate a human-like curved mouse trajectory from start to end in CSS pixels.

    Features:
    - Cubic Bezier with 1-2 control points offset perpendicularly (5-25% distance).
    - Ease-in-out velocity profile.
    - Small Gaussian jitter (<= 1.5px).
    - 8-12ms between points.
    - Fitts's law duration clamped to 180-900ms.
    - 25% chance of overshoot on long moves (> 2 * square_size), or when forced.
    """
    r = rng if rng is not None else random.Random()
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = math.hypot(dx, dy)

    duration = compute_fitts_duration_ms(dist, square_size, rng=r)
    dts = _generate_step_dts(duration, r)
    num_steps = len(dts)

    if dist < 1e-4:
        # Stationary or negligible movement
        return [Point3D(start[0], start[1], 0.0)] + [Point3D(end[0], end[1], dt) for dt in dts]

    # Unit direction and normal
    ux = dx / dist
    uy = dy / dist
    nx = -uy
    ny = ux

    # NOTE: Overshoot 25% on long moves - انسان هنگام کشیدن سریع مهره به خانه‌های دور،
    # با احتمال حدود ۲۵٪ از هدف رد شده (overshoot) و سپس بلافاصله مسیر را به سمت مرکز خانه اصلاح می‌کند.
    should_overshoot = force_overshoot or (dist > 2.0 * square_size and r.random() < 0.25)

    if not should_overshoot:
        # Single cubic Bezier curve
        side = r.choice([-1.0, 1.0])
        offset_mag = dist * r.uniform(0.05, 0.25) * side

        p0 = start
        p1 = (
            start[0] + ux * (dist * 0.33) + nx * offset_mag,
            start[1] + uy * (dist * 0.33) + ny * offset_mag,
        )
        p2 = (
            start[0] + ux * (dist * 0.67) + nx * offset_mag * r.uniform(0.8, 1.2),
            start[1] + uy * (dist * 0.67) + ny * offset_mag * r.uniform(0.8, 1.2),
        )
        p3 = end

        points: list[Point3D] = [Point3D(start[0], start[1], 0.0)]
        for i in range(1, num_steps + 1):
            tau = i / num_steps
            t = _ease_in_out(tau)
            x, y = _cubic_bezier(p0, p1, p2, p3, t)

            if i < num_steps:
                # Add jitter
                jx = r.gauss(0.0, 0.4)
                jy = r.gauss(0.0, 0.4)
                j_len = math.hypot(jx, jy)
                if j_len > 1.5:
                    scale = 1.5 / j_len
                    jx *= scale
                    jy *= scale
                x += jx
                y += jy
            else:
                # Exact end
                x, y = end[0], end[1]

            points.append(Point3D(x, y, dts[i - 1]))
        return points

    # Overshoot logic: split into outward phase to overshoot point, then correction phase
    overshoot_dist = max(8.0, min(dist * r.uniform(0.06, 0.14), 50.0))
    lat_offset = r.uniform(2.0, 8.0) * r.choice([-1.0, 1.0])
    p_over = (
        end[0] + ux * overshoot_dist + nx * lat_offset,
        end[1] + uy * overshoot_dist + ny * lat_offset,
    )

    steps_out = max(3, int(round(num_steps * 0.78)))
    steps_back = max(2, num_steps - steps_out)

    # Outward Bezier: start -> p_over
    side = r.choice([-1.0, 1.0])
    offset_mag = dist * r.uniform(0.05, 0.20) * side
    p0 = start
    p1 = (
        start[0] + ux * (dist * 0.35) + nx * offset_mag,
        start[1] + uy * (dist * 0.35) + ny * offset_mag,
    )
    p2 = (
        p_over[0] - ux * (overshoot_dist * 0.5) + nx * offset_mag * 0.5,
        p_over[1] - uy * (overshoot_dist * 0.5) + ny * offset_mag * 0.5,
    )
    p3 = p_over

    # Return Bezier: p_over -> end
    ret_p0 = p_over
    ret_p1 = (
        p_over[0] - ux * (overshoot_dist * 0.4),
        p_over[1] - uy * (overshoot_dist * 0.4),
    )
    ret_p2 = (
        end[0] + ux * (overshoot_dist * 0.2),
        end[1] + uy * (overshoot_dist * 0.2),
    )
    ret_p3 = end

    points = [Point3D(start[0], start[1], 0.0)]

    # Outward steps
    for i in range(1, steps_out + 1):
        tau = i / steps_out
        t = _ease_in_out(tau)
        x, y = _cubic_bezier(p0, p1, p2, p3, t)

        if i < steps_out:
            jx = r.gauss(0.0, 0.4)
            jy = r.gauss(0.0, 0.4)
            j_len = math.hypot(jx, jy)
            if j_len > 1.5:
                scale = 1.5 / j_len
                jx *= scale
                jy *= scale
            x += jx
            y += jy
        else:
            # Apex point at p_over
            x, y = p_over[0], p_over[1]

        points.append(Point3D(x, y, dts[i - 1]))

    # Return steps
    for i in range(1, steps_back + 1):
        tau = i / steps_back
        # Ease out to final rest
        t = 1.0 - (1.0 - tau) * (1.0 - tau)
        x, y = _cubic_bezier(ret_p0, ret_p1, ret_p2, ret_p3, t)

        if i < steps_back:
            jx = r.gauss(0.0, 0.4)
            jy = r.gauss(0.0, 0.4)
            j_len = math.hypot(jx, jy)
            if j_len > 1.5:
                scale = 1.5 / j_len
                jx *= scale
                jy *= scale
            x += jx
            y += jy
        else:
            x, y = end[0], end[1]

        dt_idx = steps_out + i - 1
        dt = dts[dt_idx] if dt_idx < len(dts) else 10.0
        points.append(Point3D(x, y, dt))

    return points


def generate_hover_path(
    current_pos: tuple[float, float],
    target_pos: tuple[float, float],
    square_size: float,
    rng: random.Random | None = None,
) -> list[Point3D]:
    """Generate an idle hover path moving the cursor from current position to a target piece."""
    return generate_drag_path(
        current_pos,
        target_pos,
        square_size=square_size,
        force_overshoot=False,
        rng=rng,
    )
