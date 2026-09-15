"""$HOME resolution that survives it being unset -- Windows Git Bash doesn't always set it, and
`os.environ["HOME"]` raising KeyError there would take down every script that reads it. Moved
here from cfq_runtime.py so every caller shares one fallback instead of repeating
`os.environ.get("HOME") or ...` at each call site.
"""

import os
import pathlib


def home_dir():
    return pathlib.Path(os.environ.get("HOME") or str(pathlib.Path.home()))
