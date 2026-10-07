#!/usr/bin/env python3
"""Checks every incoming pull request for floods, duplicate posts and duplicate tips.

Runs from the main branch and only reads the pull request through the API; it never
executes contributor code. Exits non-zero when it finds a problem so the PR shows a red check.
"""
import difflib
import json
import os
import re
import sys
import urllib.parse
import urllib.request

REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ.get("GITHUB_TOKEN", "")
PR_NUMBER = int(os.environ["PR_NUMBER"])
DRY_RUN = os.environ.get("DRY_RUN") == "1"
MARKER = "<!-- cybersectober-checks -->"
MAX_OPEN_PRS = 3
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
POSTS_FILE, TIPS_FILE = "awareness/posts.md", "awareness/tips.md"
SOCIAL_DOMAINS = {"linkedin.com", "x.com", "twitter.com", "instagram.com", "facebook.com", "fb.com",
                  "tiktok.com", "threads.net", "threads.com", "youtube.com", "youtu.be", "medium.com", "bsky.app", "substack.com"}
TRACKING = re.compile(r"^(utm_|fbclid$|igsh$|igshid$|si$|s$|t$|ref$|rcm$|trk$|lipi$)")
SIMILAR = 0.85


def api(path, method="GET", body=None):
    req = urllib.request.Request(f"https://api.github.com{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read() or "null")


def paginate(path):
    page, out = 1, []
    sep = "&" if "?" in path else "?"
    while True:
        batch = api(f"{path}{sep}per_page=100&page={page}")
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def normalize_url(url):
    """Same post, written differently, normalizes to the same string."""
    u = urllib.parse.urlsplit(url.strip().rstrip(").,"))
    host = u.netloc.lower().removeprefix("www.").removeprefix("m.").removeprefix("mobile.")
    host = {"twitter.com": "x.com", "fb.com": "facebook.com", "threads.com": "threads.net"}.get(host, host)
    query = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(u.query) if not TRACKING.match(k)])
    return f"{host}{u.path.rstrip('/').lower()}" + (f"?{query}" if query else "")


def domain_ok(url):
    host = urllib.parse.urlsplit(url).netloc.lower().split(":")[0]
    return any(host == d or host.endswith("." + d) for d in SOCIAL_DOMAINS)


def tip_text(line):
    text = re.sub(r"\(@?[^()]*\)\s*$", "", line)          # drop the author credit
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).split()


def added_lines(files, name):
    f = next((f for f in files if f["filename"] == name), None)
    if not f or not f.get("patch"):
        return []
    return [l[1:].strip() for l in f["patch"].splitlines() if l.startswith("+") and not l.startswith("+++")
            and l[1:].strip().startswith("- ")]


def existing_lines(name):
    if not os.path.exists(name):
        return []
    return [l.strip() for l in open(name, encoding="utf-8") if l.strip().startswith("- ")]


def check(pr, files, open_prs):
    problems, notes = [], []
    author = pr["user"]["login"]

    if pr["author_association"] not in TRUSTED:
        mine = sorted((p for p in open_prs if p["user"]["login"] == author), key=lambda p: p["number"])
        if len(mine) > MAX_OPEN_PRS and pr["number"] not in [p["number"] for p in mine[:MAX_OPEN_PRS]]:
            return "close", [f"You already have {MAX_OPEN_PRS} open pull requests. To keep reviews fair for everyone, "
                             "this one has been closed automatically. Please reopen it, or open it again, once some of "
                             "your other pull requests have been reviewed."]

    posts = added_lines(files, POSTS_FILE)
    if posts:
        if len(posts) > 1:
            problems.append(f"Please add **one post per pull request**. This pull request adds {len(posts)} posts.")
        known = {normalize_url(u) for l in existing_lines(POSTS_FILE) for u in re.findall(r"\((https?://[^)\s]+)\)", l)}
        for line in posts:
            urls = re.findall(r"\((https?://[^)\s]+)\)", line)
            if not urls:
                problems.append(f"No link found in `{line[:80]}`. Use the format "
                                "`- [Short description](https://link-to-your-post) (@your-github-username)`.")
                continue
            url = urls[0]
            if not domain_ok(url):
                problems.append(f"`{url}` is not a social media post. Share a link to your public post on LinkedIn, X, "
                                "Instagram, Facebook, TikTok, Threads, YouTube, Medium, Substack or Bluesky.")
            if normalize_url(url) in known:
                problems.append(f"This post has already been submitted: `{url}`. Each post can only be counted once.")
            known.add(normalize_url(url))
            if f"@{author.lower()}" not in line.lower():
                problems.append(f"The line should end with your own username, `(@{author})`. "
                                "Only share posts that you wrote and published yourself.")

    tips = added_lines(files, TIPS_FILE)
    existing = existing_lines(TIPS_FILE)
    for line in tips:
        words = tip_text(line)
        best = max(((difflib.SequenceMatcher(None, words, tip_text(e)).ratio(), e) for e in existing), default=(0, ""))
        if best[0] >= SIMILAR:
            problems.append(f"This tip looks like a duplicate of an existing one:\n  > {best[1]}\n\n"
                            "Please share a different tip, or explain in a comment how yours adds something new.")
        existing.append(line)
    return ("fail" if problems else "pass"), problems


def comment(pr_number, body, update_only=False):
    if DRY_RUN:
        print(f"--- DRY RUN comment on #{pr_number} ---\n{body}\n---")
        return
    mine = [c for c in paginate(f"/repos/{REPO}/issues/{pr_number}/comments")
            if MARKER in (c.get("body") or "") and c["user"]["type"] == "Bot"]
    if mine:
        api(f"/repos/{REPO}/issues/comments/{mine[0]['id']}", "PATCH", {"body": body})
    elif not update_only:
        api(f"/repos/{REPO}/issues/{pr_number}/comments", "POST", {"body": body})


def main():
    pr = api(f"/repos/{REPO}/pulls/{PR_NUMBER}")
    if pr["state"] != "open" or pr["user"]["type"] == "Bot":
        return 0
    files = paginate(f"/repos/{REPO}/pulls/{PR_NUMBER}/files")
    open_prs = paginate(f"/repos/{REPO}/pulls?state=open")
    result, messages = check(pr, files, open_prs)
    print(result, messages)
    if result == "close":
        comment(PR_NUMBER, f"{MARKER}\n### Too many open pull requests\n\nHi @{pr['user']['login']}, {messages[0]}\n\n"
                           "Thank you for your enthusiasm.\n\nThe CyberSecTOBER team")
        if not DRY_RUN:
            api(f"/repos/{REPO}/pulls/{PR_NUMBER}", "PATCH", {"state": "closed"})
        return 0
    if result == "fail":
        items = "\n".join(f"- {m}" for m in messages)
        comment(PR_NUMBER, f"{MARKER}\n### A few things to fix\n\nHi @{pr['user']['login']}, thank you for your pull request. "
                           f"Our automatic checks found the following:\n\n{items}\n\nEdit your file to fix these and "
                           "the checks will run again automatically. A mentor will review your pull request once they pass.\n\n"
                           "The CyberSecTOBER team")
        if not DRY_RUN:
            api(f"/repos/{REPO}/issues/{PR_NUMBER}/labels", "POST", {"labels": ["needs-changes"]})
        return 1
    comment(PR_NUMBER, f"{MARKER}\n### Checks passed\n\nThank you. All automatic checks have passed and a mentor will review "
                       "your pull request soon.\n\nThe CyberSecTOBER team", update_only=True)
    if not DRY_RUN:
        try:
            api(f"/repos/{REPO}/issues/{PR_NUMBER}/labels/needs-changes", "DELETE")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
