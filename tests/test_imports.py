"""Phase 0 check: every skeleton module imports."""

import importlib

MODULES = [
    "src.ingest",
    "src.chunk",
    "src.index_corpus",
    "src.scope",
    "src.retrieve",
    "src.answer",
    "src.validate",
    "src.app",
]


def test_modules_import():
    for name in MODULES:
        importlib.import_module(name)
