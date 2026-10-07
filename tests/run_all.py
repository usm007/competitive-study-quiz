"""Run the full exam-quiz skill suite and print a summary.

Usage: `python tests/run_all.py` from the skill root.
Exit code is nonzero on any failure or error.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


def main():
    loader = unittest.TestLoader()
    suite = loader.discover(str(HERE), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    print("-" * 60)
    print("tests run: %d, failures: %d, errors: %d, skipped: %d" % (
        result.testsRun, len(result.failures), len(result.errors),
        len(result.skipped)))
    print("RESULT: %s" % ("PASS" if result.wasSuccessful() else "FAIL"))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
