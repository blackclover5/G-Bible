"""Regression tests for G-Bible.

Empty since the project reset; this package now pins the seams that actually
broke in practice, above all the parser -> span table -> render round trip
that decides which words are "red".  Every test is self-contained: no network,
no access to data/ — the database tests run against a throwaway GBIBLE_HOME.
"""
