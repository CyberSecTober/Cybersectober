#!/usr/bin/env python3
"""Posts the leaderboard standings to the "Leaderboard updates" issue every two days.

Each contributor is @mentioned with their rank and what it takes to move up, so GitHub emails them. Anyone can stop
the updates by commenting "unsubscribe" on that issue (and "subscribe" to start again). Nothing is posted when the
standings have not changed since the last update. Reads the same data as award_badges.py and never runs PR code.
"""
import hashlib
import re

import award_badges as ab

TITLE = "Leaderboard updates"
LABEL = "leaderboard"
MARKER = "<!-- cybersectober-standings -->"
INTRO = ("Every two days the CyberSecTOBER bot posts where everyone stands on the "
         f"[leaderboard]({ab.SITE_URL}). Comment **unsubscribe** here to stop being mentioned, or **subscribe** to "
         "start again.")


def tracking_issue():
    for i in ab.paginate(f"/repos/{ab.REPO}/issues?state=open&labels={LABEL}"):
        if i["title"] == TITLE and i["user"]["type"] == "Bot":
            return i
    if ab.DRY_RUN:
        return None
    try:
        ab.api(f"/repos/{ab.REPO}/labels", "POST",
               {"name": LABEL, "color": "DB2777", "description": "Leaderboard standings posted by the bot"})
    except Exception:
        pass  # the label already exists
    return ab.api(f"/repos/{ab.REPO}/issues", "POST", {"title": TITLE, "body": INTRO, "labels": [LABEL]})


def unsubscribed(comments):
    """The latest subscribe or unsubscribe comment from each person wins."""
    off = set()
    for c in comments:
        if c["user"]["type"] == "Bot":
            continue
        words = (c.get("body") or "").lower()
        who = c["user"]["login"].lower()
        if re.search(r"\bunsubscribe\b", words):
            off.add(who)
        elif re.search(r"\bsubscribe\b", words):
            off.discard(who)
    return off


def message(ranked, off):
    top = ranked[0]
    table = "\n".join(f"| {u['rank']} | {u['login']} | {u['points']} | {len(u['badges'])} |" for u in ranked[:10])
    lines = []
    for u in ranked:
        if u["login"].lower() in off:
            continue
        move = ab.standing(u).replace("You are ", "", 1)
        if u["points"] == 0:
            move += " Posts earn badges; tips and challenges earn points."
        lines.append(f"- @{u['login']}: {move}")
    return "\n".join([
        MARKER,
        f"### Leaderboard update, {ab.NOW.strftime('%-d %B')}",
        "",
        f"**{top['login']}** leads with **{top['points']} points**. Here is the top {min(10, len(ranked))}:",
        "",
        "| # | Contributor | Points | Badges |",
        "|---|---|---|---|",
        table,
        "",
        "**Where you stand**",
        "",
        *lines,
        "",
        "**Ways to earn points:** add a security tip (3 points), take an "
        f"[open challenge]({ab.REPO_URL}/issues?q=is%3Aopen+label%3Aopen-to-all) or a "
        f"[claimable one]({ab.REPO_URL}/issues?q=is%3Aopen+is%3Aissue+no%3Aassignee+label%3Apoints-10), "
        f"or play [Shield Up]({ab.SITE_URL}play/), which walks you through each pull request.",
        "",
        "Comment **unsubscribe** on this issue to stop these mentions.",
        "",
        "The CyberSecTOBER team",
    ])


def main():
    counted, _ = ab.split_excluded(ab.merged_prs())
    ranked = ab.compute(counted, {}, ab.load_organizers())
    if not ranked:
        print("No contributors yet; nothing to post.")
        return
    issue = tracking_issue()
    comments = ab.paginate(f"/repos/{ab.REPO}/issues/{issue['number']}/comments") if issue else []
    fingerprint = hashlib.sha256(repr([(u["login"], u["points"], u["rank"]) for u in ranked]).encode()).hexdigest()[:16]
    last = next((c["body"] for c in reversed(comments) if MARKER in (c.get("body") or "")), "")
    if f"<!-- {fingerprint} -->" in last:
        print("Standings unchanged since the last update; nothing posted.")
        return
    body = message(ranked, unsubscribed(comments)) + f"\n<!-- {fingerprint} -->"
    if ab.DRY_RUN or not issue:
        print(f"--- DRY RUN: standings update ---\n{body}\n---")
        return
    ab.api(f"/repos/{ab.REPO}/issues/{issue['number']}/comments", "POST", {"body": body})
    print(f"Posted standings to issue #{issue['number']}.")


if __name__ == "__main__":
    main()
