"""
trading.py — Paper Trading IDX
Modul untuk simulasi trading saham dengan harga real yfinance
"""

import json
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

import yfinance as yf

WIB      = timezone(timedelta(hours=7))
LOT_SIZE = 100  # 1 lot = 100 lembar

# ─── Storage (shared dengan gambling.py) ──────────────────────────────────────
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
            "saldo":       1_000_000,
            "last_daily":  None,
            "last_weekly": None,
            "last_work":   None,
            "portfolio":   {},   # {"BBCA.JK": {"lot": 5, "avg_price": 9100}}
            "trade_history": [],
        }
    u = data["users"][uid]
    if "portfolio"     not in u: u["portfolio"]     = {}
    if "trade_history" not in u: u["trade_history"] = []
    return u

def fmt(n) -> str:
    return f"Rp {int(n):,}".replace(",", ".")

def to_jk(ticker: str) -> str:
    t = ticker.upper().strip()
    return t if t.endswith(".JK") else f"{t}.JK"

# ─── Fetch harga real-time ────────────────────────────────────────────────────
def get_price(ticker: str) -> float:
    """Ambil harga terakhir dari yfinance (delay ~15 menit)."""
    hist = yf.download(ticker, period="1d", interval="1m",
                       progress=False, auto_adjust=True)
    if hist is None or hist.empty:
        raise ValueError(f"Tidak ada data untuk {ticker}")
    close = hist["Close"]
    if hasattr(close.columns if hasattr(close, 'columns') else None, '__len__'):
        close = close.iloc[:, 0]
    val = close.iloc[-1]
    if hasattr(val, 'iloc'):
        val = val.iloc[0]
    return float(val)

def get_portfolio_value(portfolio: dict) -> tuple[float, list]:
    """
    Hitung total nilai portofolio + unrealized P&L.
    Return (total_value, details)
    """
    total  = 0.0
    detail = []
    for ticker, pos in portfolio.items():
        if pos["lot"] <= 0:
            continue
        try:
            price   = get_price(ticker)
            lot     = pos["lot"]
            avg     = pos["avg_price"]
            val     = price * lot * LOT_SIZE
            cost    = avg   * lot * LOT_SIZE
            unreal  = val - cost
            pct     = (unreal / cost * 100) if cost else 0
            total  += val
            detail.append({
                "ticker":    ticker,
                "lot":       lot,
                "avg_price": avg,
                "cur_price": price,
                "value":     val,
                "unrealized": unreal,
                "pct":       pct,
            })
        except Exception:
            pass
    return total, detail

# ─── Setup commands ───────────────────────────────────────────────────────────
def setup_trading(bot: commands.Bot):

    @bot.tree.command(name="buy", description="Beli saham IDX (paper trading)")
    @app_commands.describe(
        ticker="Kode saham (contoh: BBCA)",
        lot="Jumlah lot (1 lot = 100 lembar)",
    )
    async def buy_cmd(interaction: discord.Interaction, ticker: str, lot: int):
        await interaction.response.defer()
        if lot < 1:
            await interaction.followup.send("❌ Minimal 1 lot.", ephemeral=True)
            return

        jk   = to_jk(ticker)
        data = load_data()
        u    = get_user(data, interaction.user.id)

        try:
            price = await asyncio.get_event_loop().run_in_executor(
                None, get_price, jk)
        except Exception as e:
            await interaction.followup.send(f"❌ Gagal ambil harga **{jk}**: `{e}`")
            return

        total_cost = price * lot * LOT_SIZE

        if u["saldo"] < total_cost:
            await interaction.followup.send(
                f"❌ Saldo tidak cukup!\n"
                f"Butuh: **{fmt(total_cost)}**\n"
                f"Saldo: **{fmt(u['saldo'])}**")
            return

        # Kurangi saldo
        u["saldo"] -= total_cost

        # Update portfolio (average down/up)
        port = u["portfolio"]
        if jk in port and port[jk]["lot"] > 0:
            old_lot   = port[jk]["lot"]
            old_avg   = port[jk]["avg_price"]
            new_lot   = old_lot + lot
            new_avg   = ((old_avg * old_lot) + (price * lot)) / new_lot
            port[jk]  = {"lot": new_lot, "avg_price": new_avg}
        else:
            port[jk]  = {"lot": lot, "avg_price": price}

        # Catat history
        u["trade_history"].append({
            "type":   "buy",
            "ticker": jk,
            "lot":    lot,
            "price":  price,
            "total":  total_cost,
            "time":   datetime.now(WIB).isoformat(),
        })
        save_data(data)

        embed = discord.Embed(title="✅ Beli Berhasil", color=0x3fb950)
        embed.add_field(name="Saham",   value=jk,              inline=True)
        embed.add_field(name="Lot",     value=f"{lot} lot",    inline=True)
        embed.add_field(name="Harga",   value=fmt(price),      inline=True)
        embed.add_field(name="Total",   value=fmt(total_cost), inline=True)
        embed.add_field(name="Avg Beli",value=fmt(port[jk]["avg_price"]), inline=True)
        embed.add_field(name="Saldo",   value=fmt(u["saldo"]), inline=True)
        embed.set_footer(text="Harga delay ~15 menit · Paper Trading")
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="sell", description="Jual saham IDX (paper trading)")
    @app_commands.describe(
        ticker="Kode saham (contoh: BBCA)",
        lot="Jumlah lot yang dijual (0 = jual semua)",
    )
    async def sell_cmd(interaction: discord.Interaction, ticker: str, lot: int):
        await interaction.response.defer()
        jk   = to_jk(ticker)
        data = load_data()
        u    = get_user(data, interaction.user.id)
        port = u["portfolio"]

        if jk not in port or port[jk]["lot"] <= 0:
            await interaction.followup.send(
                f"❌ Kamu tidak punya saham **{jk}**.", ephemeral=True)
            return

        owned = port[jk]["lot"]
        if lot == 0:
            lot = owned  # jual semua
        if lot > owned:
            await interaction.followup.send(
                f"❌ Lot tidak cukup! Punya **{owned} lot**.", ephemeral=True)
            return

        try:
            price = await asyncio.get_event_loop().run_in_executor(
                None, get_price, jk)
        except Exception as e:
            await interaction.followup.send(f"❌ Gagal ambil harga **{jk}**: `{e}`")
            return

        avg_price   = port[jk]["avg_price"]
        total_sell  = price * lot * LOT_SIZE
        cost        = avg_price * lot * LOT_SIZE
        realized_pl = total_sell - cost
        pct         = (realized_pl / cost * 100) if cost else 0

        # Update saldo & portfolio
        u["saldo"]      += total_sell
        port[jk]["lot"] -= lot
        if port[jk]["lot"] <= 0:
            del port[jk]

        u["trade_history"].append({
            "type":       "sell",
            "ticker":     jk,
            "lot":        lot,
            "price":      price,
            "total":      total_sell,
            "realized_pl": realized_pl,
            "time":       datetime.now(WIB).isoformat(),
        })
        save_data(data)

        color = 0x3fb950 if realized_pl >= 0 else 0xf85149
        icon  = "📈" if realized_pl >= 0 else "📉"
        embed = discord.Embed(title=f"{icon} Jual Berhasil", color=color)
        embed.add_field(name="Saham",        value=jk,              inline=True)
        embed.add_field(name="Lot",          value=f"{lot} lot",    inline=True)
        embed.add_field(name="Harga Jual",   value=fmt(price),      inline=True)
        embed.add_field(name="Total",        value=fmt(total_sell), inline=True)
        embed.add_field(name="Avg Beli",     value=fmt(avg_price),  inline=True)
        sign = "+" if realized_pl >= 0 else ""
        embed.add_field(
            name="Realized P&L",
            value=f"{sign}{fmt(realized_pl)} ({sign}{pct:.2f}%)",
            inline=True)
        embed.add_field(name="Saldo",        value=fmt(u["saldo"]), inline=True)
        embed.set_footer(text="Harga delay ~15 menit · Paper Trading")
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="portfolio", description="Lihat portofolio saham kamu")
    async def portfolio_cmd(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        data = load_data()
        u    = get_user(data, interaction.user.id)
        port = u["portfolio"]

        if not port:
            await interaction.followup.send(
                "📭 Portofolio kosong. Gunakan `/buy` untuk mulai trading!")
            return

        total_val, details = await asyncio.get_event_loop().run_in_executor(
            None, get_portfolio_value, port)

        total_cost   = sum(d["avg_price"] * d["lot"] * LOT_SIZE for d in details)
        total_unreal = total_val - total_cost
        total_pct    = (total_unreal / total_cost * 100) if total_cost else 0
        equity       = u["saldo"] + total_val

        color = 0x3fb950 if total_unreal >= 0 else 0xf85149
        embed = discord.Embed(
            title=f"📊 Portofolio {interaction.user.display_name}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )

        for d in details:
            sign = "+" if d["unrealized"] >= 0 else ""
            icon = "🟢" if d["unrealized"] >= 0 else "🔴"
            embed.add_field(
                name=f"{icon} {d['ticker']}",
                value=(
                    f"{d['lot']} lot · Avg {fmt(d['avg_price'])}\n"
                    f"Now {fmt(d['cur_price'])} · {fmt(d['value'])}\n"
                    f"P&L: {sign}{fmt(d['unrealized'])} ({sign}{d['pct']:.2f}%)"
                ),
                inline=False,
            )

        sign = "+" if total_unreal >= 0 else ""
        embed.add_field(name="💰 Kas",           value=fmt(u["saldo"]),   inline=True)
        embed.add_field(name="📈 Nilai Saham",   value=fmt(total_val),    inline=True)
        embed.add_field(name="💼 Total Ekuitas", value=fmt(equity),       inline=True)
        embed.add_field(
            name="📊 Unrealized P&L",
            value=f"{sign}{fmt(total_unreal)} ({sign}{total_pct:.2f}%)",
            inline=False)
        embed.set_footer(text="Harga delay ~15 menit · Paper Trading")
        await interaction.followup.send(embed=embed)

    # Leaderboard choices
    LB_CHOICES = [
        app_commands.Choice(name="Hari ini",  value="daily"),
        app_commands.Choice(name="Minggu ini", value="weekly"),
        app_commands.Choice(name="Bulan ini",  value="monthly"),
    ]

    @bot.tree.command(name="leaderboard", description="Ranking paper trader terbaik")
    @app_commands.describe(period="Periode leaderboard")
    @app_commands.choices(period=LB_CHOICES)
    async def leaderboard_cmd(
        interaction: discord.Interaction,
        period: app_commands.Choice[str],
    ):
        await interaction.response.defer(thinking=True)
        data = load_data()

        now = datetime.now(WIB)
        if period.value == "daily":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period.value == "weekly":
            cutoff = now - timedelta(days=now.weekday())
            cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
        else:  # monthly
            cutoff = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Hitung realized P&L per user dalam periode
        scores = []
        for uid, u in data["users"].items():
            realized = 0.0
            for trade in u.get("trade_history", []):
                if trade["type"] != "sell":
                    continue
                try:
                    t = datetime.fromisoformat(trade["time"])
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=WIB)
                    if t >= cutoff:
                        realized += trade.get("realized_pl", 0)
                except Exception:
                    pass

            # Tambah unrealized P&L untuk ranking lebih fair
            port     = u.get("portfolio", {})
            _, dets  = get_portfolio_value(port) if port else (0, [])
            unrealized = sum(d["unrealized"] for d in dets)

            total_pl = realized + unrealized
            if realized != 0 or unrealized != 0:
                scores.append((uid, total_pl, realized, unrealized))

        scores.sort(key=lambda x: x[1], reverse=True)

        period_labels = {
            "daily": "Hari Ini", "weekly": "Minggu Ini", "monthly": "Bulan Ini"
        }
        embed = discord.Embed(
            title=f"🏆 Leaderboard Paper Trading — {period_labels[period.value]}",
            color=0xf9a825,
            timestamp=datetime.now(timezone.utc),
        )

        if not scores:
            embed.description = "Belum ada transaksi dalam periode ini."
        else:
            medals = ["🥇", "🥈", "🥉"]
            desc   = ""
            for i, (uid, total, realized, unreal) in enumerate(scores[:10]):
                try:
                    user = await interaction.client.fetch_user(int(uid))
                    name = user.display_name
                except Exception:
                    name = f"User {uid[:6]}"
                medal = medals[i] if i < 3 else f"**{i+1}.**"
                sign  = "+" if total >= 0 else ""
                desc += f"{medal} **{name}** — {sign}{fmt(total)}\n"
                desc += f"   Realized: {fmt(realized)} · Unrealized: {fmt(unreal)}\n"
            embed.description = desc

        embed.set_footer(text=f"P&L = Realized + Unrealized · {period.name}")
        await interaction.followup.send(embed=embed)

    @bot.tree.command(name="history", description="Lihat riwayat trading kamu")
    async def history_cmd(interaction: discord.Interaction):
        data    = load_data()
        u       = get_user(data, interaction.user.id)
        history = u.get("trade_history", [])[-10:]  # 10 terakhir

        if not history:
            await interaction.response.send_message(
                "📭 Belum ada riwayat trading.", ephemeral=True)
            return

        embed = discord.Embed(title="📋 Riwayat Trading (10 Terakhir)", color=0x58a6ff)
        for t in reversed(history):
            icon   = "🟢 BUY" if t["type"] == "buy" else "🔴 SELL"
            pl_str = ""
            if t["type"] == "sell":
                pl = t.get("realized_pl", 0)
                sign = "+" if pl >= 0 else ""
                pl_str = f" · P&L: {sign}{fmt(pl)}"
            try:
                dt  = datetime.fromisoformat(t["time"])
                dts = dt.strftime("%d/%m %H:%M")
            except Exception:
                dts = "-"
            embed.add_field(
                name=f"{icon} {t['ticker']} — {dts}",
                value=f"{t['lot']} lot @ {fmt(t['price'])}{pl_str}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
