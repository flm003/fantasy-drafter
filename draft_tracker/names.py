"""Name folding and reading picks from pasted draft-room text. No Qt imports."""
import re
import unicodedata
from dataclasses import dataclass, field

# Yahoo's draft room shows each pick as: pick number, drafter, [F. Lastname]
# (the headshot's alt text), the name again, an optional status (Q, O...),
# positions, then team, e.g.
#
#   4
#   You
#   [S. Gilgeous-Alexander]
#   S. Gilgeous-Alexander
#       PG
#       OKC
#
# The live draft's results list shows each pick as drafter (team name), full
# name, "TEAM - POSITIONS", then the pick's ordinal, e.g.
#
#   My Picks are better
#   Cade Cunningham
#   DET - PG
#   5th
BRACKETED = re.compile(r"\[([^\[\]\n]+)\]")
POSITIONS = re.compile(r"(PG|SG|SF|PF|C|G|F)(,(PG|SG|SF|PF|C|G|F))*")
TEAM_CODE = re.compile(r"[A-Z]{2,4}")
TEAM_AND_POSITIONS = re.compile(r"([A-Z]{2,4}) - (PG|SG|SF|PF|C|G|F)([,/](PG|SG|SF|PF|C|G|F))*")
STATUSES = {"Q", "O", "D", "P", "GTD", "DTD", "INJ", "NA", "SUSP", "OFS", "OUT", "IL", "IL+", "NEW"}
MY_DRAFTER_NAME = "You"  # mock drafts; in the live draft see config.MY_TEAM_NAMES


def fold(text):
    """Lower-case and strip accents, so "jokic" finds "Jokić"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _key(text):
    """Folded words joined by single spaces; punctuation is dropped."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", fold(text)).split())


def name_keys(name):
    """Forms a name may appear in: "Kel'el Ware" -> {"kel el ware", "k ware"}.

    The short form is the first name's initial plus everything after the first
    space, which is how Yahoo abbreviates ("Karl-Anthony Towns" -> "K. Towns").
    """
    keys = {_key(name)}
    first, _, rest = name.strip().partition(" ")
    if rest:
        keys.add(_key(f"{first[0]} {rest}"))
    return keys


@dataclass
class PastedPicks:
    picks: list = field(default_factory=list)      # (player index, by_me) in pick order
    ambiguous: list = field(default_factory=list)  # (name as pasted, team or "", [candidate indices])
    unknown: list = field(default_factory=list)    # names not in the player list


def _find_picks(lines, known_teams):
    """Locate picks in non-empty, stripped lines. Returns (line no., name, team, drafter).

    A pick is anchored on its block's last two lines, a positions line and then a
    known team code, which chat and "joined" lines never have. Its name is the
    [bracketed] text just above (skipping a status line) or, if the bracket is
    missing, the plain name line there. A bracketed name with no block after it
    (a paste cut off mid-pick) still counts, without a team.
    """
    found, used = [], set()
    # Live-draft blocks: drafter, name, "TEAM - POS".
    for k, line in enumerate(lines):
        m = TEAM_AND_POSITIONS.fullmatch(line)
        if m and m.group(1) in known_teams and k >= 1:
            used.update(range(k - 1, k + 1))
            found.append((k - 1, lines[k - 1], m.group(1), lines[k - 2] if k >= 2 else ""))

    for k in range(len(lines) - 1):
        if not (POSITIONS.fullmatch(lines[k]) and lines[k + 1] in known_teams
                and TEAM_CODE.fullmatch(lines[k + 1])):
            continue
        j = k - 1
        while j >= 0 and lines[j].upper() in STATUSES:
            j -= 1
        if j < 0:
            continue
        # The name: prefer the bracket (on this line or the one above), else the plain line.
        start, name = j, lines[j]
        for b in (j, j - 1):
            m = BRACKETED.search(lines[b]) if b >= 0 and b not in used else None
            if m:
                start, name = b, m.group(1).strip()
                break
        used.update(range(start, k + 2))
        drafter = lines[start - 1] if start > 0 else ""
        found.append((start, name, lines[k + 1], drafter))

    for n, line in enumerate(lines):
        if n in used:
            continue
        for m in BRACKETED.finditer(line):
            drafter = lines[n - 1] if n > 0 else ""
            found.append((n, m.group(1).strip(), "", drafter))
    return sorted(found)


def read_picks(text, names, teams, my_drafters=(MY_DRAFTER_NAME,)):
    """Read draft picks from pasted draft-room text.

    Drafter names, chat lines and "X joined" messages are ignored: a pick needs a
    [bracketed] name or a full pick block (name, positions, team). When a short
    name fits several players (e.g. "D. Mitchell"), the team from that pick's own
    block picks the right one. A pick whose drafter line is one of my_drafters
    ("You" in mock drafts, my team's name in the live draft) is flagged as mine.
    """
    mine = {_key(d) for d in my_drafters}
    owners = {}
    for i, name in enumerate(names):
        for key in name_keys(name):
            owners.setdefault(key, []).append(i)
    known_teams = {t for t in teams if t}
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]

    result, seen = PastedPicks(), set()
    for _, pasted, team, drafter in _find_picks(lines, known_teams):
        candidates = owners.get(_key(pasted), [])
        if len(candidates) > 1 and team:
            candidates = [i for i in candidates if teams[i] == team] or candidates
        if not candidates:
            if pasted not in result.unknown:
                result.unknown.append(pasted)
        elif len(candidates) > 1:
            result.ambiguous.append((pasted, team, candidates))
        elif candidates[0] not in seen:
            seen.add(candidates[0])
            result.picks.append((candidates[0], _key(drafter) in mine))
    return result
