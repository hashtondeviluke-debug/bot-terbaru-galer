"""
gambling.py — Modul Judi Bola + Ekonomi Discord Bot
"""

import json
import os
import random
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

# ─── Storage ─────────────────────────────────────────────────────────────────
DATA_FILE = Path("data.json")

def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {"users": {}, "bets": {}}

def save_data(data: dict):
    DATA_FILE.write_text(json.dumps(data, indent=2, default=str))

def get_user(data: dict, user_id: int) -> dict:
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "saldo": 1_000_000,  # mulai Rp 1jt
            "last_daily":  None,
            "last_weekly": None,
            "last_work":   None,
        }
    return data["users"][uid]

def fmt(n: int) -> str:
    return f"Rp {n:,}".replace(",", ".")

# ─── Helpers ─────────────────────────────────────────────────────────────────
WIB = timezone(timedelta(hours=7))

def now_wib() -> datetime:
    return datetime.now(WIB)

def cooldown_left(last_str: str | None, hours: int) -> int:
    """Return sisa detik cooldown, 0 kalau sudah bisa."""
    if not last_str:
        return 0
    last = datetime.fromisoformat(last_str)
    if last.tzinfo is None:
        last = last.replace(tzinfo=WIB)
    delta = (last + timedelta(hours=hours)) - now_wib()
    return max(0, int(delta.total_seconds()))

def fmt_cd(secs: int) -> str:
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    parts = []
    if h: parts.append(f"{h}j")
    if m: parts.append(f"{m}m")
    if s: parts.append(f"{s}d")
    return " ".join(parts) or "0d"

# ─── Commands Ekonomi ─────────────────────────────────────────────────────────
def setup_economy(bot: commands.Bot):

    @bot.tree.command(name="saldo", description="Cek saldo kamu")
    async def saldo_cmd(interaction: discord.Interaction):
        data = load_data()
        u    = get_user(data, interaction.user.id)
        save_data(data)
        color = 0x3fb950 if u["saldo"] >= 0 else 0xf85149
        embed = discord.Embed(title="💰 Saldo Kamu", color=color)
        embed.add_field(name="Saldo", value=fmt(u["saldo"]))
        embed.set_footer(text=f"{interaction.user.display_name}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="daily", description="Ambil uang harian Rp 500.000")
    async def daily_cmd(interaction: discord.Interaction):
        data = load_data()
        u    = get_user(data, interaction.user.id)
        cd   = cooldown_left(u["last_daily"], 24)
        if cd > 0:
            await interaction.response.send_message(
                f"⏳ Daily bisa diambil lagi dalam **{fmt_cd(cd)}**.", ephemeral=True)
            return
        amount = 500_000
        u["saldo"] += amount
        u["last_daily"] = now_wib().isoformat()
        save_data(data)
        await interaction.response.send_message(
            f"✅ Kamu dapat **{fmt(amount)}** dari daily!\n💰 Saldo: **{fmt(u['saldo'])}**")

    @bot.tree.command(name="weekly", description="Ambil uang mingguan Rp 2.000.000")
    async def weekly_cmd(interaction: discord.Interaction):
        data = load_data()
        u    = get_user(data, interaction.user.id)
        cd   = cooldown_left(u["last_weekly"], 168)
        if cd > 0:
            await interaction.response.send_message(
                f"⏳ Weekly bisa diambil lagi dalam **{fmt_cd(cd)}**.", ephemeral=True)
            return
        amount = 2_000_000
        u["saldo"] += amount
        u["last_weekly"] = now_wib().isoformat()
        save_data(data)
        await interaction.response.send_message(
            f"✅ Kamu dapat **{fmt(amount)}** dari weekly!\n💰 Saldo: **{fmt(u['saldo'])}**")

    @bot.tree.command(name="work", description="Kerja dan dapat Rp 50.000 - 200.000")
    async def work_cmd(interaction: discord.Interaction):
        data = load_data()
        u    = get_user(data, interaction.user.id)
        cd   = cooldown_left(u["last_work"], 1)
        if cd > 0:
            await interaction.response.send_message(
                f"⏳ Kerja lagi dalam **{fmt_cd(cd)}**.", ephemeral=True)
            return
        jobs = [
            ("🛵 Ojek online", 50_000, 120_000),
            ("☕ Barista", 60_000, 130_000),
            ("📦 Kurir", 70_000, 150_000),
            ("💻 Freelance", 80_000, 200_000),
            ("🧹 Cleaning service", 50_000, 100_000),
        ]
        job, lo, hi = random.choice(jobs)
        amount = random.randint(lo, hi)
        u["saldo"] += amount
        u["last_work"] = now_wib().isoformat()
        save_data(data)
        await interaction.response.send_message(
            f"{job} — Kamu dapat **{fmt(amount)}**!\n💰 Saldo: **{fmt(u['saldo'])}**")

    @bot.tree.command(name="maling", description="Coba curi duit (berisiko ketangkep!)")
    async def maling_cmd(interaction: discord.Interaction):
        data = load_data()
        u    = get_user(data, interaction.user.id)
        cd   = cooldown_left(u.get("last_maling"), 2)
        if cd > 0:
            await interaction.response.send_message(
                f"⏳ Tunggu **{fmt_cd(cd)}** sebelum maling lagi.", ephemeral=True)
            return
        u["last_maling"] = now_wib().isoformat()
        if random.random() < 0.4:  # 40% ketangkep
            denda = random.randint(200_000, 500_000)
            u["saldo"] -= denda
            save_data(data)
            await interaction.response.send_message(
                f"🚔 **KETANGKEP POLISI!** Kamu didenda **{fmt(denda)}**!\n"
                f"💰 Saldo: **{fmt(u['saldo'])}**")
        else:
            hasil = random.randint(100_000, 500_000)
            u["saldo"] += hasil
            save_data(data)
            scenarios = [
                f"🏃 Kamu berhasil gasak dompet orang di pasar! +**{fmt(hasil)}**",
                f"🏪 Minimarket kecolongan! Kamu kabur bawa **{fmt(hasil)}**",
                f"🛵 Jambret berhasil! Dapat **{fmt(hasil)}**",
            ]
            await interaction.response.send_message(
                f"{random.choice(scenarios)}\n💰 Saldo: **{fmt(u['saldo'])}**")

    @bot.tree.command(name="jualdiri", description="Jual diri (berisiko drama!)")
    async def jualdiri_cmd(interaction: discord.Interaction):
        data = load_data()
        u    = get_user(data, interaction.user.id)
        cd   = cooldown_left(u.get("last_jualdiri"), 3)
        if cd > 0:
            await interaction.response.send_message(
                f"⏳ Istirahat dulu **{fmt_cd(cd)}**.", ephemeral=True)
            return
        u["last_jualdiri"] = now_wib().isoformat()
        if random.random() < 0.3:  # 30% drama
            rugi = random.randint(50_000, 200_000)
            u["saldo"] -= rugi
            save_data(data)
            dramas = [
                f"😭 Klien kabur gak bayar! Rugi **{fmt(rugi)}**",
                f"💔 Tiba-tiba bucin gratisin. Rugi **{fmt(rugi)}**",
                f"🚨 Ketahuan pasangan, bayar 'uang damai' **{fmt(rugi)}**",
            ]
            await interaction.response.send_message(
                f"{random.choice(dramas)}\n💰 Saldo: **{fmt(u['saldo'])}**")
        else:
            hasil = random.randint(200_000, 800_000)
            u["saldo"] += hasil
            save_data(data)
            await interaction.response.send_message(
                f"💅 Bisnis lancar! Dapat **{fmt(hasil)}**\n"
                f"💰 Saldo: **{fmt(u['saldo'])}**")

    @bot.tree.command(name="rampok", description="Rampok saldo user lain (50% gagal!)")
    @app_commands.describe(target="User yang mau dirampok")
    async def rampok_cmd(interaction: discord.Interaction, target: discord.Member):
        if target.id == interaction.user.id:
            await interaction.response.send_message("❌ Gak bisa rampok diri sendiri.", ephemeral=True)
            return
        if target.bot:
            await interaction.response.send_message("❌ Bot tidak punya duit.", ephemeral=True)
            return
        data     = load_data()
        attacker = get_user(data, interaction.user.id)
        victim   = get_user(data, target.id)
        cd       = cooldown_left(attacker.get("last_rampok"), 4)
        if cd > 0:
            await interaction.response.send_message(
                f"⏳ Tunggu **{fmt_cd(cd)}** sebelum rampok lagi.", ephemeral=True)
            return
        attacker["last_rampok"] = now_wib().isoformat()
        if random.random() < 0.5:  # 50% gagal
            denda = random.randint(100_000, 300_000)
            attacker["saldo"] -= denda
            save_data(data)
            await interaction.response.send_message(
                f"🚔 Rampok **{target.display_name}** GAGAL! Kamu malah kena gebuk dan rugi **{fmt(denda)}**!\n"
                f"💰 Saldo kamu: **{fmt(attacker['saldo'])}**")
        else:
            steal = int(victim["saldo"] * 0.20)
            steal = max(steal, 10_000)
            victim["saldo"]   -= steal
            attacker["saldo"] += steal
            save_data(data)
            await interaction.response.send_message(
                f"🔫 Berhasil rampok **{target.display_name}**! Dapat **{fmt(steal)}**!\n"
                f"💰 Saldo kamu: **{fmt(attacker['saldo'])}**")


# ─── Commands Judi Bola ───────────────────────────────────────────────────────
def setup_betting(bot: commands.Bot):

    LEAGUE_MAP = {
        "world_cup": "🏆 World Cup 2026",
        "epl":       "🏴󠁧󠁢󠁥󠁮󠁧󠁿 EPL",
        "la_liga":   "🇪🇸 La Liga",
    }

    HANDICAP_CHOICES = [
        app_commands.Choice(name="0 (Even)",      value="0"),
        app_commands.Choice(name="-0.5",          value="-0.5"),
        app_commands.Choice(name="+0.5",          value="+0.5"),
        app_commands.Choice(name="-1",            value="-1"),
        app_commands.Choice(name="+1",            value="+1"),
        app_commands.Choice(name="-1.5",          value="-1.5"),
        app_commands.Choice(name="+1.5",          value="+1.5"),
    ]

    LEAGUE_CHOICES = [
        app_commands.Choice(name="🏆 World Cup 2026", value="world_cup"),
        app_commands.Choice(name="🏴󠁧󠁢󠁥󠁮󠁧󠁿 EPL",           value="epl"),
        app_commands.Choice(name="🇪🇸 La Liga",       value="la_liga"),
    ]

    @bot.tree.command(name="matches", description="Lihat pertandingan hari ini untuk judi bola")
    @app_commands.describe(liga="Pilih liga")
    @app_commands.choices(liga=LEAGUE_CHOICES)
    async def matches_cmd(interaction: discord.Interaction, liga: app_commands.Choice[str]):
        await interaction.response.defer()
        try:
            from fetch_sports import fetch_sports_data
            matches = await fetch_sports_data(liga.value)
        except Exception as e:
            await interaction.followup.send(f"❌ Gagal fetch jadwal: `{e}`")
            return

        if not matches:
            await interaction.followup.send(
                f"📭 Tidak ada pertandingan hari ini untuk **{liga.name}**.")
            return

        embed = discord.Embed(
            title=f"{LEAGUE_MAP[liga.value]} — Pertandingan Hari Ini",
            color=0xf9a825,
            timestamp=datetime.now(timezone.utc),
        )
        for m in matches[:10]:
            status = m.get("status", "")
            score  = f"{m.get('home_score','?')} - {m.get('away_score','?')}" if m.get("home_score") is not None else "vs"
            val    = (
                f"🆔 `{m['id']}`\n"
                f"⏰ {m.get('time','TBD')} WIB\n"
                f"📊 {score}  |  {status}\n"
                f"Odds: 🏠{m.get('odd_home','?')} · 🤝{m.get('odd_draw','?')} · ✈️{m.get('odd_away','?')}"
            )
            embed.add_field(name=f"⚽ {m['home']} vs {m['away']}", value=val, inline=False)

        embed.set_footer(text="Gunakan /bet <id> untuk pasang taruhan")
        await interaction.followup.send(embed=embed)

    PICK_CHOICES = [
        app_commands.Choice(name="🏠 Home (tim kandang)", value="home"),
        app_commands.Choice(name="🤝 Draw (seri)",       value="draw"),
        app_commands.Choice(name="✈️ Away (tim tamu)",   value="away"),
    ]

    @bot.tree.command(name="bet", description="Pasang taruhan bola")
    @app_commands.describe(
        match_id="ID pertandingan dari /matches",
        pilihan="Home / Draw / Away",
        handicap="Handicap untuk tim yang dipilih",
        nominal="Nominal taruhan (contoh: 100000)",
    )
    @app_commands.choices(pilihan=PICK_CHOICES, handicap=HANDICAP_CHOICES)
    async def bet_cmd(
        interaction: discord.Interaction,
        match_id:   str,
        pilihan:    app_commands.Choice[str],
        handicap:   app_commands.Choice[str],
        nominal:    int,
    ):
        if nominal < 10_000:
            await interaction.response.send_message("❌ Minimal taruhan Rp 10.000.", ephemeral=True)
            return

        data = load_data()
        u    = get_user(data, interaction.user.id)

        if u["saldo"] < nominal:
            await interaction.response.send_message(
                f"❌ Saldo tidak cukup! Saldo kamu: **{fmt(u['saldo'])}**", ephemeral=True)
            return

        # Fetch info match untuk validasi & odds
        try:
            from fetch_sports import get_match_by_id
            match = await get_match_by_id(match_id)
        except Exception as e:
            await interaction.response.send_message(f"❌ Match tidak ditemukan: `{e}`", ephemeral=True)
            return

        if not match:
            await interaction.response.send_message("❌ Match ID tidak valid.", ephemeral=True)
            return

        if match.get("status") not in ("scheduled", "not_started", ""):
            await interaction.response.send_message("❌ Pertandingan sudah dimulai/selesai.", ephemeral=True)
            return

        # Kurangi saldo
        u["saldo"] -= nominal

        # Simpan bet
        bet_id  = f"{interaction.user.id}_{match_id}_{int(datetime.now().timestamp())}"
        hc_val  = float(handicap.value)
        odds    = {
            "home": float(match.get("odd_home", 1.9)),
            "draw": float(match.get("odd_draw", 3.2)),
            "away": float(match.get("odd_away", 1.9)),
        }
        bet = {
            "bet_id":    bet_id,
            "user_id":   str(interaction.user.id),
            "match_id":  match_id,
            "home":      match["home"],
            "away":      match["away"],
            "pilihan":   pilihan.value,
            "handicap":  hc_val,
            "nominal":   nominal,
            "odds":      odds[pilihan.value],
            "status":    "pending",
            "placed_at": now_wib().isoformat(),
        }
        data["bets"][bet_id] = bet
        save_data(data)

        hc_str = f"+{hc_val}" if hc_val > 0 else str(hc_val)
        embed  = discord.Embed(title="🎰 Taruhan Dipasang!", color=0x3fb950)
        embed.add_field(name="Match",    value=f"{match['home']} vs {match['away']}", inline=False)
        embed.add_field(name="Pilihan",  value=f"{pilihan.name} (handicap {hc_str})",  inline=True)
        embed.add_field(name="Nominal",  value=fmt(nominal),                            inline=True)
        embed.add_field(name="Odds",     value=f"x{odds[pilihan.value]}",               inline=True)
        embed.add_field(name="Potensi Menang", value=fmt(int(nominal * odds[pilihan.value])), inline=True)
        embed.add_field(name="Saldo Tersisa",  value=fmt(u["saldo"]),                   inline=True)
        embed.set_footer(text=f"Bet ID: {bet_id}")
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="mybets", description="Lihat taruhan aktif kamu")
    async def mybets_cmd(interaction: discord.Interaction):
        data     = load_data()
        uid      = str(interaction.user.id)
        my_bets  = [b for b in data["bets"].values() if b["user_id"] == uid]
        pending  = [b for b in my_bets if b["status"] == "pending"]
        settled  = [b for b in my_bets if b["status"] != "pending"][-5:]  # 5 terakhir

        embed = discord.Embed(title="📋 Taruhan Kamu", color=0x58a6ff)

        if pending:
            txt = ""
            for b in pending:
                hc  = f"+{b['handicap']}" if b['handicap'] > 0 else str(b['handicap'])
                txt += f"⚽ **{b['home']} vs {b['away']}**\n"
                txt += f"   {b['pilihan'].upper()} {hc} · {fmt(b['nominal'])} · x{b['odds']}\n"
            embed.add_field(name="⏳ Pending", value=txt, inline=False)
        else:
            embed.add_field(name="⏳ Pending", value="Tidak ada taruhan aktif.", inline=False)

        if settled:
            txt = ""
            for b in settled:
                icon = "✅" if b["status"] == "win" else "❌"
                txt += f"{icon} {b['home']} vs {b['away']} — {b['pilihan'].upper()}\n"
            embed.add_field(name="📜 Riwayat", value=txt, inline=False)

        u = get_user(data, interaction.user.id)
        embed.set_footer(text=f"Saldo: {fmt(u['saldo'])}")
        await interaction.response.send_message(embed=embed, ephemeral=True)
