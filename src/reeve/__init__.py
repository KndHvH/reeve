"""Reeve: a lightweight macro assistant for Age of Empires IV."""

import os

# Before numpy is first imported (every entry point imports this package
# first): OpenBLAS otherwise starts a thread per core and commits ~500 MB of
# buffers for them. Reeve does no heavy linear algebra (its correlations run
# on FFTs), so one thread costs nothing.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

__version__ = "0.2.2.1"
