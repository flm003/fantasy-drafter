"""Start the draft tracker.

    uv run python -m draft_tracker [players.csv]
"""
import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from . import config, scoring
from .state import DraftState
from .ui import MainWindow

MAX_PROBLEMS_SHOWN = 25


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fantasy basketball draft tracker")
    ap.add_argument("csv", nargs="?", type=Path, default=config.CSV_PATH,
                    help=f"players CSV from yahoo_to_csv.py (default: {config.CSV_PATH})")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Draft Tracker")
    try:
        df, problems = scoring.load_players(args.csv)
        pool = scoring.build_pool(df)
    except (OSError, ValueError) as e:
        QMessageBox.critical(None, "Draft Tracker", f"Could not load {args.csv}:\n{e}")
        return 1

    state_path = args.csv.parent / config.STATE_FILENAME
    state, state_problems = DraftState.load(state_path, set(pool.names))
    problems += state_problems

    window = MainWindow(pool, state, state_path)
    window.show()
    if problems:
        shown = problems[:MAX_PROBLEMS_SHOWN]
        if len(problems) > len(shown):
            shown.append(f"…and {len(problems) - len(shown)} more.")
        QMessageBox.warning(window, "Check your data", "\n".join(shown))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
