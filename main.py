#!/usr/bin/env python3
import os
import sys

os.environ.setdefault("MAVLINK20", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from flightdeck import theme  # noqa: E402
from flightdeck.app import MainWindow  # noqa: E402


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FlightDeck")
    app.setFont(theme.load_fonts())
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet())
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
