"""Fetch Patrick's FPL squad from the public FPL API and write team.json.
Standard library only. Needs the environment variable TEAM_ID.
Never fails the workflow: on any error it writes team.json with an "error" field.

Selling prices are NOT in the public API, so they are worked out here with the
half-profit rule from the purchase prices in the transfer history. Players who
were never transferred in use their start price (now_cost - cost_change_start),
which can be wrong after a wildcard, so each player carries a "purchase_source".
"""
import datetime
import json
import os
import sys
import urllib.request

BASE = "https://fantasy.premierleague.com/api/"
POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def get(path):
    req = urllib.request.Request(
        BASE + path, headers={"User-Agent": "Mozilla/5.0 (compatible; fpl-price-snapshots)"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def selling_price(current, purchase):
    """Half the profit, rounded down to 0.1. Works in tenths of a million."""
    if current > purchase:
        return purchase + (current - purchase) // 2
    return current


def main():
    team_id = os.environ.get("TEAM_ID", "").strip()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    out = {"generated_utc": now, "team_id": team_id}
    try:
        boot = get("bootstrap-static/")
        elements = {e["id"]: e for e in boot["elements"]}
        teams = {t["id"]: t["short_name"] for t in boot["teams"]}
        finished = [e["id"] for e in boot["events"] if e.get("finished")]
        current = next((e["id"] for e in boot["events"] if e.get("is_current")), None)
        next_ev = next((e for e in boot["events"] if e.get("is_next")), None)
        last_done = max(finished) if finished else 1
        # Picks for the current gameweek already include transfers made before its
        # deadline. Anything with a later event number is replayed below.
        base_event = current or last_done

        picks = get("entry/%s/event/%s/picks/" % (team_id, base_event))
        last_done = base_event
        transfers = get("entry/%s/transfers/" % team_id)
        transfers.sort(key=lambda t: t["time"])

        squad = {p["element"]: p for p in picks["picks"]}
        # Replay every transfer made after the last finished gameweek.
        for t in transfers:
            if t["event"] > last_done:
                squad.pop(t["element_out"], None)
                squad[t["element_in"]] = {"element": t["element_in"], "position": None}

        last_in = {}
        for t in transfers:
            last_in[t["element_in"]] = t["element_in_cost"]

        players = []
        for el_id in squad:
            e = elements[el_id]
            now_cost = e["now_cost"]
            if el_id in last_in:
                purchase, source = last_in[el_id], "transfer"
            else:
                purchase, source = now_cost - e["cost_change_start"], "start_price"
            players.append(
                {
                    "name": e["web_name"],
                    "team": teams[e["team"]],
                    "pos": POSITIONS[e["element_type"]],
                    "price": now_cost / 10,
                    "purchase": purchase / 10,
                    "selling": selling_price(now_cost, purchase) / 10,
                    "purchase_source": source,
                }
            )
        order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
        players.sort(key=lambda p: (order[p["pos"]], p["name"]))

        later = [t for t in transfers if t["event"] > last_done]
        # element_out_cost is the sale price, element_in_cost the buy price.
        bank = picks["entry_history"]["bank"] + sum(
            t["element_out_cost"] - t["element_in_cost"] for t in later
        )
        out.update(
            {
                "picks_from_gameweek": last_done,
                "current_event": current,
                "next_deadline": next_ev["deadline_time"] if next_ev else None,
                "bank": bank / 10,
                "bank_base_from_picks": picks["entry_history"]["bank"] / 10,
                "gw_transfers_made": picks["entry_history"]["event_transfers"],
                "gw_transfer_cost": picks["entry_history"]["event_transfers_cost"],
                "transfers_after_base_gw": later,
                "players": players,
                "note": "Bank nets off transfers made after the base gameweek. Free transfers are not in the public API: verify on the Transfers screen.",
            }
        )
    except Exception as exc:  # never break the price job
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
        print("team fetch failed:", out["error"], file=sys.stderr)

    with open("team.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("Wrote team.json")


if __name__ == "__main__":
    main()
