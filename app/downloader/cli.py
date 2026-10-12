"""Application entry point."""

import tkinter as tk
from tkinter import ttk

from .gui import run_app


def main() -> int:
    """Launch the tag-search desktop application."""
    run_app()
    return 0
