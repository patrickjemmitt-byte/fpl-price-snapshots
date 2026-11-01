"""Fetch FPL price change projections from the public bootstrap-static feed
and write prices.json and prices.md. Standard library only.
"""
import datetime
import json
import sys
import urllib.request

URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def fetch():
    req = urllib.request.Request(
        URL, headers={"User-Agent": "Mozilla/5.0 (compatible; fpl-price-snapshots)"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build(boot):
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    players = []
    for el in boot["elements"]:
        projections = {}
        for p in el.get("price_change_projections") or []:
            projections[p.get("offset")] = {
                "percent": num(p.get("projected_percent")),
                "likelihood": p.get("likelihood"),
            }
        players.append(
            {
                "name": el.get("web_name"),
                "team": teams.get(el.get("team")),
                "pos": POSITIONS.get(el.get("element_type")),
                "price": el.get("now_cost", 0) / 10,
                "cost_change_event": el.get("cost_change_event"),
                "progress_now": num(el.get("price_change_percent")),
                "tonight": projections.get(0),
                "next_night": projections.get(1),
                "night_after": projections.get(2),
                "calibrating": el.get("price_change_calibrating"),
                "locked_until": el.get("price_change_locked_until"),
                "status": el.get("status"),
                "news": el.get("news"),
                "chance_next_round": el.get("chance_of_playing_next_round"),
                "net_transfers_gw": (el.get("transfers_in_event") or 0)
                - (el.get("transfers_out_event") or 0),
                "owned_pct": num(el.get("selected_by_percent")),
            }
        )
    return players


def tonight_pct(p):
    t = p.get("tonight")
    return None if not t else t.get("percent")


def row(p):
    def fmt(slot):
        s = p.get(slot)
        if not s or s.get("percent") is None:
            return "n/a"
        return "%.0f%% (L%s)" % (s["percent"], s.get("likelihood"))

    flag = ""
    if p.get("status") and p["status"] != "a":
        flag = " [%s]" % p["status"]
    elif p.get("news"):
        flag = " [news]"
    return "| %s%s | %s | %s | %.1f | %s | %s | %s | %+d |" % (
        p["name"],
        flag,
        p["team"],
        p["pos"],
        p["price"],
        fmt("tonight"),
        fmt("next_night"),
        fmt("night_after"),
        p["net_transfers_gw"],
    )


def section(title, players):
    lines = ["## %s" % title, ""]
    if not players:
        lines += ["None.", ""]
        return lines
    lines += [
        "| Player | Team | Pos | Price | Tonight | Next night | Night after | Net transfers GW |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [row(p) for p in players]
    lines.append("")
    return lines


def write_outputs(players, now):
    scored = [p for p in players if tonight_pct(p) is not None]
    rises = sorted((p for p in scored if tonight_pct(p) >= 100), key=tonight_pct, reverse=True)
    falls = sorted((p for p in scored if tonight_pct(p) <= -100), key=tonight_pct)
    near_up = sorted(
        (p for p in scored if 80 <= tonight_pct(p) < 100), key=tonight_pct, reverse=True
    )
    near_down = sorted((p for p in scored if -100 < tonight_pct(p) <= -80), key=tonight_pct)
    calibrating = any(p.get("calibrating") for p in players)

    md = [
        "# FPL price change projections",
        "",
        "Generated: %s UTC" % now,
        "",
        "Source: official FPL bootstrap-static feed. Tonight means the next 00:00 UK price change.",
        "Percent is projected progress (100 or more means a move is expected). L is the likelihood score, -5 to +5.",
        "A projection can reverse before the update if transfers change.",
        "",
    ]
    if calibrating:
        md += ["WARNING: some players are flagged as calibrating. Treat projections with caution.", ""]
    md += section("Expected to rise tonight (100% or more)", rises)
    md += section("Expected to fall tonight (-100% or less)", falls)
    md += section("Close to rising (80% to 99%)", near_up)
    md += section("Close to falling (-80% to -99%)", near_down)

    with open("prices.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    with open("prices.json", "w", encoding="utf-8") as f:
        json.dump({"generated_utc": now, "players": players}, f, ensure_ascii=False, indent=1)


def main():
    boot = fetch()
    players = build(boot)
    if not any(p.get("tonight") for p in players):
        print("ERROR: no price_change_projections found in feed", file=sys.stderr)
        sys.exit(1)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    write_outputs(players, now)
    print("Wrote prices.md and prices.json for %d players" % len(players))


if __name__ == "__main__":
    main()
