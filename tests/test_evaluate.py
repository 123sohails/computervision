import importlib.util
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("evaluate", Path(__file__).parent.parent / "scripts" / "evaluate.py")
evaluate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluate)


def test_iou_and_greedy_matching():
    a = np.array([[0, 0, 10, 10], [20, 20, 30, 30]], dtype=float)
    b = np.array([[0, 0, 10, 10], [100, 100, 110, 110], [21, 21, 31, 31]], dtype=float)
    ious = evaluate.iou_matrix(a, b)
    assert abs(ious[0, 0] - 1.0) < 1e-6 and ious[0, 1] == 0.0
    assert evaluate.match(a, b, 0.5) == 2
    assert evaluate.match(a, b[:0], 0.5) == 0
