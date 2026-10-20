"""Extraction core: signal schema, lexicon, deterministic checks, provider protocol.

Pure: no network, no database, no SDK imports. Replay never calls a provider; the
checks version and results are stored with each extraction and never recomputed.
"""
