"""Lumi — your AI companion. Always on. Always yours."""

import os as _os

# Workaround for protobuf version mismatch in chromadb's bundled opentelemetry.
# Must be set before chromadb is imported anywhere in the process. We set it
# here (the package root) so every Lumi entrypoint inherits it automatically.
_os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

__version__ = "0.1.0"
