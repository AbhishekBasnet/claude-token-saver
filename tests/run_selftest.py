#!/usr/bin/env python3
"""Run the token-saver self-test from a shell or CI (no Claude needed).
The engine and fixtures live in the plugin (plugins/token-saver/selftest/) so
Doctor can run the same test from an installed copy."""
import os
import runpy
import sys

here = os.path.dirname(os.path.abspath(__file__))
selftest = os.path.join(here, "..", "plugins", "token-saver", "selftest", "selftest.py")
sys.path.insert(0, os.path.dirname(selftest))
sys.argv = [selftest] + sys.argv[1:]
runpy.run_path(selftest, run_name="__main__")
