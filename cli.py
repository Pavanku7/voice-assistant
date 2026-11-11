"""
Meryna — CLI entry point.

Run with ``python cli.py`` (voice mode) or ``python cli.py --text`` for
text-only interaction.

Requirements addressed: 9.2
"""

from interfaces.cli.app import main

if __name__ == "__main__":
    main()
