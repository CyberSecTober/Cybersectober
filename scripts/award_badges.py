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
from datetime import date, datetime, timedelta, timezone

try:  # Renders contributions as readable pages; installed by the workflow. Without them pages show plain text.
    import markdown
    import nh3
except ImportError:
    markdown = nh3 = None

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
CATCH_UP_DAYS = 7
NOW = datetime.fromisoformat(os.environ["NOW"]) if os.environ.get("NOW") else datetime.now(timezone.utc)

WEEKS = [  # (first day, last day, theme); launch week also covers anything merged before 5 October
    (None, date(2026, 10, 10), "Launch week: make your first contribution"),
    (date(2026, 10, 11), date(2026, 10, 17), "Secure What You Build"),
    (date(2026, 10, 18), date(2026, 10, 24), "Secure the Future"),
    (date(2026, 10, 25), date(2026, 10, 31), "Secure Our Communities"),
]

# ISO code -> (country name, words that identify it in a free-text GitHub location)
COUNTRIES = {
    "NG": ("Nigeria", "nigeria nigerian naija lagos abuja ibadan kano enugu ilorin abeokuta owerri uyo kaduna jos akure osogbo calabar warri onitsha asaba ikeja lekki yaba ikorodu ota ogun oyo osun ondo ekiti kwara edo anambra imo abia ebonyi bayelsa benue kogi nasarawa plateau katsina sokoto zamfara kebbi gombe bauchi borno yobe adamawa taraba jigawa fct awka nsukka zaria maiduguri makurdi lokoja minna umuahia abakaliki yenagoa ado-ekiti ogbomoso ife ile-ife ijebu sagamu;port harcourt;benin city;delta state;rivers state;cross river;akwa ibom;niger state;lagos state"),
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
    "BJ": ("Benin", "benin cotonou;porto-novo;republic of benin"),
    "TG": ("Togo", "togo lomé lome"),
    "GB": ("United Kingdom", "uk england scotland wales london manchester birmingham leeds glasgow edinburgh belfast;united kingdom;great britain;northern ireland"),
    "US": ("United States", "usa us america california texas florida washington seattle boston chicago atlanta houston dallas austin denver philadelphia virginia maryland massachusetts illinois ohio michigan arizona colorado oregon minnesota pennsylvania;united states;new york;san francisco;los angeles;new jersey;new mexico;north carolina;bay area"),
    "CA": ("Canada", "canada toronto vancouver montreal calgary ottawa"),
    "IN": ("India", "india indian bharat bangalore bengaluru mumbai delhi hyderabad chennai pune kolkata ahmedabad jaipur lucknow noida gurgaon gurugram bhopal indore chandigarh kochi surat nagpur patna ranchi bhubaneswar coimbatore vizag visakhapatnam mysore mysuru dehradun kanpur varanasi maharashtra karnataka kerala gujarat rajasthan telangana bihar haryana odisha jharkhand uttarakhand goa assam;tamil nadu;uttar pradesh;madhya pradesh;west bengal;andhra pradesh;new delhi"),
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


# Every other country, matched by its name and common alternative names: "CODE|Name|alias;alias".
OTHER_COUNTRIES = """AF|Afghanistan
AL|Albania
DZ|Algeria
AD|Andorra
AO|Angola|luanda
AG|Antigua and Barbuda|antigua
AR|Argentina|buenos aires
AM|Armenia|yerevan
AU|Australia|sydney;melbourne;brisbane;perth;adelaide;canberra
AT|Austria|vienna;wien
AZ|Azerbaijan|baku
BS|Bahamas
BH|Bahrain|manama
BD|Bangladesh|dhaka;chittagong
BB|Barbados
BY|Belarus|minsk
BE|Belgium|brussels;antwerp
BZ|Belize
BT|Bhutan
BO|Bolivia
BA|Bosnia and Herzegovina|bosnia;sarajevo
BW|Botswana|gaborone
BR|Brazil|brasil;são paulo;sao paulo;rio de janeiro
BN|Brunei
BG|Bulgaria|sofia
BF|Burkina Faso|ouagadougou
BI|Burundi|bujumbura
CV|Cabo Verde|cape verde
KH|Cambodia|phnom penh
CF|Central African Republic
TD|Chad|n'djamena
CL|Chile|santiago
CN|China|beijing;shanghai;shenzhen;guangzhou;hangzhou
CO|Colombia|bogotá;bogota;medellín;medellin
KM|Comoros
CG|Republic of the Congo|congo-brazzaville;brazzaville
CD|DR Congo|drc;dr congo;democratic republic of the congo;kinshasa;lubumbashi
CR|Costa Rica
HR|Croatia|zagreb
CU|Cuba|havana
CY|Cyprus|nicosia
CZ|Czechia|czech republic;prague
DK|Denmark|copenhagen
DJ|Djibouti
DM|Dominica
DO|Dominican Republic|santo domingo
EC|Ecuador|quito
SV|El Salvador
GQ|Equatorial Guinea
ER|Eritrea|asmara
EE|Estonia|tallinn
SZ|Eswatini|swaziland
FJ|Fiji
FI|Finland|helsinki
GA|Gabon|libreville
GE|Georgia|tbilisi
GR|Greece|athens
GD|Grenada
GT|Guatemala
GN|Guinea|conakry
GW|Guinea-Bissau
GY|Guyana
HT|Haiti
HN|Honduras
HK|Hong Kong
HU|Hungary|budapest
IS|Iceland|reykjavik
ID|Indonesia|jakarta;bandung;surabaya;bali
IR|Iran|tehran
IQ|Iraq|baghdad;erbil
IL|Israel|tel aviv;jerusalem
IT|Italy|italia;rome;roma;milan;milano;turin
JM|Jamaica|kingston
JP|Japan|tokyo;osaka;kyoto
JO|Jordan|amman
KZ|Kazakhstan|almaty;astana
KI|Kiribati
KW|Kuwait
KG|Kyrgyzstan|bishkek
LA|Laos
LV|Latvia|riga
LB|Lebanon|beirut
LS|Lesotho|maseru
LY|Libya|tripoli
LI|Liechtenstein
LT|Lithuania|vilnius
LU|Luxembourg
MO|Macau
MG|Madagascar|antananarivo
MW|Malawi|lilongwe;blantyre
MY|Malaysia|kuala lumpur;penang
MV|Maldives
ML|Mali|bamako
MT|Malta
MH|Marshall Islands
MR|Mauritania|nouakchott
MU|Mauritius
MX|Mexico|méxico;guadalajara;monterrey
FM|Micronesia
MD|Moldova|chisinau
MC|Monaco
MN|Mongolia|ulaanbaatar
ME|Montenegro
MZ|Mozambique|maputo
MM|Myanmar|yangon
NA|Namibia|windhoek
NR|Nauru
NP|Nepal|kathmandu
NZ|New Zealand|auckland;wellington
NI|Nicaragua
NE|Niger|niamey
KP|North Korea
MK|North Macedonia|skopje
NO|Norway|oslo
OM|Oman|muscat
PK|Pakistan|karachi;lahore;islamabad;rawalpindi;peshawar;faisalabad
PW|Palau
PS|Palestine|gaza;ramallah
PA|Panama
PG|Papua New Guinea
PY|Paraguay
PE|Peru|lima
PH|Philippines|manila;cebu;quezon city
PL|Poland|polska;warsaw;krakow;kraków
PT|Portugal|lisbon;porto
PR|Puerto Rico
QA|Qatar|doha
RO|Romania|bucharest
RU|Russia|moscow;saint petersburg
WS|Samoa
SM|San Marino
ST|São Tomé and Príncipe|sao tome
SA|Saudi Arabia|ksa;riyadh;jeddah
RS|Serbia|belgrade
SC|Seychelles
SG|Singapore
SK|Slovakia|bratislava
SI|Slovenia|ljubljana
SB|Solomon Islands
SO|Somalia|mogadishu;somaliland
KR|South Korea|korea;seoul;busan
SS|South Sudan|juba
ES|Spain|españa;madrid;barcelona;valencia
LK|Sri Lanka|colombo
KN|Saint Kitts and Nevis
LC|Saint Lucia
VC|Saint Vincent and the Grenadines
SD|Sudan|khartoum
SR|Suriname
SE|Sweden|sverige;stockholm;gothenburg
CH|Switzerland|zurich;zürich;geneva;bern
SY|Syria|damascus
TW|Taiwan|taipei
TJ|Tajikistan
TH|Thailand|bangkok
TL|Timor-Leste|east timor
TO|Tonga
TT|Trinidad and Tobago|trinidad
TN|Tunisia|tunis
TR|Türkiye|turkey;turkiye;istanbul;ankara;izmir
TM|Turkmenistan
TV|Tuvalu
UA|Ukraine|kyiv;kiev;lviv;kharkiv
UY|Uruguay|montevideo
UZ|Uzbekistan|tashkent
VU|Vanuatu
VA|Vatican City
VE|Venezuela|caracas
VN|Vietnam|viet nam;hanoi;ho chi minh
YE|Yemen|sanaa
"""
for _line in OTHER_COUNTRIES.strip().splitlines():
    _code, _name, *_aliases = _line.split("|")
    if _code not in COUNTRIES:
        COUNTRIES[_code] = (_name, ";" + ";".join([_name.lower()] + (_aliases[0].split(";") if _aliases else [])))

COUNTRY_PATTERNS = [(code, re.compile(r"(?<![\w])(" + "|".join(re.escape(t) for t in _terms(spec) if t) + r")(?![\w])"))
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
MAINTENANCE_DIRS = ("scripts/", ".github/", "data/")


POSTS_FILE, TIPS_FILE = "awareness/posts.md", "awareness/tips.md"
POST_MILESTONES = [(1, "awareness-advocate"), (5, "signal-booster")]
MAX_TIPS_FOR_POINTS = 5


def pr_files(pr):
    if "_files" not in pr:
        pr["_files"] = paginate(f"/repos/{REPO}/pulls/{pr['number']}/files")
    return pr["_files"]


def content_info(pr):
    """What the contribution added, as it reads today on main: the lines it added to the tips or posts list, a single
    page (guide, quiz, write-up), or a folder (tool, lab). kind is "lines", "file", "folder" or "pr" if it has moved."""
    files = [f for f in pr_files(pr) if f["filename"].startswith(CONTENT_DIRS) and f["status"] != "removed"
             and os.path.exists(f["filename"])]
    if not files:
        return {"kind": "pr", "url": pr["html_url"]}
    names = [f["filename"] for f in files]
    if len(files) == 1 and names[0] in (TIPS_FILE, POSTS_FILE):
        added = [l[1:].strip() for l in (files[0].get("patch") or "").splitlines()
                 if l.startswith("+") and not l.startswith("+++") and l[1:].strip()]
        return {"kind": "lines", "path": names[0], "lines": added, "url": f"{REPO_URL}/blob/main/{names[0]}"}
    folder = os.path.commonpath(names) if len(names) > 1 else ""
    if folder and folder.count("/") >= 1:
        readme = next((n for n in sorted(names, key=len) if os.path.basename(n).lower() == "readme.md"), None)
        page_file = readme or next((n for n in names if n.endswith(".md")), None)
        return {"kind": "folder", "path": folder, "page": page_file, "files": sorted(names),
                "url": f"{REPO_URL}/tree/main/{folder}"}
    page_file = next((n for n in names if n.endswith(".md")), names[0])
    return {"kind": "file", "path": page_file, "page": page_file if page_file.endswith(".md") else None,
            "url": f"{REPO_URL}/blob/main/{page_file}"}


def points_for(pr):
    """Return (points, labels, counts, is_post). Unlabelled PRs that touch no content folder are maintenance and
    don't count; unlabelled PRs that only add to the posts file are awareness posts (badges, no points)."""
    labels = {l["name"] for l in pr["labels"]}
    pts = max((int(l.split("-")[1]) for l in labels if l.startswith("points-") and l.split("-")[1].isdigit()), default=0)
    counts, is_post, is_tip = True, False, False
    if not pts:
        files = {f["filename"] for f in pr_files(pr)}
        if files == {"awareness/tips.md"}:
            pts, is_tip = 3, True
        is_post = files == {POSTS_FILE}
        counts = (any(f.startswith(CONTENT_DIRS) for f in files)
                  and not any(f.startswith(MAINTENANCE_DIRS) for f in files))
    if pts and "quality-bonus" in labels:
        pts += 5
    return pts, labels, counts, is_post, is_tip


def load_organizers():
    path = "data/organizers.json"
    return {l.lower() for l in json.load(open(path))} if os.path.exists(path) else set()


def compute(prs, manual, organizers=frozenset()):
    """Organizers (maintainers running the challenge) never earn points or badges, so they stay off the leaderboard."""
    users = {}
    for pr in prs:
        login = pr["user"]["login"]
        if login.lower() in organizers:
            continue
        pts, labels, counts, is_post, is_tip = points_for(pr)
        if not counts:
            continue
        u = users.setdefault(login, {"login": login, "points": 0, "prs": [], "badges": {}, "posts": 0, "post_weeks": set(), "tips": 0})
        capped = False
        if is_tip:
            u["tips"] += 1
            if u["tips"] > MAX_TIPS_FOR_POINTS:
                pts, capped = 0, True
        before = u["points"]
        u["points"] += pts
        u["prs"].append({"number": pr["number"], "title": pr["title"], "url": pr["html_url"], "info": content_info(pr),
                         "labels": sorted(labels),
                         "merged_at": pr["merged_at"], "points": pts, "post": is_post, "capped": capped})

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
        if login.lower() in organizers:
            continue
        u = users.setdefault(login, {"login": login, "points": 0, "prs": [], "badges": {}, "posts": 0, "post_weeks": set(), "tips": 0})
        for slug in slugs:
            if slug in BADGES:
                u["badges"].setdefault(slug, {"date": None, "pr": None})
    ranked = sorted(users.values(), key=lambda u: (-u["points"], min((p["merged_at"] for p in u["prs"]), default="9")))
    for i, u in enumerate(ranked, 1):
        u["rank"] = i
        # Points needed to overtake the person one place above (ties go to whoever merged first).
        u["to_pass"] = ranked[i - 2]["points"] - u["points"] + 1 if i > 1 else None
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
    # The most specific match wins ("Niger State, Nigeria" is Nigeria, "Papua New Guinea" is not Guinea);
    # on a tie the country listed first wins ("Atlanta, Georgia" is the United States).
    text, best = location.lower(), None
    for code, pattern in COUNTRY_PATTERNS:
        length = max((len(m.group()) for m in pattern.finditer(text)), default=0)
        if length and (best is None or length > best[0]):
            best = (length, code)
    return (best[1], COUNTRIES[best[1]][0]) if best else None


def add_countries(ranked):
    for u in ranked:
        try:
            location = (api(f"/users/{u['login']}") or {}).get("location")
        except Exception as e:
            print(f"::warning::Could not read the profile of @{u['login']}: {e}")
            u["country"] = None
            continue
        u["country"] = country_from_location(location)
        if not location:
            print(f"::notice::@{u['login']} has no location on their GitHub profile, so no country is shown.")
        elif not u["country"]:
            print(f"::notice::Could not match a country for @{u['login']} from their location {location!r}.")


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


def standing(u):
    """One sentence on where the contributor sits and what it takes to move up."""
    if u["to_pass"] is None:
        return "You are **#1** on the leaderboard. Keep contributing to stay on top."
    n = u["to_pass"]
    return (f"You are **#{u['rank']}** on the leaderboard. **{n} more point{'' if n == 1 else 's'}** "
            f"moves you up to #{u['rank'] - 1}.")


def md_bold(text):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text))


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
                 f"- Total points: **{u['points']}**", ""]
    if pr["capped"]:
        lines += [f"Your tip has been merged. Only your first {MAX_TIPS_FOR_POINTS} tips earn points, so this one is "
                  "recorded without points. Guides, translations, checklists, labs and tools are the way to keep earning.", ""]
    elif not pr["points"] and not pr["post"]:
        lines += ["> **Note for maintainers:** this pull request has no `points-*` label, so no points have been "
                  "awarded yet. Add the appropriate label and this comment will update automatically.", ""]
    for s in new:
        lines += [f"**Badge earned: {BADGES[s][0]}**", "",
                  f'<img src="{RAW_BADGES}/cards/{s}.jpg" width="240" alt="{BADGES[s][0]} badge">', "",
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
    lines += [f"**Leaderboard:** {standing(u)} [See the leaderboard]({SITE_URL})", ""]
    if pr["post"]:
        lines += ["Posts earn badges. Tips, guides, translations, checklists, labs and tools earn points.", ""]
    lines += [f"**Verification:** your badges and contributions can be verified publicly at {verify_url(login)}. "
              "Use this link as the Credential URL when adding a badge to LinkedIn. To display your badges on your GitHub "
              "profile, copy the ready-made snippet from your verification page.", "",
              f"If you haven't already, please star the [repository]({REPO_URL}) using the Star button at the top right "
              "of the page. It helps more people find CyberSecTOBER.", "",
              "Thank you for helping make the internet safer.", "",
              "The CyberSecTOBER team"]
    return "\n".join(lines)


def award_comments(pr_number):
    return [c for c in paginate(f"/repos/{REPO}/issues/{pr_number}/comments")
            if MARKER in (c.get("body") or "") and c["user"]["type"] == "Bot"]


def post_comment(pr_number, body):
    if DRY_RUN:
        print(f"--- DRY RUN: comment for PR #{pr_number} ---\n{body}\n---")
        return
    existing = award_comments(pr_number)
    if existing:
        api(f"/repos/{REPO}/issues/comments/{existing[0]['id']}", "PATCH", {"body": body})
    else:
        api(f"/repos/{REPO}/issues/{pr_number}/comments", "POST", {"body": body})


def catch_up(ranked):
    """Post award comments that a run never delivered, for example when GitHub Actions had no runner available.
    Only looks at contributions merged in the last CATCH_UP_DAYS days that have no award comment yet."""
    cutoff = NOW - timedelta(days=CATCH_UP_DAYS)
    for u in ranked:
        for p in u["prs"]:
            merged = datetime.fromisoformat(p["merged_at"].replace("Z", "+00:00"))
            if merged < cutoff or award_comments(p["number"]):
                continue
            print(f"Catching up: PR #{p['number']} by @{u['login']} has no award comment yet.")
            post_comment(p["number"], comment_body(u, p["number"]))


def contribution_link(p, root=""):
    """The title opens a readable page with the contribution itself; the number links to the pull request as proof."""
    return (f'<a href="{root}c/{p["number"]}/">{html.escape(p["title"])}</a> '
            f'<a class="muted" href="{p["url"]}">#{p["number"]}</a>')


def front_matter(text):
    """Split an optional YAML header (--- key: value ---) from markdown. Returns (fields, body)."""
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}, text
    fields = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and value.strip():
            fields[key.strip().lower()] = value.strip().strip("\"'")
    return fields, text[m.end():]


def render_markdown(text, path):
    """Markdown to safe HTML. Relative links and images point back to the file's folder on GitHub."""
    if not (markdown and nh3):
        return f"<pre>{html.escape(text)}</pre>"
    parts = re.split(r"(```.*?```)", text, flags=re.S)  # make bare web addresses clickable, outside code blocks
    text = "".join(part if part.startswith("```") else
                   re.sub(r'(?<![("<\[=])(https?://[^\s<>()"]+[^\s<>()".,;:!?])', r"<\1>", part) for part in parts)
    out = markdown.markdown(text, extensions=["extra", "sane_lists"])
    folder = os.path.dirname(path) + "/" if os.path.dirname(path) else ""

    def absolute(m):
        attr, url = m.group(1), m.group(2)
        if re.match(r"^(https?:|mailto:|#)", url):
            return m.group(0)
        base = f"https://raw.githubusercontent.com/{REPO}/main/" if attr == "src" else f"{REPO_URL}/blob/main/"
        return f'{attr}="{urllib.parse.urljoin(base + folder, url)}"'

    out = re.sub(r'\b(src|href)="([^"]*)"', absolute, out)
    return nh3.clean(out, url_schemes={"http", "https", "mailto"})


def first_link(text):
    m = re.search(r"\]\((https?://[^)\s]+)\)", text) or re.search(r"https?://\S+", text)
    return (m.group(1) if m.lastindex else m.group(0)) if m else None


def contribution_page(u, p):
    info = p["info"]
    fields, body_md, content = {}, "", ""
    if info["kind"] == "lines":
        items = "".join(f"<li>{render_markdown(l[2:] if l.startswith('- ') else l, info['path'])}</li>" for l in info["lines"])
        content = f'<div class="panel prose"><ul class="contribution-lines">{items}</ul></div>'
        link = first_link(" ".join(info["lines"])) if p["post"] else None
        if link:
            content += f'<p><a class="cta" href="{html.escape(link)}">Read the full post</a></p>'
    elif info.get("page"):
        fields, body_md = front_matter(open(info["page"], encoding="utf-8").read())
        heading = re.match(r"\A\s*#\s+(.+?)\s*#*\s*\n", body_md)
        if heading:  # the page's own heading becomes the page title instead of appearing twice
            fields.setdefault("title", heading.group(1))
            body_md = body_md[heading.end():]
        content = f'<article class="panel prose">{render_markdown(body_md, info["page"])}</article>'
        if info["kind"] == "folder":
            files = "".join(f'<li><a href="{REPO_URL}/blob/main/{f}">{html.escape(f[len(info["path"]) + 1:])}</a></li>'
                            for f in info["files"])
            content += f'<h2>Files</h2><div class="panel"><ul>{files}</ul></div>'
    else:
        content = f'<div class="panel"><p>View this contribution on GitHub.</p></div>'
    title = fields.get("title") or p["title"]
    tracks = [l for l in p["labels"] if l in ("awareness", "api-security", "ai-security", "community")]
    meta = [f'<a href="../../u/{u["login"].lower()}/">@{html.escape(u["login"])}</a>', fmt_date(p["merged_at"]),
            "Awareness post" if p["post"] else f'{p["points"]} points'] + [html.escape(t) for t in tracks]
    desc = f'<p class="lead">{html.escape(fields["description"])}</p>' if fields.get("description") else ""
    body = (f'<h1>{html.escape(title)}</h1>{desc}'
            f'<div class="byline"><img src="https://github.com/{u["login"]}.png?size=64" alt="">{" · ".join(meta)}</div>'
            f'{content}'
            f'<p class="muted">Contributed to the CyberSecTOBER open-source library under '
            f'<a href="{REPO_URL}/blob/main/LICENSE-CONTENT.md">CC BY 4.0</a>. '
            f'<a href="{info["url"]}">View on GitHub</a> · <a href="{p["url"]}">Pull request #{p["number"]}</a></p>')
    return page(f"{title}: CyberSecTOBER 2026", body, 2)


def fmt_date(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%-d %B %Y") if iso else "Awarded by a maintainer"


def page(title, body, depth):
    root = "../" * depth
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<script data-goatcounter="https://cybersectober.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
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
.badge{{text-align:center}}.badge img{{width:100%;max-width:240px;height:auto;border-radius:10px;display:block;margin:0 auto 10px}}.badge p{{margin:0;color:var(--muted);font-size:14px}}
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
.lead{{color:var(--muted);font-size:18px;margin:4px 0 12px}}
.byline{{color:var(--muted);font-size:15px;margin:10px 0 20px}}.byline img{{width:28px;height:28px;border-radius:50%;vertical-align:middle;margin-right:8px}}
.prose{{font-size:17px;line-height:1.7;overflow-wrap:anywhere}}.prose h1{{font-size:28px}}.prose h2{{font-size:22px;margin:28px 0 10px}}.prose h3{{font-size:19px;margin:22px 0 8px}}
.prose img{{max-width:100%;height:auto;border-radius:10px}}.prose hr{{border:0;border-top:1px solid var(--line);margin:24px 0}}
.prose code{{font:14px "IBM Plex Mono",monospace;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:1px 6px}}.prose pre code{{border:0;padding:0}}
.prose blockquote{{margin:0;padding-left:14px;border-left:3px solid var(--accent);color:var(--muted)}}.prose>:first-child{{margin-top:0}}
.contribution-lines{{margin:0;padding-left:20px}}.contribution-lines p{{margin:0}}
.cta{{display:inline-block;background:var(--accent);color:#06281A;text-decoration:none;font-weight:700;border-radius:10px;padding:11px 18px;margin-top:12px}}
button{{background:var(--accent);color:#06281A;border:0;border-radius:8px;padding:9px 16px;font:600 15px "Space Grotesk",system-ui,sans-serif;cursor:pointer}}.table-wrap{{overflow-x:auto}}
</style></head><body><main>
<div class="eyebrow"><a href="{root}" style="color:inherit;text-decoration:none">CyberSecTOBER 2026</a></div>
{body}
<footer>Updated {NOW.strftime("%-d %B %Y, %H:%M")} UTC. Badges are awarded automatically from merged pull requests in <a href="{REPO_URL}">{html.escape(REPO)}</a>. Points and badges on this site are the official record.</footer>
</main></body></html>"""


def badge_tile(u, slug, root):
    b = u["badges"][slug]
    source = f'<a href="{REPO_URL}/pull/{b["pr"]}">PR #{b["pr"]}</a>' if b["pr"] else "Maintainer award"
    return (f'<div class="panel badge"><img src="{root}badges/cards/{slug}.jpg" alt="{html.escape(BADGES[slug][0])} badge: '
            f'{html.escape(BADGES[slug][1])}">'
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


CHALLENGE_LABELS = {"open-to-all", "good first issue", "beginner", "intermediate", "advanced"}


def issue_section(body, name):
    """Plain text of one '### Heading' section of a challenge issue, for the game."""
    m = re.search(rf"^###\s*{re.escape(name)}\s*$(.*?)(?=^###|^---|\Z)", body or "", re.S | re.M)
    text = m.group(1).strip() if m else ""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text).replace("`", "")
    return text[:700]


def done_path(body):
    """The file or folder a challenge asks for: the first `folder/file` in its "Done when" section."""
    m = re.search(r"^###\s*Done when\s*$(.*?)(?=^###|^---|\Z)", body or "", re.S | re.M)
    return next((t for t in re.findall(r"`([^`\s]+)`", m.group(1) if m else "")
                 if "/" in t and not t.startswith(("templates/", "http"))), None)


def open_challenges():
    """Open challenge issues, published in data.json so the Shield Up game can show them."""
    try:
        issues = paginate(f"/repos/{REPO}/issues?state=open")
    except Exception as e:  # the site still builds without them
        print(f"::warning::Could not list open challenges: {e}")
        return []
    out = []
    for i in issues:
        labels = [label["name"] for label in i.get("labels", [])]
        if "pull_request" in i or not CHALLENGE_LABELS & set(labels):
            continue
        out.append({"number": i["number"], "title": i["title"], "labels": labels, "assigned": bool(i.get("assignees")),
                    "what": issue_section(i.get("body"), "What to build"), "done": issue_section(i.get("body"), "Done when"),
                    "path": done_path(i.get("body"))})
    return out


def build_site(ranked):
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    os.makedirs(OUT_DIR)
    shutil.copytree("badges", os.path.join(OUT_DIR, "badges"), ignore=shutil.ignore_patterns("*.md", "svg"))
    if os.path.isdir("site"):
        shutil.copytree("site", OUT_DIR, dirs_exist_ok=True)
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
    latest_rows = [f'<tr><td>{who_cell(u)}</td><td>{contribution_link(p)}'
                   f'<br><span class="muted" style="font-size:14px">{fmt_date(p["merged_at"])}</span></td>'
                   f'<td class="num">{"Post" if p["post"] else "+" + str(p["points"])}</td></tr>' for u, p in contributions[:10]]

    index = (f'<h1>Leaderboard</h1><p class="muted">Every merged contribution to CyberSecTOBER 2026, verified. '
             f'<a href="join/">How to join →</a></p>'
             f'<div class="statbar">{statbar}</div>'
             f'<h2>This week</h2><div class="week">Week {wi + 1} · {html.escape(theme)} · {span}</div>'
             f'<div class="panel" style="margin-top:10px">{table(["#", "Contributor", "Points"], week_rows, "No merged contributions this week yet. Yours could be the first!")}</div>'
             f'<h2>Overall</h2><div class="panel">{table(["#", "Contributor", "Badges", "Points"], overall_rows, "No merged contributions yet. Be the first!")}</div>'
             f'<h2>Countries</h2><div class="panel">{table(["#", "Country", "Contributors", "Points"], country_rows, "No countries yet. Add your location to your GitHub profile to represent your country.")}'
             f'<p class="muted" style="margin:12px 0 0;font-size:14px">Based on the Location field of each contributor\'s GitHub profile.</p></div>'
             f'<h2>Latest contributions</h2><div class="panel">{table(["Contributor", "Contribution", "Points"], latest_rows, "Nothing merged yet.")}</div>')
    open(os.path.join(OUT_DIR, "index.html"), "w").write(page("CyberSecTOBER 2026 Leaderboard", index, 0))
    # Public, machine-readable record for the site's own pages (for example the Eko Cyber Life game).
    with open(os.path.join(OUT_DIR, "data.json"), "w") as f:
        json.dump({"updated": NOW.isoformat(timespec="minutes"),
                   "contributors": [{"login": u["login"], "points": u["points"], "rank": u["rank"],
                                     "badges": [s for s in BADGES if s in u["badges"]], "contributions": len(u["prs"]),
                                     "country": u["country"][1] if u.get("country") else None,
                                     "merged": sorted(p["merged_at"][:10] for p in u["prs"])}
                                    for u in ranked],
                   "challenges": open_challenges()}, f, indent=1)

    for u, p in contributions:
        d = os.path.join(OUT_DIR, "c", str(p["number"]))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "index.html"), "w").write(contribution_page(u, p))

    for u in ranked:
        login = u["login"]
        d = os.path.join(OUT_DIR, "u", login.lower())
        os.makedirs(d, exist_ok=True)
        tiles = "".join(badge_tile(u, s, "../../") for s in BADGES if s in u["badges"])
        earned = [s for s in BADGES if s in u["badges"]]
        for s in earned:
            shutil.copy(os.path.join("badges", f"{s}.png"), os.path.join(d, f"{s}.png"))
            shutil.copy(os.path.join("badges", "cards", f"{s}.jpg"), os.path.join(d, f"{s}.jpg"))
        snippet = "\n".join(f'<a href="{verify_url(login)}"><img src="{verify_url(login)}{s}.jpg" width="180" '
                             f'alt="CyberSecTOBER 2026 {BADGES[s][0]} badge, verified"></a>' for s in earned)
        embed = (f'<h2>Show your badges on GitHub</h2><div class="panel">'
                 f'<p style="margin-top:0">Paste this into your GitHub profile README. The images only exist for badges you have earned, '
                 f'and each one links back to this page as proof.</p>'
                 f'<pre id="snippet">{html.escape(snippet)}</pre>'
                 f'<button onclick="navigator.clipboard.writeText(document.getElementById(\'snippet\').innerText);this.textContent=\'Copied\'">Copy snippet</button>'
                 f'</div>') if earned else ""
        prs = [f'<tr><td>{contribution_link(p, "../../")}</td>'
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
                f'<p class="muted" style="margin:12px 0 0">{md_bold(standing(u))} <a href="../../">See the leaderboard →</a></p>'
                f'<h2>Badges</h2><div class="grid">{tiles}</div>'
                f'{embed}'
                f'<h2>Contributions</h2><div class="panel">'
                + table(["Contribution", "Merged", "Points"], prs, "Badges awarded by maintainers.") + '</div>')
        open(os.path.join(d, "index.html"), "w").write(page(f"{login}: CyberSecTOBER 2026 badges", body, 2))


def main():
    manual = json.load(open("data/manual-awards.json")) if os.path.exists("data/manual-awards.json") else {}
    ranked = compute(merged_prs(), manual, load_organizers())
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
    catch_up(ranked)


if __name__ == "__main__":
    main()
