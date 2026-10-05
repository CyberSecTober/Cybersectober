#!/usr/bin/env python3
"""Creates challenge issues listed in data/challenges.json that don't exist yet (matched by title)."""
import json
import os
import urllib.request

REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ.get("GITHUB_TOKEN", "")
DRY_RUN = os.environ.get("DRY_RUN") == "1"
BLOB = f"https://github.com/{REPO}/blob/main"


def api(path, method="GET", body=None):
    req = urllib.request.Request(f"https://api.github.com{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or "null")


def existing_titles():
    titles, page = set(), 1
    while True:
        batch = api(f"/repos/{REPO}/issues?state=all&per_page=100&page={page}")
        titles |= {i["title"] for i in batch}
        if len(batch) < 100:
            return titles
        page += 1


def body(c):
    reward = (str(c["points"]) if c["points"] else "No points: awareness posts earn the Awareness Advocate, "
              "Signal Booster and Awareness Ambassador badges")
    return (f"### Track\n\n{c['track']}\n\n### Difficulty\n\n{c['difficulty']}\n\n### Points\n\n{reward}\n\n"
            f"### What to build\n\n{c['what']}\n\n### Done when\n\n{c['done']}\n\n"
            f"### Helpful resources\n\n- Step-by-step instructions: [README](https://github.com/{REPO}#readme)\n"
            f"- Rules and safety: [CONTRIBUTING.md]({BLOB}/CONTRIBUTING.md)\n\n---\n"
            + ("**Open to everyone.** No need to claim this challenge: anyone can do it, and everyone who completes it "
               "earns the reward. One contribution per pull request." if "open-to-all" in c["labels"] else
               "Comment **\"I'll take this\"** to claim it (held for 5 days). Please read the safety rules in "
               "CONTRIBUTING.md before you start."))


def main():
    challenges = json.load(open("data/challenges.json", encoding="utf-8"))
    have = existing_titles()
    for c in challenges:
        if c["title"] in have:
            print(f"exists, skipped: {c['title']}")
            continue
        if DRY_RUN:
            print(f"would create: {c['title']}  labels={c['labels']}")
            continue
        issue = api(f"/repos/{REPO}/issues", "POST", {"title": c["title"], "body": body(c), "labels": c["labels"]})
        print(f"created #{issue['number']}: {c['title']}")


if __name__ == "__main__":
    main()
