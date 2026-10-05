#!/usr/bin/env python3
"""Award CyberSecTOBER points and badges from merged pull requests.

Recomputes everything from merged PRs on every run, optionally comments on one
PR, and writes the leaderboard and verification site to OUT_DIR.
"""
import html
import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

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
NOW = datetime.fromisoformat(os.environ["NOW"]) if os.environ.get("NOW") else datetime.now(timezone.utc)

WEEKS = [  # (first day, last day, theme); launch week also covers anything merged before 5 October
    (None, date(2026, 10, 10), "Launch week: make your first contribution"),
    (date(2026, 10, 11), date(2026, 10, 17), "Secure What You Build"),
    (date(2026, 10, 18), date(2026, 10, 24), "Secure the Future"),
    (date(2026, 10, 25), date(2026, 10, 31), "Secure Our Communities"),
]

# ISO code -> (country name, words that identify it in a free-text GitHub location)
COUNTRIES = {
    "NG": ("Nigeria", "nigeria naija lagos abuja ibadan kano enugu ilorin abeokuta owerri uyo kaduna jos akure osogbo calabar warri onitsha asaba;port harcourt;benin city"),
    "GH": ("Ghana", "ghana accra kumasi tamale takoradi;cape coast"),
    "KE": ("Kenya", "kenya nairobi mombasa kisumu nakuru eldoret"),
    "ZA": ("South Africa", "johannesburg pretoria durban;south africa;cape town"),
    "UG": ("Uganda", "uganda kampala entebbe"),
    "TZ": ("Tanzania", "tanzania dodoma arusha zanzibar;dar es salaam"),
    "RW": ("Rwanda", "rwanda kigali"),
    "ET": ("Ethiopia", "ethiopia;addis ababa"),
    "EG": ("Egypt", "egypt cairo alexandria"),
    "CM": ("Cameroon", "cameroon douala yaounde yaoundé"),
    "SN": ("Senegal", "senegal sénégal dakar"),
    "CI": ("Côte d'Ivoire", "abidjan;ivory coast;côte d'ivoire;cote d'ivoire"),
    "MA": ("Morocco", "morocco casablanca rabat marrakech"),
    "ZM": ("Zambia", "zambia lusaka"),
    "ZW": ("Zimbabwe", "zimbabwe harare bulawayo"),
    "SL": ("Sierra Leone", "freetown;sierra leone"),
    "LR": ("Liberia", "liberia monrovia"),
    "GM": ("The Gambia", "gambia banjul"),
    "BJ": ("Benin", "cotonou;porto-novo;republic of benin"),
    "TG": ("Togo", "togo lomé lome"),
    "GB": ("United Kingdom", "uk england scotland wales london manchester birmingham leeds glasgow edinburgh;united kingdom"),
    "US": ("United States", "usa california texas seattle boston chicago;united states;new york;san francisco"),
    "CA": ("Canada", "canada toronto vancouver montreal calgary ottawa"),
    "IN": ("India", "india bangalore bengaluru mumbai delhi hyderabad chennai pune"),
    "DE": ("Germany", "germany deutschland berlin munich hamburg"),
    "NL": ("Netherlands", "netherlands amsterdam rotterdam"),
    "FR": ("France", "france paris"),
    "IE": ("Ireland", "ireland dublin"),
    "AE": ("United Arab Emirates", "uae dubai;abu dhabi;united arab emirates"),
}
def _terms(spec):
    """'word word;multi word phrase;another phrase' -> list of terms."""
    words, *phrases = spec.split(";")
    return words.split() + phrases


COUNTRY_PATTERNS = [(code, re.compile(r"(?<![\w])(" + "|".join(re.escape(t) for t in _terms(spec)) + r")(?![\w])"))
                    for code, (_, spec) in COUNTRIES.items()]

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


CONTENT_DIRS = ("awareness/", "api-security/", "ai-security/", "community/")


POSTS_FILE = "awareness/posts.md"
POST_MILESTONES = [(1, "awareness-advocate"), (5, "signal-booster")]


def points_for(pr):
    """Return (points, labels, counts, is_post). Unlabelled PRs that touch no content folder are maintenance and
    don't count; unlabelled PRs that only add to the posts file are awareness posts (badges, no points)."""
    labels = {l["name"] for l in pr["labels"]}
    pts = max((int(l.split("-")[1]) for l in labels if l.startswith("points-") and l.split("-")[1].isdigit()), default=0)
    counts, is_post = True, False
    if not pts:
        files = {f["filename"] for f in paginate(f"/repos/{REPO}/pulls/{pr['number']}/files")}
        if files == {"awareness/tips.md"}:
            pts = 3
        is_post = files == {POSTS_FILE}
        counts = any(f.startswith(CONTENT_DIRS) for f in files)
    if pts and "quality-bonus" in labels:
        pts += 5
    return pts, labels, counts, is_post


def compute(prs, manual):
    users = {}
    for pr in prs:
        login = pr["user"]["login"]
        pts, labels, counts, is_post = points_for(pr)
        if not counts:
            continue
        u = users.setdefault(login, {"login": login, "points": 0, "prs": [], "badges": {}, "posts": 0, "post_weeks": set()})
        before = u["points"]
        u["points"] += pts
        u["prs"].append({"number": pr["number"], "title": pr["title"], "url": pr["html_url"],
                         "merged_at": pr["merged_at"], "points": pts, "post": is_post})

        def earn(slug):
            u["badges"].setdefault(slug, {"date": pr["merged_at"], "pr": pr["number"]})

        earn("first-contribution")
        if is_post:
            u["posts"] += 1
            u["post_weeks"] |= {i for i, (start, end, _) in enumerate(WEEKS) if in_week(pr["merged_at"], start, end)}
            for needed, slug in POST_MILESTONES:
                if u["posts"] >= needed:
                    earn(slug)
            if len(u["post_weeks"]) == len(WEEKS):
                earn("awareness-ambassador")
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
        u = users.setdefault(login, {"login": login, "points": 0, "prs": [], "badges": {}, "posts": 0, "post_weeks": set()})
        for slug in slugs:
            if slug in BADGES:
                u["badges"].setdefault(slug, {"date": None, "pr": None})
    ranked = sorted(users.values(), key=lambda u: (-u["points"], min((p["merged_at"] for p in u["prs"]), default="9")))
    for i, u in enumerate(ranked, 1):
        u["rank"] = i
    return ranked


def flag(code):
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code)


def country_from_location(location):
    """Best-effort country from a free-text GitHub profile location. Returns (code, name) or None."""
    if not location:
        return None
    pair = re.search("[\U0001F1E6-\U0001F1FF]{2}", location)
    if pair:
        code = "".join(chr(ord(c) - 0x1F1E6 + 65) for c in pair.group())
        return code, COUNTRIES.get(code, (code,))[0]
    text = location.lower()
    for code, pattern in COUNTRY_PATTERNS:
        if pattern.search(text):
            return code, COUNTRIES[code][0]
    return None


def add_countries(ranked):
    for u in ranked:
        try:
            u["country"] = country_from_location((api(f"/users/{u['login']}") or {}).get("location"))
        except Exception:
            u["country"] = None


def current_week():
    today = NOW.date()
    for i, (start, end, theme) in enumerate(WEEKS):
        if today <= end:
            return i, start, end, theme
    return len(WEEKS) - 1, *WEEKS[-1]


def in_week(iso, start, end):
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
    return (start is None or d >= start) and d <= end


def translated_languages():
    base = "community/translations"
    if not os.path.isdir(base):
        return 0
    return sum(1 for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))
               and any(f != "README.md" for _, _, fs in os.walk(os.path.join(base, d)) for f in fs))


def verify_url(login):
    return f"{SITE_URL}u/{login.lower()}/"


def linkedin_url(login, slug, date):
    d = datetime.fromisoformat(date.replace("Z", "+00:00")) if date else datetime(2026, 10, 1, tzinfo=timezone.utc)
    q = {"startTask": "CERTIFICATION_NAME", "name": f"CyberSecTOBER 2026: {BADGES[slug][0]}",
         "organizationName": "CyberSecTOBER", "issueYear": d.year, "issueMonth": d.month,
         "certUrl": verify_url(login), "certId": f"{login}-{slug}"}
    return "https://www.linkedin.com/profile/add?" + urllib.parse.urlencode(q)


def x_url(login, slug):
    text = f"I earned the {BADGES[slug][0]} badge in #CyberSecTOBER 2026, an open-source cybersecurity challenge."
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
    if pr["post"]:
        lines = [MARKER, "### Awareness post recorded", "",
                 f"Hi @{login}, thank you for sharing cybersecurity awareness with #CyberSecTOBER. "
                 "Your post has been added to your record.", "",
                 f"- Awareness posts recorded: **{u['posts']}**",
                 f"- Weeks with a post: **{len(u['post_weeks'])} of {len(WEEKS)}**", ""]
    else:
        lines = [MARKER, "### Contribution recorded", "",
                 f"Hi @{login}, thank you for contributing to CyberSecTOBER 2026. "
                 "Your pull request has been merged and added to your record.", "",
                 f"- Points for this contribution: **{pr['points']}**",
                 f"- Total points: **{u['points']}**",
                 f"- Leaderboard rank: **{u['rank']}**", ""]
    if not pr["points"] and not pr["post"]:
        lines += ["> **Note for maintainers:** this pull request has no `points-*` label, so no points have been "
                  "awarded yet. Add the appropriate label and this comment will update automatically.", ""]
    for s in new:
        lines += [f"**Badge earned: {BADGES[s][0]}**", "",
                  f'<img src="{RAW_BADGES}/{s}.png" width="96" alt="{BADGES[s][0]} badge">', "",
                  f"{BADGES[s][1]}  ",
                  f"[Add to LinkedIn]({linkedin_url(login, s, u['badges'][s]['date'])}) · [Share on X]({x_url(login, s)})", ""]
    if pr["post"]:
        if u["posts"] < 5:
            lines += [f"**Next milestone:** {5 - u['posts']} more posts to reach Signal Booster.", ""]
        elif "awareness-ambassador" not in u["badges"]:
            lines += ["**Next milestone:** share a post in every week of October to earn Awareness Ambassador.", ""]
    else:
        nt = next_tier(u["points"])
        if nt:
            lines += [f"**Next milestone:** {nt[0]} more points to reach {nt[1]}.", ""]
    lines += [f"**Verification:** your badges and contributions can be verified publicly at {verify_url(login)}. "
              "Use this link as the Credential URL when adding a badge to LinkedIn. To display your badges on your GitHub "
              "profile, copy the ready-made snippet from your verification page.", "",
              f"If you haven't already, please star the [repository]({REPO_URL}) using the Star button at the top right "
              "of the page. It helps more people find CyberSecTOBER.", "",
              "Thank you for helping make the internet safer.", "",
              "The CyberSecTOBER team"]
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
.statbar{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0 8px}}
.statbar .panel{{padding:14px 16px}}.statbar b{{display:block;font-size:30px}}.statbar span{{color:var(--muted);font-size:14px}}
.week{{font:500 12px "IBM Plex Mono",monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}}
.flag{{margin-left:6px}}.progress{{margin-top:20px}}.progress .track{{height:10px;background:var(--line);border-radius:99px;overflow:hidden;margin-top:8px}}
.progress .fill{{height:100%;background:var(--accent);border-radius:99px}}
pre{{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px;overflow-x:auto;white-space:pre;font:13px/1.5 "IBM Plex Mono",monospace;color:var(--text)}}
button{{background:var(--accent);color:#06281A;border:0;border-radius:8px;padding:9px 16px;font:600 15px "Space Grotesk",system-ui,sans-serif;cursor:pointer}}.table-wrap{{overflow-x:auto}}
</style></head><body><main>
<div class="eyebrow"><a href="{root}" style="color:inherit;text-decoration:none">CyberSecTOBER 2026</a></div>
{body}
<footer>Updated {NOW.strftime("%-d %B %Y, %H:%M")} UTC. Badges are awarded automatically from merged pull requests in <a href="{REPO_URL}">{html.escape(REPO)}</a>. Points and badges on this site are the official record.</footer>
</main></body></html>"""


def badge_tile(u, slug, root):
    b = u["badges"][slug]
    source = f'<a href="{REPO_URL}/pull/{b["pr"]}">PR #{b["pr"]}</a>' if b["pr"] else "Maintainer award"
    return (f'<div class="panel badge"><img src="{root}badges/{slug}.png" alt="{html.escape(BADGES[slug][0])} badge">'
            f'<h3>{html.escape(BADGES[slug][0])}</h3><p>{html.escape(BADGES[slug][1])}</p>'
            f'<p>{fmt_date(b["date"])} · {source}</p>'
            f'<div class="links"><a href="{html.escape(linkedin_url(u["login"], slug, b["date"]))}">Add to LinkedIn</a> · '
            f'<a href="{html.escape(x_url(u["login"], slug))}">Post on X</a></div></div>')


def who_cell(u, root=""):
    c = u.get("country")
    f = f'<span class="flag" title="{html.escape(c[1])}">{flag(c[0])}</span>' if c else ""
    return (f'<a href="{root}u/{u["login"].lower()}/"><img src="https://github.com/{u["login"]}.png?size=56" alt="">'
            f'{html.escape(u["login"])}</a>{f}')


def table(headers, rows, empty):
    if not rows:
        return f'<p class="muted">{empty}</p>'
    head = "".join(f'<th{" class=num" if h in ("Points", "Badges", "Contributors") else ""}>{h}</th>' for h in headers)
    return f'<div class="table-wrap"><table><tr>{head}</tr>{"".join(rows)}</table></div>'


def build_site(ranked):
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    os.makedirs(OUT_DIR)
    shutil.copytree("badges", os.path.join(OUT_DIR, "badges"), ignore=shutil.ignore_patterns("*.md", "svg"))
    open(os.path.join(OUT_DIR, ".nojekyll"), "w").close()

    contributions = sorted(((u, p) for u in ranked for p in u["prs"]), key=lambda x: x[1]["merged_at"], reverse=True)
    countries = {}
    for u in ranked:
        if u.get("country"):
            c = countries.setdefault(u["country"], {"points": 0, "people": 0})
            c["points"] += u["points"]
            c["people"] += 1
    stats = [(len(ranked), "contributors"), (len(contributions), "merged contributions"),
             (len(countries), "countries"), (translated_languages(), "languages translated")]
    statbar = "".join(f'<div class="panel"><b>{n}</b><span>{label}</span></div>' for n, label in stats)

    wi, wstart, wend, theme = current_week()
    weekly = sorted(((u, sum(p["points"] for p in u["prs"] if in_week(p["merged_at"], wstart, wend))) for u in ranked),
                    key=lambda x: -x[1])
    weekly = [(u, pts) for u, pts in weekly if pts][:10]
    span = f'{wstart.strftime("%-d")} – {wend.strftime("%-d %B")}' if wstart else f'Up to {wend.strftime("%-d %B")}'
    week_rows = [f'<tr><td>{i}</td><td>{who_cell(u)}</td><td class="num"><b>{pts}</b></td></tr>' for i, (u, pts) in enumerate(weekly, 1)]

    overall_rows = [f'<tr><td>{u["rank"]}</td><td>{who_cell(u)}</td><td class="num">{len(u["badges"])}</td>'
                    f'<td class="num"><b>{u["points"]}</b></td></tr>' for u in ranked]
    country_rows = [f'<tr><td>{i}</td><td>{flag(code)} {html.escape(name)}</td><td class="num">{c["people"]}</td><td class="num"><b>{c["points"]}</b></td></tr>'
                    for i, ((code, name), c) in enumerate(sorted(countries.items(), key=lambda x: (-x[1]["points"], -x[1]["people"])), 1)]
    latest_rows = [f'<tr><td>{who_cell(u)}</td><td><a href="{p["url"]}">#{p["number"]}</a> {html.escape(p["title"])}'
                   f'<br><span class="muted" style="font-size:14px">{fmt_date(p["merged_at"])}</span></td>'
                   f'<td class="num">{"Post" if p["post"] else "+" + str(p["points"])}</td></tr>' for u, p in contributions[:10]]

    index = (f'<h1>Leaderboard</h1><p class="muted">Every merged contribution to CyberSecTOBER 2026, verified. '
             f'<a href="{REPO_URL}#-your-first-contribution-in-5-minutes-no-installs">Make your first contribution →</a></p>'
             f'<div class="statbar">{statbar}</div>'
             f'<h2>This week</h2><div class="week">Week {wi + 1} · {html.escape(theme)} · {span}</div>'
             f'<div class="panel" style="margin-top:10px">{table(["#", "Contributor", "Points"], week_rows, "No merged contributions this week yet. Yours could be the first!")}</div>'
             f'<h2>Overall</h2><div class="panel">{table(["#", "Contributor", "Badges", "Points"], overall_rows, "No merged contributions yet. Be the first!")}</div>'
             f'<h2>Countries</h2><div class="panel">{table(["#", "Country", "Contributors", "Points"], country_rows, "No countries yet. Add your location to your GitHub profile to represent your country.")}'
             f'<p class="muted" style="margin:12px 0 0;font-size:14px">Based on the Location field of each contributor\'s GitHub profile.</p></div>'
             f'<h2>Latest contributions</h2><div class="panel">{table(["Contributor", "Contribution", "Points"], latest_rows, "Nothing merged yet.")}</div>')
    open(os.path.join(OUT_DIR, "index.html"), "w").write(page("CyberSecTOBER 2026 Leaderboard", index, 0))

    for u in ranked:
        login = u["login"]
        d = os.path.join(OUT_DIR, "u", login.lower())
        os.makedirs(d, exist_ok=True)
        tiles = "".join(badge_tile(u, s, "../../") for s in BADGES if s in u["badges"])
        earned = [s for s in BADGES if s in u["badges"]]
        for s in earned:
            shutil.copy(os.path.join("badges", f"{s}.png"), os.path.join(d, f"{s}.png"))
        snippet = "\n".join(f'<a href="{verify_url(login)}"><img src="{verify_url(login)}{s}.png" width="120" '
                             f'alt="CyberSecTOBER 2026 {BADGES[s][0]} badge, verified"></a>' for s in earned)
        embed = (f'<h2>Show your badges on GitHub</h2><div class="panel">'
                 f'<p style="margin-top:0">Paste this into your GitHub profile README. The images only exist for badges you have earned, '
                 f'and each one links back to this page as proof.</p>'
                 f'<pre id="snippet">{html.escape(snippet)}</pre>'
                 f'<button onclick="navigator.clipboard.writeText(document.getElementById(\'snippet\').innerText);this.textContent=\'Copied\'">Copy snippet</button>'
                 f'</div>') if earned else ""
        prs = [f'<tr><td><a href="{p["url"]}">#{p["number"]}</a> {html.escape(p["title"])}</td>'
               f'<td>{fmt_date(p["merged_at"])}</td><td class="num">{"Post" if p["post"] else p["points"]}</td></tr>' for p in reversed(u["prs"])]
        c = u.get("country")
        where = f'<br><span class="muted">{flag(c[0])} {html.escape(c[1])}</span>' if c else ""
        nt = next_tier(u["points"])
        if nt:
            target = u["points"] + nt[0]
            progress = (f'<div class="panel progress"><b>{u["points"]} / {target} points</b> to <b>{html.escape(nt[1])}</b>'
                        f'<div class="track"><div class="fill" style="width:{round(100 * u["points"] / target)}%"></div></div></div>')
        else:
            progress = '<div class="panel progress"><b>Highest tier reached: Cyber Guardian</b></div>'
        body = (f'<div class="panel who"><img src="https://github.com/{login}.png?size=144" alt="">'
                f'<div><h1>{html.escape(login)}</h1><a href="https://github.com/{login}">github.com/{html.escape(login)}</a>{where}<br>'
                f'<span class="verified">✓ VERIFIED BY CYBERSECTOBER</span></div></div>'
                f'<div class="stats"><div><b>{u["points"]}</b><span>points</span></div><div><b>{len(u["badges"])}</b><span>badges</span></div>'
                f'<div><b>#{u["rank"]}</b><span>leaderboard rank</span></div><div><b>{len(u["prs"])}</b><span>merged contributions</span></div></div>'
                f'{progress}'
                f'<h2>Badges</h2><div class="grid">{tiles}</div>'
                f'{embed}'
                f'<h2>Contributions</h2><div class="panel">'
                + table(["Pull request", "Merged", "Points"], prs, "Badges awarded by maintainers.") + '</div>')
        open(os.path.join(d, "index.html"), "w").write(page(f"{login}: CyberSecTOBER 2026 badges", body, 2))


def main():
    manual = json.load(open("data/manual-awards.json")) if os.path.exists("data/manual-awards.json") else {}
    ranked = compute(merged_prs(), manual)
    add_countries(ranked)
    build_site(ranked)
    print(f"Built site for {len(ranked)} contributor(s) at {OUT_DIR}/")
    if PR_NUMBER:
        n = int(PR_NUMBER)
        u = next((u for u in ranked if any(p["number"] == n for p in u["prs"])), None)
        if u:
            post_comment(n, comment_body(u, n))
        else:
            print(f"PR #{n} is not a merged contribution (not merged into main, or maintenance only); no comment posted.")


if __name__ == "__main__":
    main()
