"""Run component tests safely; real Groq testing is opt-in via live_integration.py."""
import sys
import unittest
from pathlib import Path


if __name__ == "__main__":
    directory = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(directory), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
