from draft_tracker.names import fold, name_keys, read_picks

# Shape of a real paste from the Yahoo draft room.
DRAFT_ROOM = """1
Drafter A
[V. Wembanyama]
V. Wembanyama

    C
    SAS

Drafter B
Drafter B joined
Drafter C
Drafter C joined
2
Drafter D
[N. Jokić]
N. Jokić

    C
    DEN

3
Drafter C
[L. Dončić]
L. Dončić
Q

    PG,SG
    LAL

4
You
[S. Gilgeous-Alexander]
S. Gilgeous-Alexander

    PG
    OKC

5
Drafter E
[D. Mitchell]
D. Mitchell

    PG
    MIA
"""

PLAYERS = [  # (name, team)
    ("Victor Wembanyama", "SAS"), ("Nikola Jokić", "DEN"), ("Luka Dončić", "LAL"),
    ("Shai Gilgeous-Alexander", "OKC"), ("Donovan Mitchell", "CLE"), ("Davion Mitchell", "MIA"),
    ("Kel'el Ware", "MIA"), ("Karl-Anthony Towns", "NYK"), ("N. Alexander-Walker", "ATL"),
    ("Jaren Jackson Jr.", "MEM"), ("Amen Thompson", "HOU"), ("Ausar Thompson", "DET"),
]
NAMES = [n for n, _ in PLAYERS]
TEAMS = [t for _, t in PLAYERS]


def read(text):
    return read_picks(text, NAMES, TEAMS)


def picked(result):
    return [(NAMES[i], mine) for i, mine in result.picks]


def test_fold_strips_accents_and_case():
    assert fold("Nikola JOKIĆ") == "nikola jokic"


def test_short_forms_follow_yahoo():
    assert "k ware" in name_keys("Kel'el Ware")
    assert "k towns" in name_keys("Karl-Anthony Towns")
    assert "j jackson jr" in name_keys("Jaren Jackson Jr.")
    assert "n alexander walker" in name_keys("N. Alexander-Walker")


def test_reads_a_draft_room_paste():
    result = read(DRAFT_ROOM)
    assert picked(result) == [
        ("Victor Wembanyama", False), ("Nikola Jokić", False), ("Luka Dončić", False),
        ("Shai Gilgeous-Alexander", True), ("Davion Mitchell", False),
    ]
    assert result.ambiguous == [] and result.unknown == []


def test_names_outside_pick_blocks_are_ignored():
    # Chat, drafter names and "joined" lines have no positions/team block after them.
    assert read("Victor Wembanyama joined\nNikola Jokic\nchat: take Luka Dončić!").picks == []


def test_pick_without_brackets_is_read_from_its_block():
    text = ("6\nJohn\nN. Jokić\n\n    C\n    DEN\n"              # no [bracketed] name at all
            "7\nYou\n[V. Wembanyama]\n\n    C\n    SAS\n")       # bracket but no plain repeat
    assert picked(read(text)) == [("Nikola Jokić", False), ("Victor Wembanyama", True)]


def test_paste_starting_mid_pick():
    # The selection began below the first pick's bracket.
    text = "L. Dončić\nQ\n\n    PG,SG\n    LAL\n\n4\nYou\n[S. Gilgeous-Alexander]\nS. Gilgeous-Alexander\n  PG\n  OKC\n"
    assert picked(read(text)) == [("Luka Dončić", False), ("Shai Gilgeous-Alexander", True)]


def test_unrecognised_name_in_a_block_is_reported():
    result = read("3\nDrafter C\n[Z. Newguy]\nZ. Newguy\n\n    SF\n    BOS\n")
    assert result.picks == [] and result.unknown == ["Z. Newguy"]


def test_team_settles_look_alikes():
    text = "1\nA\n[A. Thompson]\nA. Thompson\n  SF\n  DET\n2\nB\n[A. Thompson]\nA. Thompson\n  SG\n  HOU\n"
    assert picked(read(text)) == [("Ausar Thompson", False), ("Amen Thompson", False)]


def test_last_pick_in_paste_gets_its_team():
    text = "9\nZed\n[D. Mitchell]\nD. Mitchell\nQ\n\n    PG,SG\n    CLE"
    assert picked(read(text)) == [("Donovan Mitchell", False)]


def test_team_comes_only_from_the_picks_own_block():
    # The pick was cut off before its team; "MIA" in the chat below must not be used.
    text = "5\nDrafter E\n[D. Mitchell]\nD. Mitchell\n\nDrafter E\nwho needs a MIA guard?\n"
    result = read(text)
    assert result.picks == [] and result.ambiguous[0][1] == ""


def test_status_line_is_skipped():
    text = "3\nDrafter C\n[A. Thompson]\nA. Thompson\nGTD\n\n    SF,PF\n    DET\n"
    assert picked(read(text)) == [("Ausar Thompson", False)]


def test_look_alike_without_team_is_ambiguous():
    result = read("[D. Mitchell]")
    assert result.picks == []
    assert [NAMES[i] for i in result.ambiguous[0][2]] == ["Donovan Mitchell", "Davion Mitchell"]


def test_unknown_names_are_reported_once():
    result = read("[Z. Nobody]\n  PG\n  BOS\n[Z. Nobody]")
    assert result.picks == [] and result.unknown == ["Z. Nobody"]


def test_repeated_pick_is_read_once():
    result = read(DRAFT_ROOM + DRAFT_ROOM)
    assert len(result.picks) == 5


def test_apostrophe_and_hyphen_first_names():
    text = "1\nX\n[K. Ware]\n  C\n  MIA\n2\nY\n[K. Towns]\n  C\n  NYK\n"
    assert picked(read(text)) == [("Kel'el Ware", False), ("Karl-Anthony Towns", False)]


# Shape of a paste from the live draft's results list.
LIVE_DRAFT = """Team Alpha
Nikola Jokić
DEN - C
1st
Team Beta
Victor Wembanyama
SAS - C
2nd
Team Alpha left the draft
Team Gamma left the draft
Team Mine
Davion Mitchell
MIA - PG
3rd
Team Delta
Kel'el Ware
MIA - C
4th
"""


def test_reads_a_live_draft_paste():
    result = read_picks(LIVE_DRAFT, NAMES, TEAMS, ["team mine"])
    assert [(NAMES[i], mine) for i, mine in result.picks] == [
        ("Nikola Jokić", False), ("Victor Wembanyama", False),
        ("Davion Mitchell", True), ("Kel'el Ware", False),
    ]
    assert result.ambiguous == [] and result.unknown == []


def test_live_draft_unknown_name_is_reported():
    result = read("Team Delta\nZed Newguy\nMIA - SF\n9th\n")
    assert result.picks == [] and result.unknown == ["Zed Newguy"]


def test_both_layouts_in_one_paste():
    assert len(read(DRAFT_ROOM + LIVE_DRAFT).picks) == 6
