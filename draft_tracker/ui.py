"""Main window: available list on the left, my roster on the right."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTableView, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import config, names, scoring
from .config import CATEGORIES, ROSTER_SIZE
from .model import COL_NAME, COL_NOTES, COL_SCORE, PLAYER_ROLE, AvailableModel, SearchProxy, tint
from .state import MINE, TAKEN

ROSTER_HEADERS = ["#", "Name", "Team", "Pos", *CATEGORIES]
ROSTER_CAT_START = 4
TOTALS_ROW = ROSTER_SIZE
WEIGHT_ROW = ROSTER_SIZE + 1
MULT_ROW = ROSTER_SIZE + 2
# Projected edges over a typical opponent within this distance of 0 count as a
# toss-up and show yellow in the totals; beyond it, green (ahead) or red (behind).
EDGE_HIGHLIGHT = 0.15
CLOSE = QColor(230, 180, 0, 110)


class MainWindow(QMainWindow):
    def __init__(self, pool, state, state_path):
        super().__init__()
        self.pool = pool
        self.state = state
        self.state_path = state_path
        self.ev = None
        self.paste_box = None  # built with the roster panel; eventFilter runs before that

        self.model = AvailableModel(pool, state, self._save, self)
        self.proxy = SearchProxy(self)
        self.proxy.setSourceModel(self.model)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_list_panel())
        splitter.addWidget(self._build_roster_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        self.picks_label = QLabel()
        self.statusBar().addPermanentWidget(self.picks_label)
        self._build_shortcuts()

        self.resize(1600, 850)
        self._refresh()
        self.search.setFocus()

    # ------------------------------------------------------------ build ----
    def _build_list_panel(self):
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search name   ·   ↑/↓ move   ·   Enter = taken   ·   Shift+Enter = mine   ·   Esc clears")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        self.search.installEventFilter(self)

        undo_btn = QPushButton("Undo (Ctrl+Z)")
        undo_btn.clicked.connect(self._undo)
        new_btn = QPushButton("New draft…")
        new_btn.clicked.connect(self._new_draft)

        top = QHBoxLayout()
        top.addWidget(QLabel("Search:"))
        top.addWidget(self.search, 1)
        top.addWidget(undo_btn)
        top.addWidget(new_btn)

        t = self.table = QTableView()
        t.setModel(self.proxy)
        # Header clicks cycle: sort (numbers high-first), reverse, then back to the
        # recommended order. Unsorted, the proxy shows the model's rows, which are
        # already ranked best first.
        t.horizontalHeader().setSortIndicatorClearable(True)
        t.setSortingEnabled(True)
        t.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        t.verticalHeader().hide()
        header = t.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_NOTES, QHeaderView.Stretch)
        header.setDefaultAlignment(Qt.AlignCenter)
        # Double-click a row = mine, right-click = taken (Notes keeps double-click to edit).
        t.doubleClicked.connect(self._on_double_click)
        t.setContextMenuPolicy(Qt.CustomContextMenu)
        t.customContextMenuRequested.connect(self._on_right_click)

        hint = QLabel("Double-click = mine  ·  Right-click = taken  ·  "
                      "Ctrl+M / Ctrl+T mark the selected row  ·  F2 edits notes\n"
                      "Click a header to sort, again to reverse, a third time to return "
                      "to the recommended order")

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(t, 1)
        layout.addWidget(hint)
        panel = QWidget()
        panel.setLayout(layout)
        return panel

    def _build_roster_panel(self):
        self.roster_title = QLabel()
        font = self.roster_title.font()
        font.setPointSizeF(font.pointSizeF() * 1.3)
        font.setBold(True)
        self.roster_title.setFont(font)

        r = self.roster = QTableWidget(MULT_ROW + 1, len(ROSTER_HEADERS))
        r.setHorizontalHeaderLabels(ROSTER_HEADERS)
        r.verticalHeader().hide()
        r.verticalHeader().setDefaultSectionSize(r.fontMetrics().height() + 8)
        r.setEditTriggers(QAbstractItemView.NoEditTriggers)
        r.setSelectionMode(QAbstractItemView.NoSelection)
        r.setFocusPolicy(Qt.NoFocus)
        r.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        r.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for row, label in ((TOTALS_ROW, "Team per game"), (WEIGHT_ROW, "Need weight"),
                           (MULT_ROW, "G-score factor")):
            r.setSpan(row, 0, 1, ROSTER_CAT_START)
            r.setItem(row, 0, self._cell(label, bold=True))
        for c, m in enumerate(self.pool.g_factor):
            item = self._cell(f"{m:.2f}", align=Qt.AlignRight)
            item.setToolTip("How reliably an edge in this category wins a week (fixed for the draft)")
            r.setItem(MULT_ROW, ROSTER_CAT_START + c, item)
        # Size the table to its rows so the paste box gets the rest of the panel.
        r.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        r.setFixedHeight(r.horizontalHeader().sizeHint().height()
                         + r.verticalHeader().defaultSectionSize() * r.rowCount()
                         + r.horizontalScrollBar().sizeHint().height() + 2 * r.frameWidth())

        self.center_label = QLabel()
        # Explicit line breaks rather than word wrap: wrapped labels get too little
        # height inside a splitter and overlap their neighbours.
        legend = QLabel(f"vs a typical opponent ({config.TEAMS}-team league): red = behind, "
                        "yellow = toss-up, green = ahead (hover for detail).\n"
                        "Big leads get less need weight. Yahoo rank is display only. "
                        f"TO need weight is capped at {scoring.WEIGHT_MAX[CATEGORIES.index('TO')]:.1f}.")

        layout = QVBoxLayout()
        layout.addWidget(self.roster_title)
        layout.addWidget(r)
        layout.addWidget(self.center_label)
        layout.addWidget(legend)
        layout.addWidget(self._build_paste_box(), 1)
        panel = QWidget()
        panel.setLayout(layout)
        return panel

    def _build_paste_box(self):
        """Paste draft-room text; every [bracketed] player in it is marked."""
        self.paste_box = QPlainTextEdit()
        self.paste_box.setPlaceholderText(
            "Paste the draft room's pick list here, then press Ctrl+Enter.\n\n"
            "Works with both the mock-draft and live-draft layouts. Every pick is marked taken, "
            "or mine when the drafter is one of MY_TEAM_NAMES in config.py (“You” by default). Chat lines are ignored. The team code under each name settles look-alikes such as "
            "D. Mitchell. Picks already marked are skipped, so pasting the whole list again is fine.")
        self.paste_box.installEventFilter(self)
        paste_btn = QPushButton("Mark pasted picks (Ctrl+Enter)")
        paste_btn.clicked.connect(self._mark_pasted)
        # A read-only text area rather than a QLabel: wrapped labels don't get
        # enough height inside a splitter, so long results were cut off.
        self.paste_result = QPlainTextEdit()
        self.paste_result.setReadOnly(True)
        self.paste_result.setFocusPolicy(Qt.NoFocus)
        self.paste_result.setFrameShape(QFrame.NoFrame)
        self.paste_result.setFixedHeight(self.paste_result.fontMetrics().lineSpacing() * 5 + 8)
        self.paste_result.viewport().setAutoFillBackground(False)

        buttons = QHBoxLayout()
        buttons.addWidget(paste_btn)
        buttons.addStretch(1)
        layout = QVBoxLayout()
        layout.addWidget(self.paste_box, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.paste_result)
        box = QGroupBox("Catch up from the draft room")
        box.setLayout(layout)
        return box

    def _build_shortcuts(self):
        for keys, slot in (("Ctrl+M", lambda: self._mark(MINE)),
                           ("Ctrl+T", lambda: self._mark(TAKEN)),
                           (QKeySequence.Undo, self._undo),
                           (QKeySequence.Find, self._focus_search)):
            QShortcut(QKeySequence(keys), self, activated=slot)

    @staticmethod
    def _cell(text, bold=False, align=Qt.AlignLeft):
        item = QTableWidgetItem(text)
        item.setTextAlignment(int(align | Qt.AlignVCenter))
        if bold:
            font = QFont()
            font.setBold(True)
            item.setFont(font)
        return item

    # ----------------------------------------------------------- events ----
    def eventFilter(self, obj, event):
        if obj is self.search:
            if event.type() == QEvent.ShortcutOverride and event.matches(QKeySequence.Undo):
                # Let Ctrl+Z undo the last pick instead of editing the search text.
                event.ignore()
                return True
            if event.type() == QEvent.KeyPress:
                key = event.key()
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    self._mark(MINE if event.modifiers() & Qt.ShiftModifier else TAKEN)
                    return True
                steps = {Qt.Key_Up: -1, Qt.Key_Down: 1, Qt.Key_PageUp: -10, Qt.Key_PageDown: 10}
                if key in steps:
                    self._move_selection(steps[key])
                    return True
                if key == Qt.Key_Escape:
                    self.search.clear()
                    return True
        if obj is self.paste_box and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
                self._mark_pasted()
                return True
        return super().eventFilter(obj, event)

    def _focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _on_search(self, text):
        self.proxy.set_query(text)
        self._select_proxy_row(0)

    def _select_proxy_row(self, row):
        count = self.proxy.rowCount()
        if count == 0:
            self.table.clearSelection()
            return
        row = max(0, min(row, count - 1))
        index = self.proxy.index(row, COL_NAME)
        self.table.selectionModel().setCurrentIndex(
            index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        self.table.scrollTo(index)

    def _move_selection(self, delta):
        current = self.table.selectionModel().currentIndex()
        self._select_proxy_row(current.row() + delta if current.isValid() else 0)

    def _selected_player(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].data(PLAYER_ROLE) if rows else None

    def _on_double_click(self, index):
        if index.column() != COL_NOTES:
            self._mark(MINE, index.data(PLAYER_ROLE))

    def _on_right_click(self, pos):
        index = self.table.indexAt(pos)
        if index.isValid():
            self._mark(TAKEN, index.data(PLAYER_ROLE))

    # ---------------------------------------------------------- actions ----
    def _mark(self, result, player=None):
        """Mark a player (default: the selected row) as mine or taken."""
        i = self._selected_player() if player is None else player
        if i is None:
            self.statusBar().showMessage("No player selected.", 4000)
            return
        if result == MINE and len(self.state.mine()) >= ROSTER_SIZE:
            self.statusBar().showMessage(f"Your roster is already full ({ROSTER_SIZE} players).", 6000)
            return
        name = self.pool.names[i]
        self.state.add(name, result)
        self._save()
        self._refresh()
        self.search.clear()
        self.search.setFocus()
        where = "drafted by you" if result == MINE else "taken"
        self.statusBar().showMessage(f"{name} {where}.", 6000)

    def _mark_pasted(self):
        text = self.paste_box.toPlainText()
        if not text.strip():
            self.paste_result.setPlainText("Nothing pasted.")
            return
        parsed = names.read_picks(text, self.pool.names, self.pool.teams,
                                  config.MY_TEAM_NAMES)
        picked = self.state.picked()
        room = ROSTER_SIZE - len(self.state.mine())
        new = []  # (name, result) in draft order
        for i, by_me in parsed.picks:
            name = self.pool.names[i]
            if name not in picked:
                yours = by_me and sum(r == MINE for _, r in new) < room
                new.append((name, MINE if yours else TAKEN))
        mine = [n for n, r in new if r == MINE]
        taken = [n for n, r in new if r == TAKEN]

        if new:
            batch = self.state.new_batch()
            for name, result in new:
                self.state.add(name, result, batch)
            self._save()
            self.search.clear()
            self._refresh()
        # Clear the box whenever it held picks, even if all were already marked; keep
        # it only when no pick was found at all, so a bad paste can be checked.
        if parsed.picks or parsed.ambiguous or parsed.unknown:
            self.paste_box.clear()

        # Problems first: the box shows about five lines, and a long list of
        # marked names must not push a missed pick out of view.
        lines = []
        if not parsed.picks and not parsed.ambiguous and not parsed.unknown:
            lines.append("⚠ No picks found in the pasted text.")
        for pasted, team, candidates in parsed.ambiguous:
            options = " / ".join(self.pool.names[i] for i in candidates
                                 if self.pool.names[i] not in picked)
            if options:
                lines.append(f"⚠ Not sure who {pasted}{' (' + team + ')' if team else ''} is: "
                             f"{options}. Mark by hand.")
        if parsed.unknown:
            lines.append(f"⚠ Not in your player list, ignored: {', '.join(parsed.unknown)}")
        if mine:
            lines.append("Yours: " + ", ".join(mine))
        lines.append(f"Marked {len(taken)} taken" + (": " + ", ".join(taken) if taken else "."))
        skipped = len(parsed.picks) - len(mine) - len(taken)
        if skipped:
            lines.append(f"{skipped} pick{' was' if skipped == 1 else 's were'} already marked.")
        if mine or taken:
            lines.append("Ctrl+Z undoes this whole paste.")
        self.paste_result.setPlainText("\n".join(lines))
        self._log_paste(text, lines)
        self.search.setFocus()

    def _log_paste(self, text, result_lines):
        """Append the raw paste and what it produced, so a missed pick can be traced."""
        path = Path(self.state_path).with_name(config.PASTE_LOG_FILENAME)
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text.rstrip()}\n"
                         "----- result -----\n" + "\n".join(result_lines) + "\n\n")
        except OSError:
            pass  # a logging failure must never interrupt the draft

    def _undo(self):
        removed = self.state.undo()
        if not removed:
            self.statusBar().showMessage("Nothing to undo.", 4000)
            return
        self._save()
        self.search.clear()
        self._refresh()
        # Select a player that came back so it's easy to re-mark.
        last = removed[-1]
        self._select_proxy_row(self.proxy.mapFromSource(
            self.model.index(self.model.row_of(self.pool.index[last.player]), 0)).row())
        if len(removed) == 1:
            message = f"Undid {last.player} ({last.result})."
        else:
            message = f"Undid the pasted batch of {len(removed)} picks."
        self.statusBar().showMessage(message, 6000)

    def _new_draft(self):
        if not self.state.picks:
            self.statusBar().showMessage("The draft is already empty.", 4000)
            return
        answer = QMessageBox.question(
            self, "New draft",
            f"Clear all {len(self.state.picks)} picks and start a new draft?\n"
            "Your player notes are kept.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        self.state.clear()
        self._save()
        self.search.clear()
        self._refresh()
        self.statusBar().showMessage("Started a new draft.", 6000)

    def _save(self):
        try:
            self.state.save(self.state_path)
        except OSError as e:
            QMessageBox.critical(self, "Save failed", f"Could not save {self.state_path}:\n{e}")

    # ---------------------------------------------------------- refresh ----
    def _refresh(self):
        index = self.pool.index
        self.ev = scoring.evaluate(self.pool,
                                   [index[n] for n in self.state.mine()],
                                   [index[n] for n in self.state.taken()])
        self.model.set_evaluation(self.ev)
        self._fill_roster()

        n_picks = len(self.state.picks)
        self.picks_label.setText(f"{n_picks} picks made · {len(self.ev.available)} players left")
        self.setWindowTitle(f"Draft Tracker — next pick #{n_picks + 1}")
        self._select_proxy_row(0)

    def _fill_roster(self):
        p, ev, r = self.pool, self.ev, self.roster
        mine = ev.mine
        self.roster_title.setText(f"My team ({len(mine)} of {ROSTER_SIZE})")

        for row in range(ROSTER_SIZE):
            if row < len(mine):
                i = mine[row]
                values = [p.names[i], p.teams[i], p.positions[i]]
                values += [f"{v:.2f}" for v in p.per_game[i]]
            else:
                values = [""] * (len(ROSTER_HEADERS) - 1)
            r.setItem(row, 0, self._cell(str(row + 1), align=Qt.AlignRight))
            for col, text in enumerate(values, 1):
                align = Qt.AlignRight if col >= ROSTER_CAT_START else Qt.AlignLeft
                r.setItem(row, col, self._cell(text, align=align))

        totals = p.per_game[mine].sum(axis=0)
        for c, cat in enumerate(CATEGORIES):
            col = ROSTER_CAT_START + c
            w, edge = ev.weights[c], ev.edge[c]
            total = self._cell(f"{totals[c]:.2f}", bold=True, align=Qt.AlignRight)
            weight = self._cell(f"×{w:.2f}", align=Qt.AlignRight)
            # Color by the projected edge over a typical opponent, not by the
            # weight: deficits all get weight 1, and TO is capped regardless.
            # No colors until I've drafted someone: before that every edge is 0.
            if mine:
                color = tint(edge, full_at=1.0) if abs(edge) > EDGE_HIGHLIGHT else CLOSE
                total.setBackground(color)
                weight.setBackground(color)
            if abs(edge) <= EDGE_HIGHLIGHT:
                standing = "close to (a toss-up with)"
            else:
                standing = "ahead of" if edge > 0 else "behind"
            tip = (f"{cat}: projected {standing} a typical opponent, edge {edge:+.2f} weekly spreads\n"
                   f"(full rosters: you {ev.projected_me[c]:+.1f}, opponent {ev.projected_opp[c]:+.1f}"
                   f" in G-score units). Need weight {w:.2f}.")
            total.setToolTip(tip)
            weight.setToolTip(tip)
            r.setItem(TOTALS_ROW, col, total)
            r.setItem(WEIGHT_ROW, col, weight)

        centers = sum("C" in p.positions[i].split(",") for i in mine)
        self.center_label.setText(f"C-eligible on roster: {centers}")
