"""
fetch_sports.py — Fetch jadwal & hasil via football-data.org (free, include World Cup)
"""

import os
import urllib.request
import json
from datetime import datetime, timezone, timedelta

API_KEY  = os.environ.get("FOOTBALLDATA_API_KEY", "")
BASE_URL = "https://api.football-data.org/v4"

WIB = timezone(timedelta(hours=7))

# Competition codes di football-data.org
COMPETITION_MAP = {
    "world_cup": "WC",   # FIFA World Cup
    "epl":       "PL",   # Premier League
    "la_liga":   "PD",   # La Liga
}

def _get(path: str) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"X-Auth-Token": API_KEY},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


async def fetch_sports_data(league_key: str) -> list[dict]:
    """Fetch pertandingan hari ini untuk liga tertentu."""
    if not API_KEY:
        raise RuntimeError(
            "FOOTBALLDATA_API_KEY belum diset.\n"
            "Daftar gratis di: https://www.football-data.org/client/register"
        )

    code  = COMPETITION_MAP.get(league_key)
    if not code:
        raise ValueError(f"Liga tidak dikenal: {league_key}")

    today = datetime.now(WIB).strftime("%Y-%m-%d")
    data  = _get(f"/competitions/{code}/matches?dateFrom={today}&dateTo={today}")

    matches = []
    for m in data.get("matches", []):
        home   = m["homeTeam"]["shortName"] or m["homeTeam"]["name"]
        away   = m["awayTeam"]["shortName"] or m["awayTeam"]["name"]
        status = m["status"]  # SCHEDULED, IN_PLAY, PAUSED, FINISHED, etc.
        score  = m["score"]

        # Status mapping
        status_map = {
            "SCHEDULED": "scheduled",
            "TIMED":     "scheduled",
            "IN_PLAY":   "live",
            "PAUSED":    "live",
            "FINISHED":  "finished",
            "SUSPENDED": "finished",
            "POSTPONED": "finished",
        }
        status_clean = status_map.get(status, "scheduled")

        # Waktu WIB
        utc_date = m.get("utcDate", "")
        try:
            dt_utc   = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            dt_wib   = dt_utc.astimezone(WIB)
            time_str = dt_wib.strftime("%H:%M")
        except Exception:
            time_str = "TBD"

        # Skor
        home_score = score.get("fullTime", {}).get("home")
        away_score = score.get("fullTime", {}).get("away")
        if home_score is None:
            home_score = score.get("halfTime", {}).get("home")
            away_score = score.get("halfTime", {}).get("away")

        matches.append({
            "id":          str(m["id"]),
            "home":        home,
            "away":        away,
            "home_score":  home_score,
            "away_score":  away_score,
            "status":      status_clean,
            "time":        time_str,
            "odd_home":    1.90,
            "odd_draw":    3.20,
            "odd_away":    1.90,
            "stage":       m.get("stage", ""),
        })

    return matches


async def get_match_by_id(match_id: str) -> dict | None:
    """Fetch detail 1 pertandingan berdasarkan match ID."""
    if not API_KEY:
        raise RuntimeError("FOOTBALLDATA_API_KEY belum diset.")

    try:
        data = _get(f"/matches/{match_id}")
    except Exception:
        return None

    m      = data
    home   = m["homeTeam"]["shortName"] or m["homeTeam"]["name"]
    away   = m["awayTeam"]["shortName"] or m["awayTeam"]["name"]
    status = m["status"]
    score  = m["score"]

    status_map = {
        "SCHEDULED": "scheduled", "TIMED": "scheduled",
        "IN_PLAY": "live", "PAUSED": "live",
        "FINISHED": "finished",
    }

    home_score = score.get("fullTime", {}).get("home")
    away_score = score.get("fullTime", {}).get("away")

    return {
        "id":         match_id,
        "home":       home,
        "away":       away,
        "home_score": home_score,
        "away_score": away_score,
        "status":     status_map.get(status, "scheduled"),
        "odd_home":   1.90,
        "odd_draw":   3.20,
        "odd_away":   1.90,
    }


async def resolve_bets(bot, data: dict) -> list[dict]:
    """Auto-resolve taruhan yang sudah FINISHED."""
    if not API_KEY:
        return []

    notifs   = []
    to_check = {b["match_id"] for b in data["bets"].values() if b["status"] == "pending"}

    for match_id in to_check:
        try:
            match = await get_match_by_id(match_id)
            if not match or match["status"] != "finished":
                continue

            home_score = match["home_score"] or 0
            away_score = match["away_score"] or 0

            for bet_id, bet in data["bets"].items():
                if bet["match_id"] != match_id or bet["status"] != "pending":
                    continue

                hc   = float(bet["handicap"])
                pick = bet["pilihan"]

                if pick == "home":
                    adj = home_score + hc
                    win = adj > away_score
                    draw_adj = adj == away_score
                elif pick == "away":
                    adj = away_score + (-hc)
                    win = adj > home_score
                    draw_adj = adj == home_score
                else:  # draw
                    win = home_score == away_score
                    draw_adj = False

                # Handicap setengah menang (push) untuk .5 handicap
                bayar = 0
                if win:
                    bayar = int(bet["nominal"] * bet["odds"])
                    bet["status"] = "win"
                elif draw_adj and abs(hc % 1) == 0:
                    # Push — kembalikan modal
                    bayar = bet["nominal"]
                    bet["status"] = "push"
                else:
                    bet["status"] = "lose"

                uid = bet["user_id"]
                if uid in data["users"]:
                    data["users"][uid]["saldo"] += bayar

                icon = {"win": "✅ MENANG", "push": "🔄 PUSH", "lose": "❌ KALAH"}[bet["status"]]
                notifs.append({
                    "user_id": uid,
                    "text": (
                        f"🎰 {icon} | **{match['home']} vs {match['away']}** "
                        f"({home_score}-{away_score})\n"
                        f"Pilihan: {pick.upper()} · {_fmt(bet['nominal'])}\n"
                        f"{'Menang: +' + _fmt(bayar) if bet['status'] == 'win' else 'Modal kembali: ' + _fmt(bayar) if bet['status'] == 'push' else 'Kalah: -' + _fmt(bet['nominal'])}"
                    ),
                })
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"resolve error match {match_id}: {e}")

    return notifs


def _fmt(n: int) -> str:
    return f"Rp {n:,}".replace(",", ".")
