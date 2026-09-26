"""
tests/fixtures/sample_repo/broken_syntax.py
---------------------------------------------
Intentionally broken Python file used to test safe SyntaxError handling.
"""

def oops(:
    pass  # <- deliberate syntax error
