"""
Bader-Ofer (largest averages / Jefferson-D'Hondt) seat allocation for the Knesset,
including the 3.25% electoral threshold and surplus-vote agreements (heskemei odafim).

How it really works (per Basic Law: The Knesset + Knesset Elections Law):
1. Parties below 3.25% of valid votes are eliminated.
2. A "moded" (divisor) allocates 120 seats among passing lists by highest averages,
   where two lists with a surplus agreement are treated as ONE joint list.
3. Seats inside a joint list are then split between the pair by the same method.
"""

def _highest_averages(votes: dict[str, float], seats: int) -> dict[str, int]:
    """Jefferson / D'Hondt highest-averages allocation."""
    alloc = {p: 0 for p in votes}
    for _ in range(seats):
        best = max(votes, key=lambda p: votes[p] / (alloc[p] + 1))
        alloc[best] += 1
    return alloc


def allocate(votes: dict[str, float],
             agreements: list[tuple[str, str]] | None = None,
             threshold: float = 0.0325,
             total_seats: int = 120) -> dict[str, int]:
    """
    votes: {party: raw vote count (or share — only ratios matter)}
    agreements: list of (partyA, partyB) surplus-vote agreement pairs.
    Returns {party: seats} for ALL parties (0 for those below threshold).
    """
    agreements = agreements or []
    total = sum(votes.values())
    passing = {p: v for p, v in votes.items() if v / total >= threshold}
    result = {p: 0 for p in votes}
    if not passing:
        return result

    # Build joint lists: an agreement only counts if BOTH parties passed.
    joint: dict[str, dict[str, float]] = {}
    used = set()
    for a, b in agreements:
        if a in passing and b in passing and a not in used and b not in used:
            joint[f"{a}+{b}"] = {a: passing[a], b: passing[b]}
            used.update((a, b))
    for p, v in passing.items():
        if p not in used:
            joint[p] = {p: v}

    # Stage 1: allocate 120 seats among joint lists.
    stage1 = _highest_averages({k: sum(v.values()) for k, v in joint.items()},
                               total_seats)
    # Stage 2: split each joint list's seats internally by the same method.
    for k, members in joint.items():
        if len(members) == 1:
            result[next(iter(members))] = stage1[k]
        else:
            inner = _highest_averages(members, stage1[k])
            for p, s in inner.items():
                result[p] = s
    return result


if __name__ == "__main__":
    # === Verification against the OFFICIAL 2022 (25th Knesset) results ===
    votes_2022 = {
        "Likud": 1_115_336, "Yesh Atid": 847_435, "RZP": 516_470,
        "National Unity": 432_482, "Shas": 392_964, "UTJ": 280_194,
        "Yisrael Beiteinu": 213_687, "Ra'am": 194_047, "Hadash-Ta'al": 178_735,
        "Labor": 175_992, "Meretz": 150_793, "Balad": 138_617,
        "Jewish Home": 56_775, "Others": 71_603,
    }
    agreements_2022 = [
        ("Likud", "RZP"), ("Shas", "UTJ"),
        ("Yesh Atid", "National Unity"), ("Labor", "Meretz"),
    ]
    expected = {
        "Likud": 32, "Yesh Atid": 24, "RZP": 14, "National Unity": 12,
        "Shas": 11, "UTJ": 7, "Yisrael Beiteinu": 6, "Ra'am": 5,
        "Hadash-Ta'al": 5, "Labor": 4, "Meretz": 0, "Balad": 0,
        "Jewish Home": 0, "Others": 0,
    }
    got = allocate(votes_2022, agreements_2022)
    for p in expected:
        mark = "OK " if got[p] == expected[p] else "FAIL"
        print(f"{mark} {p:<18} expected {expected[p]:>2}  got {got[p]:>2}")
    assert got == expected, "Bader-Ofer implementation does not match official 2022 results!"
    print("\n✓ Matches the official 25th Knesset results exactly.\n")
