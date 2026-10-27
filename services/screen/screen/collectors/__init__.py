"""Data sources of the screen.

Each collector is one module with `fetch(config) -> dict`. It may raise on any
problem; main.py then keeps showing the previous data and marks the panel stale.
"""
