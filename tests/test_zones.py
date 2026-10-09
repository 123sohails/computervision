import numpy as np
import pytest

from backend.services.zone_manager import (Zone, ZoneManager, bottom_center, points_in_polygon,
                                           validate_zone)

SQUARE = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)


def test_points_in_polygon_square():
    pts = np.array([[5, 5], [11, 5], [-1, -1], [9.9, 0.1]])
    assert points_in_polygon(pts, SQUARE).tolist() == [True, False, False, True]


def test_points_in_concave_polygon():
    l_shape = np.array([[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]], dtype=float)
    pts = np.array([[2, 8], [8, 8], [8, 2]])
    assert points_in_polygon(pts, l_shape).tolist() == [True, False, True]


def test_empty_points():
    assert points_in_polygon(np.zeros((0, 2)), SQUARE).shape == (0,)


def test_bottom_center_uses_feet():
    assert bottom_center(np.array([[10, 20, 30, 120]])).tolist() == [[20.0, 120.0]]


def test_relative_zone_scales_with_resolution():
    z = Zone.from_dict({"id": "q", "zone_type": "QUEUE_ZONE",
                        "points": [[0.25, 0.5], [0.75, 0.5], [0.75, 1.0], [0.25, 1.0]]})
    assert z.abs_points(1280, 720)[0].tolist() == [320, 360]
    assert z.abs_points(1920, 1080)[0].tolist() == [480, 540]


def test_zone_manager_membership_by_feet_not_center():
    zm = ZoneManager([Zone.from_dict({"id": "floor", "zone_type": "OCCUPANCY_ZONE",
                                      "points": [[0, 0.5], [1, 0.5], [1, 1], [0, 1]]})], 100, 100)
    # Box centre is in the top half (outside), feet are in the bottom half (inside).
    box = np.array([[40, 10, 60, 70]])
    assert zm.membership(bottom_center(box))["floor"].tolist() == [True]


def test_exclusion_zone():
    zm = ZoneManager([Zone.from_dict({"id": "x", "zone_type": "EXCLUSION_ZONE",
                                      "points": [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]})], 100, 100)
    assert zm.excluded(np.array([[10, 50], [90, 50]])).tolist() == [True, False]


@pytest.mark.parametrize("zone_type,points,err", [
    ("BAD", [[0, 0], [1, 0], [1, 1]], "zone_type"),
    ("QUEUE_ZONE", [[0, 0], [1, 1]], "at least 3"),
    ("ENTRY_LINE", [[0, 0], [1, 1], [0, 1]], "exactly 2"),
    ("QUEUE_ZONE", [[0, 0], [1.5, 0], [1, 1]], "relative"),
    ("QUEUE_ZONE", [[0, 0], [0.5, 0.5], [1, 1]], "area"),
])
def test_validate_zone_rejects(zone_type, points, err):
    with pytest.raises(ValueError, match=err):
        validate_zone(zone_type, points)


def test_validate_zone_accepts():
    validate_zone("OCCUPANCY_ZONE", [[0, 0], [1, 0], [1, 1]], capacity=60)
    validate_zone("EXIT_LINE", [[0, 0.5], [1, 0.5]])
