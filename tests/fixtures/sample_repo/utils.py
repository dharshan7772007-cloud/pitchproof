"""
tests/fixtures/sample_repo/utils.py
-------------------------------------
Minimal Python file used as a test fixture for the repo-analysis tests.
Contains a known bug: get_items() can raise IndexError when the list is empty.
"""


def get_items(items: list, index: int):
    """Return the item at *index* from *items*. Raises IndexError if out of range."""
    return items[index]  # Bug: no bounds check


def process(data: list):
    """Process data by accessing the first element."""
    first = get_items(data, 0)
    return first * 2


class DataProcessor:
    """Simple data processing class."""

    def __init__(self, data: list):
        self.data = data

    def run(self):
        return process(self.data)
