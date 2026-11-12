"""Qt table model for the available-player list, plus the search filter."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont

from .config import CATEGORIES
from .names import fold

SORT_ROLE = Qt.UserRole
PLAYER_ROLE = Qt.UserRole + 1

COL_YAHOO, COL_NAME, COL_POS, COL_TEAM, COL_SCORE = range(5)
CAT_START = 5
COL_NOTES = CAT_START + len(CATEGORIES)
HEADERS = ["Yahoo", "Name", "Pos", "Team", "Score", *CATEGORIES, "Notes"]

GOOD = QColor(46, 160, 67)
BAD = QColor(218, 54, 51)


def tint(value, full_at=2.0):
    """Green for positive, red for negative, stronger with size."""
    strength = min(abs(value) / full_at, 1.0)
    color = QColor(GOOD if value > 0 else BAD)
    color.setAlpha(int(25 + 150 * strength))
    return color


class AvailableModel(QAbstractTableModel):
    def __init__(self, pool, state, on_notes_changed, parent=None):
        super().__init__(parent)
        self.pool = pool
        self.state = state
        self.on_notes_changed = on_notes_changed
        self.ev = None
        self.rows = []
        self._folded = [fold(n) for n in pool.names]
        self._yahoo = [int(r) if r.strip().isdigit() else 10**6 for r in pool.pre_rank]

    def set_evaluation(self, ev):
        self.beginResetModel()
        self.ev = ev
        self.rows = ev.available
        self.endResetModel()
        self.headerDataChanged.emit(Qt.Horizontal, CAT_START, COL_NOTES - 1)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(HEADERS)

    def flags(self, index):
        flags = super().flags(index)
        return flags | Qt.ItemIsEditable if index.column() == COL_NOTES else flags

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        is_cat = CAT_START <= section < COL_NOTES
        if role == Qt.InitialSortOrderRole:
            # First click on a number column puts the biggest values on top.
            return Qt.DescendingOrder if section == COL_SCORE or is_cat else Qt.AscendingOrder
        if role == Qt.DisplayRole:
            if is_cat and self.ev is not None:
                return f"{HEADERS[section]}\n×{self.ev.weights[section - CAT_START]:.2f}"
            return HEADERS[section]
        if role == Qt.ToolTipRole:
            if is_cat:
                c = section - CAT_START
                return (f"Contribution: z-score × G-score factor {self.pool.g_factor[c]:.2f}"
                        f" × need weight (shown).\n"
                        "Need weight is 1 when you project level with or behind a typical\n"
                        "opponent, and drops as your projected lead grows.")
            if section == COL_SCORE:
                return "Sum of the seven contributions; the list is ranked by this"
            if section == COL_YAHOO:
                return ("Yahoo pre-season rank, display only (never used in the score):\n"
                        "roughly where other teams will take him")
            if section == COL_NOTES:
                return "Your notes (double-click or F2 to edit); saved with the draft"
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        i = self.rows[row]
        p, ev = self.pool, self.ev
        cat = col - CAT_START if CAT_START <= col < COL_NOTES else None

        if role == PLAYER_ROLE:
            return i
        if role == Qt.DisplayRole:
            if col == COL_YAHOO:
                return p.pre_rank[i]
            if col == COL_NAME:
                return p.names[i]
            if col == COL_POS:
                return p.positions[i]
            if col == COL_TEAM:
                return p.teams[i]
            if col == COL_SCORE:
                return f"{ev.scores[i]:.2f}"
            if cat is not None:
                return f"{ev.contributions[i, cat]:+.2f}"
            if col == COL_NOTES:
                return self.state.notes.get(p.names[i], "")
        if role == Qt.EditRole and col == COL_NOTES:
            return self.state.notes.get(p.names[i], "")
        if role == SORT_ROLE:
            if col == COL_YAHOO:
                return self._yahoo[i]
            if col == COL_NAME:
                return self._folded[i]
            if col == COL_SCORE:
                return float(ev.scores[i])
            if cat is not None:
                return float(ev.contributions[i, cat])
            return self.data(index, Qt.DisplayRole)
        if role == Qt.TextAlignmentRole and (col in (COL_YAHOO, COL_SCORE) or cat is not None):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.BackgroundRole and cat is not None:
            return tint(ev.contributions[i, cat])
        if role == Qt.FontRole and col == COL_SCORE:
            font = QFont()
            font.setBold(True)
            return font
        if role == Qt.ToolTipRole:
            if col == COL_NAME:
                return f"{p.teams[i]} · {p.positions[i]} · {p.gp[i]:.0f} GP projected"
            if cat is not None:
                return (f"{p.totals[i, cat]:.0f} {CATEGORIES[cat]} ({p.per_game[i, cat]:.2f}/game)\n"
                        f"z {p.z[i, cat]:+.2f} × G-score {p.g_factor[cat]:.2f}"
                        f" × need {ev.weights[cat]:.2f}"
                        f" = {ev.contributions[i, cat]:+.2f}")
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or index.column() != COL_NOTES:
            return False
        self.state.set_note(self.pool.names[self.rows[index.row()]], str(value))
        self.dataChanged.emit(index, index)
        self.on_notes_changed()
        return True

    def row_of(self, player):
        try:
            return self.rows.index(player)
        except ValueError:
            return -1


class SearchProxy(QSortFilterProxyModel):
    """Sorts by SORT_ROLE and filters on an accent-insensitive name match."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.needle = ""
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)

    def set_query(self, text):
        self.needle = fold(text.strip())
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self.needle:
            return True
        name = self.sourceModel().index(source_row, COL_NAME, source_parent).data(SORT_ROLE)
        return self.needle in name
