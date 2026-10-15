"""Run component tests safely; live Groq evaluators are under research/tools/."""
import sys
import unittest
from pathlib import Path


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    directory = root / 'tests' / 'components'
    sys.path.insert(0,str(root / 'research' / 'tools'))
    suite = unittest.defaultTestLoader.discover(str(directory), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
