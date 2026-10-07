#!/usr/bin/env python3
"""Checks every incoming pull request for floods, duplicate posts and tips, and common format mistakes in new files
(template text left in, missing or unfilled front matter, broken headings, files outside the challenge's folder).

Runs from the main branch and only reads the pull request through the API; it never
executes contributor code. Exits non-zero when it finds a problem so the PR shows a red check.
"""
import base64
import difflib
import glob
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
TRACKS = ("awareness", "api-security", "ai-security", "community")
LIST_FILES = {POSTS_FILE, TIPS_FILE, "awareness/glossary.md"}
CHALLENGE_REF = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|part of)\s+#(\d+)", re.I)
BAD_HEADING = re.compile(r"^#{2,6}[^#\s]")


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


def template_lines():
    """Placeholder sentences from the templates, so a file that still contains them can be spotted."""
    lines = set()
    for path in glob.glob("templates/*.md"):
        if path.endswith("README.md"):
            continue
        fence = False
        for i, l in enumerate(open(path, encoding="utf-8").read().split("\n---", 1)[-1].splitlines()):
            t = l.strip()
            if t.startswith("```"):
                fence = not fence
                continue
            if fence or len(t) < 8 or t.startswith(("#", ">", "<!--", "---")) or "SOLUTION.md" in t or "LICENSE" in t:
                continue
            lines.add(t)
    return lines


def front_matter(text):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fields = {}
    for l in text[3:end].splitlines():
        if ":" in l:
            k, v = l.split(":", 1)
            fields[k.strip()] = v.strip()
    return fields


def file_text(path, sha):
    try:
        f = api(f"/repos/{REPO}/contents/{urllib.parse.quote(path)}?ref={sha}")
        if f.get("size", 0) > 300_000:
            return None
        return base64.b64decode(f["content"]).decode("utf-8", "replace")
    except Exception:
        return None


def challenge_target(spec):
    """Turn a "Done when" path such as `<track>/resources/your-github-username-topic.md` into a check.
    Returns (kind, value): ("exact", path) for a fixed file or folder, ("prefix", regex) for a pattern."""
    segs = spec.strip("/").split("/")
    if not any("<" in s or s.startswith("your-") or "your-github-username" in s or "yyyy" in s for s in segs):
        return "exact", spec
    parts = []
    for s in segs:
        if s.startswith("<") and s.endswith(">"):
            parts.append("(" + "|".join(TRACKS) + ")" if s == "<track>" else "[^/]+")
        elif s.startswith("your-") or "your-github-username" in s or "<" in s or "." in s:
            break
        else:
            parts.append(re.escape(s))
    return "prefix", "^" + "/".join(parts) + "/"


def linked_challenges(pr):
    """Challenges the pull request says it completes, read from trusted challenge issues only."""
    out = []
    for n in sorted(set(int(x) for x in CHALLENGE_REF.findall(pr.get("body") or ""))):
        try:
            issue = api(f"/repos/{REPO}/issues/{n}")
        except Exception:
            continue
        if issue.get("pull_request") or not (issue["user"]["type"] == "Bot" or issue["author_association"] in TRUSTED):
            continue
        m = re.search(r"### Done when\s+(.*?)(?:\n### |\Z)", issue.get("body") or "", re.S)
        if not m:
            continue
        done = m.group(1)
        spec = next((t for t in re.findall(r"`([^`\s]+)`", done)
                     if "/" in t and not t.startswith(("templates/", "http"))), None)
        if spec:
            out.append((n, spec, bool(re.search(r"front matter|yaml header|template", done, re.I))))
    return out


def content_problems(pr, files):
    """Format mistakes in new or edited Markdown files in the track folders."""
    problems = []
    sha = pr["head"]["sha"]
    changed = [f for f in files if f["status"] in ("added", "modified", "renamed")]
    docs = [f["filename"] for f in changed if f["filename"].endswith(".md") and f["filename"].split("/")[0] in TRACKS
            and f["filename"] not in LIST_FILES]
    texts = {p: t for p in docs for t in [file_text(p, sha)] if t is not None}
    placeholders = template_lines()

    for path, text in texts.items():
        name = f"`{path}`"
        body_lines = [l.strip() for l in text.splitlines()]
        left = [l for l in body_lines if l in placeholders]
        if len(left) >= 2 or "- [Link](https://example.com)" in left:
            problems.append(f"{name} still contains the template's example text, for example \"{left[0]}\". "
                            "Replace it with your own content before the pull request can be reviewed.")
        fm = front_matter(text)
        if fm is not None:
            unfilled = [k for k, v in fm.items() if " | " in v or v.startswith("(") or "yyyy" in v or v == "link-to-english-version"
                        or (not v and k in ("title", "author", "track", "difficulty", "description", "language"))]
            if unfilled:
                problems.append(f"The front matter in {name} is not filled in: "
                                + ", ".join(f"`{k}`" for k in unfilled) + ". Give each one a single value, for "
                                "example `difficulty: beginner`.")
        fence, bad = False, []
        for l in text.splitlines():
            if l.strip().startswith("```"):
                fence = not fence
            elif not fence and BAD_HEADING.match(l):
                bad.append(l.strip())
        if bad:
            problems.append(f"Some headings in {name} are missing a space after the `#`, so GitHub shows them as "
                            f"plain text: `{bad[0][:60]}`. Write `## Heading`, not `##Heading`.")
        elif not path.endswith("README.md") and sum(1 for l in body_lines if l) >= 30 \
                and not any(re.match(r"#{1,6}\s", l) for l in text.splitlines()):
            problems.append(f"{name} has no Markdown headings. Use `#` and `##` for the title and sections (and `-` "
                            "for lists) so it reads well on GitHub. The Preview tab shows how it will look.")

    for n, spec, needs_fm in linked_challenges(pr):
        kind, value = challenge_target(spec)
        names = [f["filename"] for f in changed]
        if kind == "exact":
            hits = [p for p in names if (p.startswith(value) if value.endswith("/") else p == value)]
        else:
            hits = [p for p in names if re.match(value, p)]
        if not hits:
            hint = " (`<track>` is the track folder, for example `awareness`)" if "<track>" in spec else ""
            problems.append(f"Challenge #{n} asks for your work at `{spec}`{hint}. Please move your file there. "
                            "On GitHub, edit the file and change its name, including the folders in front of it.")
            continue
        if needs_fm:
            main_docs = [p for p in hits if p.endswith(".md") and (p.endswith("README.md") or not spec.endswith("/"))]
            for p in main_docs:
                if p in texts and front_matter(texts[p]) is None:
                    problems.append(f"`{p}` needs front matter at the very top, as challenge #{n} asks. Copy the block "
                                    "between the `---` lines from the template in `templates/` and fill it in.")
    return problems


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
    problems += content_problems(pr, files)
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
