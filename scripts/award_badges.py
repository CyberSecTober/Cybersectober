#!/usr/bin/env python3
"""Award CyberSecTOBER points and badges from merged pull requests.

Recomputes everything from merged PRs on every run, optionally comments on one
PR, and writes the leaderboard and verification site to OUT_DIR.
"""
import html
import json
import os
import shutil
import urllib.parse
import urllib.request
from datetime import datetime, timezone

REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ.get("GITHUB_TOKEN", "")
PR_NUMBER = os.environ.get("PR_NUMBER", "").strip()
OUT_DIR = os.environ.get("OUT_DIR", "_site")
DRY_RUN = os.environ.get("DRY_RUN") == "1"
OWNER, NAME = REPO.split("/")
SITE_URL = (os.environ.get("SITE_URL") or f"https://{OWNER.lower()}.github.io/{NAME}").rstrip("/") + "/"
REPO_URL = f"https://github.com/{REPO}"
RAW_BADGES = f"https://raw.githubusercontent.com/{REPO}/main/badges"
MARKER = "<!-- cybersectober-award -->"

BADGES = {
    "first-contribution": ("First Contribution", "Your first pull request was merged."),
    "security-contributor": ("Security Contributor", "Earned 25 contribution points."),
    "security-builder": ("Security Builder", "Earned 50 contribution points."),
    "security-champion": ("Security Champion", "Earned 75 contribution points."),
    "cyber-guardian": ("Cyber Guardian", "Earned 100 contribution points. The highest tier."),
    "awareness-advocate": ("Awareness Advocate", "Shared a first security awareness post with #CyberSecTOBER."),
    "signal-booster": ("Signal Booster", "Shared 5 or more awareness posts during October."),
    "awareness-ambassador": ("Awareness Ambassador", "Posted at least once every week of October."),
    "community-defender": ("Community Defender", "Created a community or local-language security resource."),
    "ai-security-pioneer": ("AI Security Pioneer", "Contributed to the AI Security track."),
    "api-defender": ("API Defender", "Contributed to the Web & API Security track."),
    "lab-builder": ("Lab Builder", "Built a practical, deliberately vulnerable security lab."),
    "open-source-mentor": ("Open Source Mentor", "Mentored or reviewed work for other contributors."),
    "cybersectober-champion": ("CyberSecTOBER Champion", "Top contributor at the close of CyberSecTOBER 2026."),
}
TIERS = [(25, "security-contributor"), (50, "security-builder"), (75, "security-champion"), (100, "cyber-guardian")]
TRACK_BADGES = {"community": "community-defender", "ai-security": "ai-security-pioneer", "api-security": "api-defender"}


def api(path, method="GET", body=None):
    req = urllib.request.Request(
        path if path.startswith("http") else f"https://api.github.com{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
    )
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


def merged_prs():
    prs = [p for p in paginate(f"/repos/{REPO}/pulls?state=closed&base=main")
           if p["merged_at"] and p["user"]["type"] != "Bot"]
    return sorted(prs, key=lambda p: p["merged_at"])


def points_for(pr):
    labels = {l["name"] for l in pr["labels"]}
    pts = max((int(l.split("-")[1]) for l in labels if l.startswith("points-") and l.split("-")[1].isdigit()), default=0)
    if not pts:
        files = {f["filename"] for f in paginate(f"/repos/{REPO}/pulls/{pr['number']}/files")}
        if files == {"awareness/tips.md"}:
            pts = 3
    if pts and "quality-bonus" in labels:
        pts += 5
    return pts, labels


def compute(prs, manual):
    users = {}
    for pr in prs:
        login = pr["user"]["login"]
        pts, labels = points_for(pr)
        u = users.setdefault(login, {"login": login, "points": 0, "prs": [], "badges": {}})
        before = u["points"]
        u["points"] += pts
        u["prs"].append({"number": pr["number"], "title": pr["title"], "url": pr["html_url"],
                         "merged_at": pr["merged_at"], "points": pts})

        def earn(slug):
            u["badges"].setdefault(slug, {"date": pr["merged_at"], "pr": pr["number"]})

        earn("first-contribution")
        for threshold, slug in TIERS:
            if before < threshold <= u["points"]:
                earn(slug)
        if pts:
            for track, slug in TRACK_BADGES.items():
                if track in labels:
                    earn(slug)
            if "points-15" in labels:
                earn("lab-builder")
    for login, slugs in manual.items():
        u = users.setdefault(login, {"login": login, "points": 0, "prs": [], "badges": {}})
        for slug in slugs:
            if slug in BADGES:
                u["badges"].setdefault(slug, {"date": None, "pr": None})
    ranked = sorted(users.values(), key=lambda u: (-u["points"], min((p["merged_at"] for p in u["prs"]), default="9")))
    for i, u in enumerate(ranked, 1):
        u["rank"] = i
    return ranked


def verify_url(login):
    return f"{SITE_URL}u/{login.lower()}/"


def linkedin_url(login, slug, date):
    d = datetime.fromisoformat(date.replace("Z", "+00:00")) if date else datetime(2026, 10, 1, tzinfo=timezone.utc)
    q = {"startTask": "CERTIFICATION_NAME", "name": f"CyberSecTOBER 2026: {BADGES[slug][0]}",
         "organizationName": "CyberSecTOBER", "issueYear": d.year, "issueMonth": d.month,
         "certUrl": verify_url(login), "certId": f"{login}-{slug}"}
    return "https://www.linkedin.com/profile/add?" + urllib.parse.urlencode(q)


def x_url(login, slug):
    text = f"I just earned the {BADGES[slug][0]} badge in #CyberSecTOBER 2026, an open-source cybersecurity challenge 🔐"
    return "https://x.com/intent/tweet?" + urllib.parse.urlencode({"text": text, "url": verify_url(login)})


def next_tier(points):
    for threshold, slug in TIERS:
        if points < threshold:
            return threshold - points, BADGES[slug][0]
    return None


def comment_body(u, pr_number):
    pr = next(p for p in u["prs"] if p["number"] == pr_number)
    new = [s for s, b in u["badges"].items() if b["pr"] == pr_number]
    login = u["login"]
    lines = [MARKER, f"## 🎉 Congratulations @{login}, your contribution is merged!", "",
             f"**+{pr['points']} points** for this pull request · **{u['points']} points** in total · **Rank #{u['rank']}** on the leaderboard", ""]
    if not pr["points"]:
        lines += ["> ⚠️ **Maintainers:** this pull request has no `points-*` label, so no points were awarded yet. "
                  "Add the right label and this comment will update automatically.", ""]
    if new:
        lines += ["### 🏅 New badge" + ("s" if len(new) > 1 else ""), ""]
        for s in new:
            lines += [f'<img src="{RAW_BADGES}/{s}.png" width="110" alt="{BADGES[s][0]} badge">', "",
                      f"**{BADGES[s][0]}**: {BADGES[s][1]}  ",
                      f"[➕ Add to LinkedIn]({linkedin_url(login, s, u['badges'][s]['date'])}) · [📣 Post on X]({x_url(login, s)})", ""]
    else:
        lines += ["No new badge this time, but every point counts.", ""]
    nt = next_tier(u["points"])
    if nt:
        lines += [f"🎯 You're **{nt[0]} points** away from **{nt[1]}**.", ""]
    lines += ["### ✅ Your verification page", "",
              f"Anyone can check your badges and contributions here: **{verify_url(login)}**", "",
              "Use that link as the **Credential URL** on LinkedIn. To show your badge on your GitHub profile, see "
              f"[Show off your badge]({REPO_URL}#-show-off-your-badge).", "",
              "Thank you for helping make the internet safer. 🔐"]
    return "\n".join(lines)


def post_comment(pr_number, body):
    if DRY_RUN:
        print(f"--- DRY RUN: comment for PR #{pr_number} ---\n{body}\n---")
        return
    existing = [c for c in paginate(f"/repos/{REPO}/issues/{pr_number}/comments")
                if MARKER in (c.get("body") or "") and c["user"]["type"] == "Bot"]
    if existing:
        api(f"/repos/{REPO}/issues/comments/{existing[0]['id']}", "PATCH", {"body": body})
    else:
        api(f"/repos/{REPO}/issues/{pr_number}/comments", "POST", {"body": body})


def fmt_date(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%-d %B %Y") if iso else "Awarded by a maintainer"


def page(title, body, depth):
    root = "../" * depth
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500&family=Space+Grotesk:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0B0F16;--panel:#141C28;--line:#243042;--text:#F2F4F7;--muted:#9AA4B2;--accent:#3DDC97}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 "Space Grotesk",system-ui,sans-serif}}
a{{color:var(--accent)}}main{{max-width:880px;margin:0 auto;padding:32px 16px 64px}}
.eyebrow{{font:500 13px "IBM Plex Mono",monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}}
h1{{font-size:clamp(28px,5vw,40px);margin:8px 0 4px}}h2{{margin:36px 0 12px;font-size:22px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px}}
.who{{display:flex;gap:16px;align-items:center}}.who img{{width:72px;height:72px;border-radius:50%}}
.verified{{display:inline-block;margin-top:6px;padding:3px 10px;border-radius:99px;border:1px solid var(--accent);color:var(--accent);font:500 12px "IBM Plex Mono",monospace}}
.stats{{display:flex;gap:28px;flex-wrap:wrap;margin-top:16px}}.stats b{{display:block;font-size:28px}}.stats span{{color:var(--muted);font-size:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}}
.badge{{text-align:center}}.badge img{{width:120px;height:120px}}.badge h3{{margin:6px 0 2px;font-size:17px}}.badge p{{margin:0;color:var(--muted);font-size:14px}}
.badge .links{{margin-top:10px;font-size:14px}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line)}}th{{color:var(--muted);font-weight:400;font-size:14px}}
td img{{width:28px;height:28px;border-radius:50%;vertical-align:middle;margin-right:8px}}.num{{text-align:right}}
.muted{{color:var(--muted)}}footer{{margin-top:48px;color:var(--muted);font-size:14px}}
</style></head><body><main>
<div class="eyebrow"><a href="{root}" style="color:inherit;text-decoration:none">CyberSecTOBER 2026</a></div>
{body}
<footer>Badges are awarded automatically from merged pull requests in <a href="{REPO_URL}">{html.escape(REPO)}</a>. Points and badges on this site are the official record.</footer>
</main></body></html>"""


def badge_tile(u, slug, root):
    b = u["badges"][slug]
    source = f'<a href="{REPO_URL}/pull/{b["pr"]}">PR #{b["pr"]}</a>' if b["pr"] else "Maintainer award"
    return (f'<div class="panel badge"><img src="{root}badges/{slug}.png" alt="{html.escape(BADGES[slug][0])} badge">'
            f'<h3>{html.escape(BADGES[slug][0])}</h3><p>{html.escape(BADGES[slug][1])}</p>'
            f'<p>{fmt_date(b["date"])} · {source}</p>'
            f'<div class="links"><a href="{html.escape(linkedin_url(u["login"], slug, b["date"]))}">Add to LinkedIn</a> · '
            f'<a href="{html.escape(x_url(u["login"], slug))}">Post on X</a></div></div>')


def build_site(ranked):
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    os.makedirs(OUT_DIR)
    shutil.copytree("badges", os.path.join(OUT_DIR, "badges"), ignore=shutil.ignore_patterns("*.md", "svg"))
    open(os.path.join(OUT_DIR, ".nojekyll"), "w").close()

    rows = "".join(
        f'<tr><td>{u["rank"]}</td><td><a href="u/{u["login"].lower()}/"><img src="https://github.com/{u["login"]}.png?size=56" alt="">{html.escape(u["login"])}</a></td>'
        f'<td class="num">{len(u["badges"])}</td><td class="num"><b>{u["points"]}</b></td></tr>' for u in ranked)
    board = (f'<table><tr><th>#</th><th>Contributor</th><th class="num">Badges</th><th class="num">Points</th></tr>{rows}</table>'
             if ranked else '<p class="muted">No merged contributions yet. Be the first!</p>')
    index = (f'<h1>Leaderboard</h1><p class="muted">Every merged contribution to CyberSecTOBER 2026, verified. '
             f'<a href="{REPO_URL}#-your-first-contribution-in-5-minutes-no-installs">Make your first contribution →</a></p>'
             f'<div class="panel">{board}</div>')
    open(os.path.join(OUT_DIR, "index.html"), "w").write(page("CyberSecTOBER 2026 Leaderboard", index, 0))

    for u in ranked:
        login = u["login"]
        d = os.path.join(OUT_DIR, "u", login.lower())
        os.makedirs(d, exist_ok=True)
        tiles = "".join(badge_tile(u, s, "../../") for s in BADGES if s in u["badges"])
        prs = "".join(f'<tr><td><a href="{p["url"]}">#{p["number"]}</a> {html.escape(p["title"])}</td>'
                      f'<td>{fmt_date(p["merged_at"])}</td><td class="num">{p["points"]}</td></tr>' for p in reversed(u["prs"]))
        body = (f'<div class="panel who"><img src="https://github.com/{login}.png?size=144" alt="">'
                f'<div><h1>{html.escape(login)}</h1><a href="https://github.com/{login}">github.com/{html.escape(login)}</a><br>'
                f'<span class="verified">✓ VERIFIED BY CYBERSECTOBER</span></div></div>'
                f'<div class="stats"><div><b>{u["points"]}</b><span>points</span></div><div><b>{len(u["badges"])}</b><span>badges</span></div>'
                f'<div><b>#{u["rank"]}</b><span>leaderboard rank</span></div><div><b>{len(u["prs"])}</b><span>merged contributions</span></div></div>'
                f'<h2>Badges</h2><div class="grid">{tiles}</div>'
                f'<h2>Contributions</h2><div class="panel">'
                + (f'<table><tr><th>Pull request</th><th>Merged</th><th class="num">Points</th></tr>{prs}</table>' if prs
                   else '<p class="muted">Badges awarded by maintainers.</p>') + '</div>')
        open(os.path.join(d, "index.html"), "w").write(page(f"{login}: CyberSecTOBER 2026 badges", body, 2))


def main():
    manual = json.load(open("data/manual-awards.json")) if os.path.exists("data/manual-awards.json") else {}
    ranked = compute(merged_prs(), manual)
    build_site(ranked)
    print(f"Built site for {len(ranked)} contributor(s) at {OUT_DIR}/")
    if PR_NUMBER:
        n = int(PR_NUMBER)
        u = next((u for u in ranked if any(p["number"] == n for p in u["prs"])), None)
        if u:
            post_comment(n, comment_body(u, n))
        else:
            print(f"PR #{n} is not a merged pull request into main; no comment posted.")


if __name__ == "__main__":
    main()
