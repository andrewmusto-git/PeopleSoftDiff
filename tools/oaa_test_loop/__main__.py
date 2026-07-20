"""Entry point for `python -m tools.oaa_test_loop <slug>`."""
import sys

from tools.oaa_test_loop.harness import main

sys.exit(main(sys.argv))
