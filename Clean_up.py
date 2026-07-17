#!/usr/bin/env python3
"""Backward-compatible entry point.

The implementation now lives in the ``cleanup`` package (``cleanup/core`` for
the engine, ``cleanup/cli`` for this Rich interface). This shim keeps the old
``python Clean_up.py <dir>`` invocation working. Prefer the installed
``cleanup`` command (see pyproject.toml) going forward.
"""

from cleanup.cli.main import main

if __name__ == "__main__":
    main()
