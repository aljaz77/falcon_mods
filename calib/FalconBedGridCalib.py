"""Frozen-executable entry point for the bed-grid calibration tool."""
import sys

from falcon_bedgrid.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
