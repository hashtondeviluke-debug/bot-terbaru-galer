"""
fetch_sports.py — Fetch jadwal & hasil pertandingan via SportRadar / API-Football
Pakai API gratis api-football.com (100 req/hari)
"""

import os
import aiohttp
from datetime import datetime, timezone, timedelta

API_KEY  = os.environ.get("FOOTBALL_API_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"

WIB = timezone(timedelta(hours=7))

LEAGUE_IDS = {
    "world_cup": 1,    # FIFA World Cup 2026
    "epl":       39,   # Premier League
    "la_liga":   140,  # La Liga
}

# Season aktif per liga
LEAGUE_SEASONS = {
    "world_cup": 2026,
    "epl":       2025,
    "la_liga":   2025,
}

async def fetch_sports_data(league_key: str) -> list[dict]:
    """Fetch pertandingan hari ini untuk liga tertentu."""
    if not API_KEY:
        raise RuntimeError(
            "FOOTBALL_API_KEY belum diset.\n"
            "Daftar gratis di: https://www.api-football.com/"
        )

    league_id = LEAGUE_IDS.get(league_key)
    if not league_id:
        raise ValueError(f"Liga tidak dikenal: {league_key}")

    today = datetime.now(WIB).strftime("%Y-%m-%d")

    headers = {
        "x-apisports-key": API_KEY,
    }
    params = {
        "league": league_id,
        "date":   today,
        "season": LEAGUE_SEASONS[league_key],
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BASE_URL}/fixtures",
            headers=headers,
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"API error {resp.status}")
            data = await resp.json()

    matches = []
    for fix in data.get("response", []):
        fixture  = fix["fixture"]
        teams    = fix["teams"]
        goals    = fix["goals"]
        odds_raw = fix.get("odds", {})
        status   = fixture["status"]["short"]  # NS, 1H, HT, 2H, FT, etc

        # Status mapping
        status_map = {
            "NS": "scheduled", "TBD": "scheduled",
            "1H": "live", "HT": "live", "2H": "live", "ET": "live",
            "FT": "finished", "AET": "finished", "PEN": "finished",
        }
        status_clean = status_map.get(status, "scheduled")

        # Waktu WIB
        kt = datetime.fromtimestamp(fixture["timestamp"], tz=WIB)
        time_str = kt.strftime("%H:%M")

        matches.append({
            "id":          str(fixture["id"]),
            "home":        teams["home"]["name"],
            "away":        teams["away"]["name"],
            "home_score":  goals["home"],
            "away_score":  goals["away"],
            "status":      status_clean,
            "time":        time_str,
            "odd_home":    1.90,  # default odds kalau tidak ada
            "odd_draw":    3.20,
            "odd_away":    1.90,
        })

    return matches


async def get_match_by_id(match_id: str) -> dict | None:
    """Fetch detail 1 pertandingan berdasarkan fixture ID."""
    if not API_KEY:
        raise RuntimeError("FOOTBALL_API_KEY belum diset.")

    headers = {"x-apisports-key": API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BASE_URL}/fixtures",
            headers=headers,
            params={"id": match_id},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()

    resp_list = data.get("response", [])
    if not resp_list:
        return None

    fix    = resp_list[0]
    teams  = fix["teams"]
    goals  = fix["goals"]
    status = fix["fixture"]["status"]["short"]
    status_map = {
        "NS": "scheduled", "TBD": "scheduled",
        "1H": "live", "HT": "live", "2H": "live",
        "FT": "finished", "AET": "finished", "PEN": "finished",
    }
    return {
        "id":         match_id,
        "home":       teams["home"]["name"],
        "away":       teams["away"]["name"],
        "home_score": goals["home"],
        "away_score": goals["away"],
        "status":     status_map.get(status, "scheduled"),
        "odd_home":   1.90,
        "odd_draw":   3.20,
        "odd_away":   1.90,
    }


async def resolve_bets(bot, data: dict) -> list[str]:
    """
    Cek semua bet pending, resolve yang sudah FT.
    Return list pesan notifikasi.
    """
    if not API_KEY:
        return []

    headers   = {"x-apisports-key": API_KEY}
    notifs    = []
    to_check  = {b["match_id"] for b in data["bets"].values() if b["status"] == "pending"}

    async with aiohttp.ClientSession() as session:
        for match_id in to_check:
            async with session.get(
                f"{BASE_URL}/fixtures",
                headers=headers,
                params={"id": match_id},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                fdata = await resp.json()

            resp_list = fdata.get("response", [])
            if not resp_list:
                continue
            fix    = resp_list[0]
            status = fix["fixture"]["status"]["short"]
            if status not in ("FT", "AET", "PEN"):
                continue

            home_score = fix["goals"]["home"] or 0
            away_score = fix["goals"]["away"] or 0
            home_name  = fix["teams"]["home"]["name"]
            away_name  = fix["teams"]["away"]["name"]

            # Resolve semua bet untuk match ini
            for bet_id, bet in data["bets"].items():
                if bet["match_id"] != match_id or bet["status"] != "pending":
                    continue

                hc   = bet["handicap"]
                pick = bet["pilihan"]

                # Terapkan handicap ke home
                adj_home = home_score + (hc if pick == "home" else -hc if pick == "away" else 0)
                adj_away = away_score

                if pick == "home":
                    adj_home = home_score + hc
                    win = adj_home > away_score
                elif pick == "away":
                    adj_away = away_score + (-hc)
                    win = adj_away > home_score
                else:  # draw
                    win = home_score == away_score

                # Setengah menang untuk .5 handicap di garis
                bayar = 0
                if win:
                    bayar = int(bet["nominal"] * bet["odds"])
                    bet["status"] = "win"
                else:
                    bet["status"] = "lose"

                # Tambah ke saldo
                uid = bet["user_id"]
                if uid not in data["users"]:
                    continue
                data["users"][uid]["saldo"] += bayar

                # Buat notif
                icon   = "✅ MENANG" if win else "❌ KALAH"
                result = f"{home_score}-{away_score}"
                notifs.append({
                    "user_id":    uid,
                    "channel_id": None,
                    "text": (
                        f"🎰 {icon} | **{home_name} vs {away_name}** ({result})\n"
                        f"Taruhan: {pick.upper()} · {fmt_rp(bet['nominal'])}\n"
                        f"{'Menang: +' + fmt_rp(bayar) if win else 'Kalah: -' + fmt_rp(bet['nominal'])}"
                    ),
                })

    return notifs


def fmt_rp(n: int) -> str:
    return f"Rp {n:,}".replace(",", ".")
