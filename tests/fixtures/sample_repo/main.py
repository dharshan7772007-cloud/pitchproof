"""
tests/fixtures/sample_repo/main.py
------------------------------------
Entry point for the sample fixture repository.
"""
from utils import DataProcessor


def main():
    processor = DataProcessor([1, 2, 3])
    result = processor.run()
    print(f"Result: {result}")


if __name__ == "__main__":
    main()
