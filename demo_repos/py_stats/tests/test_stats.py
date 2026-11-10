import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stats import mean, median, value_range


def test_mean():
    assert mean([1, 2, 3, 4]) == 2.5


def test_median_odd_length():
    assert median([5, 1, 3]) == 3


def test_median_even_length():
    assert median([4, 1, 3, 2]) == 2.5


def test_median_two_values():
    assert median([10, 20]) == 15


def test_median_empty():
    with pytest.raises(ValueError):
        median([])


def test_value_range():
    assert value_range([3, 9, 4]) == 6
