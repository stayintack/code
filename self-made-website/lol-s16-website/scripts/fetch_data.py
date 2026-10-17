"""Fetch Worlds 2026 schedule/results from the LoL Esports API and write data.js for the S16 page."""
import json, sys, urllib.request, datetime

KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"  # public key used by lolesports.com
BASE = "https://esports-api.lolesports.com/persisted/gw"
LEAGUE = "98767975604431411"
STAGE = {"入围赛": "pi", "瑞士轮": "swiss", "四分之一决赛": "qf", "半决赛": "sf", "决赛": "f"}

def get(path):
    req = urllib.request.Request(BASE + path, headers={"x-api-key": KEY})
    return json.load(urllib.request.urlopen(req, timeout=30))["data"]

def pages():
    first = get(f"/getSchedule?hl=zh-CN&leagueId={LEAGUE}")["schedule"]
    yield first
    for direction in ("older", "newer"):
        tok = first["pages"].get(direction)
        while tok:
            s = get(f"/getSchedule?hl=zh-CN&leagueId={LEAGUE}&pageToken={tok}")["schedule"]
            if not any(e["startTime"] >= "2026-10-01" for e in s["events"]):
                break
            yield s
            tok = s["pages"].get(direction)

seen, out = set(), []
for p in pages():
    for e in p["events"]:
        m = e.get("match")
        if not m or e["startTime"] < "2026-10-01" or m["id"] in seen:
            continue
        seen.add(m["id"])
        teams = []
        for t in m["teams"]:
            code = t.get("code")
            r = t.get("result") or {}
            teams.append({"c": None if code in (None, "TBD") else code, "g": r.get("gameWins"), "o": r.get("outcome")})
        out.append({"id": m["id"], "t": e["startTime"], "st": STAGE.get(e["blockName"], e["blockName"]),
                    "bo": m["strategy"]["count"], "s": e["state"], "teams": teams})
out.sort(key=lambda x: (x["t"], x["id"]))
data = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "matches": out}
dest = sys.argv[1] if len(sys.argv) > 1 else "data.js"
open(dest, "w").write("const DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
print(dest, len(out), "matches;", sum(1 for x in out if x["s"] == "completed"), "completed")
