"""
IDX Stock Discord Bot
Deploy-ready untuk Railway.app
"""

import os
import io
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import numpy as np

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN", "")

# ─── In-memory State ─────────────────────────────────────────────────────────
# custom_mas[guild_id][ticker] = [{"type": "EMA", "period": 20}, ...]
custom_mas: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

# alerts[guild_id] = [{"ticker": "BBCA.JK", "price": 9000, "direction": "above", "channel_id": int}, ...]
alerts: dict[int, list[dict]] = defaultdict(list)

# ─── Helpers ─────────────────────────────────────────────────────────────────
def to_jk(ticker: str) -> str:
    t = ticker.upper().strip()
    return t if t.endswith(".JK") else f"{t}.JK"


def calc_ma(series, period: int, ma_type: str):
    if ma_type.upper() == "EMA":
        return series.ewm(span=period, adjust=False).mean()
    return series.rolling(window=period).mean()  # SMA


MA_COLORS = {
    "EMA20":  "#FFD700",
    "EMA50":  "#FF8C00",
    "SMA50":  "#00BFFF",
    "SMA200": "#FF69B4",
}

TIMEFRAME_MAP = {
    "3m":  ("5d",  "15m"),   # (yf period, yf interval)
    "30m": ("1mo", "90m"),
    "1d":  ("6mo", "1d"),
    "1w":  ("2y",  "1wk"),
}

# ─── Chart Builder ───────────────────────────────────────────────────────────
def build_chart(ticker: str, timeframe: str, extra_mas: list[dict]) -> io.BytesIO:
    period, interval = TIMEFRAME_MAP[timeframe]
    df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)

    if df is None or df.empty:
        raise ValueError(f"Tidak ada data untuk {ticker}")

    df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index

    close = df["Close"].squeeze()
    opens = df["Open"].squeeze()
    high  = df["High"].squeeze()
    low   = df["Low"].squeeze()
    vol   = df["Volume"].squeeze()

    # ── Default MAs ──────────────────────────────────────────────────────────
    default_mas = [
        {"type": "EMA", "period": 20,  "label": "EMA20",  "color": MA_COLORS["EMA20"]},
        {"type": "EMA", "period": 50,  "label": "EMA50",  "color": MA_COLORS["EMA50"]},
        {"type": "SMA", "period": 50,  "label": "SMA50",  "color": MA_COLORS["SMA50"]},
        {"type": "SMA", "period": 200, "label": "SMA200", "color": MA_COLORS["SMA200"]},
    ]
    for m in extra_mas:
        lbl = f"{m['type'].upper()}{m['period']}"
        default_mas.append({"type": m["type"], "period": m["period"], "label": lbl, "color": "#ADFF2F"})

    # ── Figure ────────────────────────────────────────────────────────────────
    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 8),
        gridspec_kw={"height_ratios": [3, 1]},
        facecolor="#0d1117",
    )
    for ax in (ax1, ax2):
        ax.set_facecolor("#0d1117")
        ax.tick_params(colors="#8b949e", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#30363d")

    # ── Candlesticks ─────────────────────────────────────────────────────────
    dates = np.arange(len(df))
    w = 0.4
    for i in dates:
        o, c, h, l = float(opens.iloc[i]), float(close.iloc[i]), float(high.iloc[i]), float(low.iloc[i])
        color = "#3fb950" if c >= o else "#f85149"
        ax1.plot([i, i], [l, h], color=color, linewidth=0.8)
        ax1.add_patch(Rectangle((i - w/2, min(o, c)), w, abs(c - o), color=color, zorder=2))

    # ── MAs ──────────────────────────────────────────────────────────────────
    for m in default_mas:
        if len(close) >= m["period"]:
            ma_vals = calc_ma(close, m["period"], m["type"])
            ax1.plot(dates, ma_vals.values, label=m["label"], color=m["color"], linewidth=1.2, zorder=3)

    ax1.legend(loc="upper left", fontsize=7, framealpha=0.3,
               facecolor="#161b22", edgecolor="#30363d", labelcolor="white")
    ax1.set_title(f"{ticker}  ·  {timeframe.upper()} Chart", color="white", fontsize=13, pad=10)
    ax1.set_xlim(-1, len(dates))
    ax1.yaxis.set_tick_params(labelright=True, labelleft=False)
    ax1.set_xticks([])

    # ── Volume bars ───────────────────────────────────────────────────────────
    vol_colors = ["#3fb950" if float(close.iloc[i]) >= float(opens.iloc[i]) else "#f85149" for i in dates]
    ax2.bar(dates, vol.values, color=vol_colors, width=0.8, alpha=0.7)
    ax2.set_xlim(-1, len(dates))
    ax2.set_ylabel("Volume", color="#8b949e", fontsize=8)
    ax2.yaxis.set_tick_params(labelright=True, labelleft=False)

    # ── X-axis labels (sampled) ───────────────────────────────────────────────
    step = max(1, len(dates) // 8)
    ax2.set_xticks(dates[::step])
    fmt = "%d %b" if timeframe in ("1d", "1w") else "%d/%m %H:%M"
    ax2.set_xticklabels(
        [df.index[i].strftime(fmt) for i in dates[::step]],
        rotation=30, ha="right", fontsize=7, color="#8b949e",
    )

    fig.tight_layout(pad=1.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="#0d1117")
    plt.close(fig)
    buf.seek(0)
    return buf


# ─── Bot Setup ───────────────────────────────────────────────────────────────
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        log.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        log.error(f"Sync error: {e}")
    check_alerts.start()


# ─── /price ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="price", description="Harga saham IDX saat ini")
@app_commands.describe(ticker="Kode saham (contoh: BBCA, TLKM)")
async def price_cmd(interaction: discord.Interaction, ticker: str):
    await interaction.response.defer()
    jk = to_jk(ticker)
    try:
        info  = yf.Ticker(jk).fast_info
        hist  = yf.download(jk, period="2d", interval="1d", progress=False, auto_adjust=True)

        if hist is None or hist.empty:
            await interaction.followup.send(f"❌ Data tidak ditemukan untuk **{jk}**.")
            return

        last   = float(hist["Close"].iloc[-1])
        prev   = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last
        chg    = last - prev
        chg_pct = (chg / prev * 100) if prev else 0
        vol    = int(hist["Volume"].iloc[-1])
        hi     = float(hist["High"].iloc[-1])
        lo     = float(hist["Low"].iloc[-1])

        sign   = "🟢" if chg >= 0 else "🔴"
        arrow  = "▲" if chg >= 0 else "▼"

        embed = discord.Embed(
            title=f"{sign} {jk}",
            color=0x3fb950 if chg >= 0 else 0xf85149,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="💰 Harga", value=f"Rp {last:,.0f}", inline=True)
        embed.add_field(name=f"{arrow} Perubahan", value=f"Rp {chg:+,.0f}  ({chg_pct:+.2f}%)", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=False)
        embed.add_field(name="📈 High", value=f"Rp {hi:,.0f}", inline=True)
        embed.add_field(name="📉 Low",  value=f"Rp {lo:,.0f}", inline=True)
        embed.add_field(name="📊 Volume", value=f"{vol:,}", inline=True)
        embed.set_footer(text="Data via yfinance · IDX")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        log.exception(e)
        await interaction.followup.send(f"❌ Error saat mengambil data **{jk}**: `{e}`")


# ─── /chart ──────────────────────────────────────────────────────────────────
TF_CHOICES = [
    app_commands.Choice(name="3 Menit  (candle 15m, 5 hari)",   value="3m"),
    app_commands.Choice(name="30 Menit (candle 90m, 1 bulan)",  value="30m"),
    app_commands.Choice(name="1 Hari   (candle 1d,  6 bulan)",  value="1d"),
    app_commands.Choice(name="1 Minggu (candle 1wk, 2 tahun)",  value="1w"),
]

@bot.tree.command(name="chart", description="Candlestick chart + MA untuk saham IDX")
@app_commands.describe(
    ticker="Kode saham (contoh: BBCA)",
    timeframe="Pilih timeframe",
)
@app_commands.choices(timeframe=TF_CHOICES)
async def chart_cmd(interaction: discord.Interaction, ticker: str, timeframe: app_commands.Choice[str]):
    await interaction.response.defer()
    jk = to_jk(ticker)
    guild_id = interaction.guild_id or 0
    extra = custom_mas[guild_id].get(jk, [])

    try:
        buf = await asyncio.get_event_loop().run_in_executor(
            None, build_chart, jk, timeframe.value, extra
        )
        file = discord.File(buf, filename=f"{jk}_{timeframe.value}.png")
        await interaction.followup.send(
            content=f"📊 **{jk}** — Timeframe `{timeframe.name}`",
            file=file,
        )
    except Exception as e:
        log.exception(e)
        await interaction.followup.send(f"❌ Gagal membuat chart **{jk}**: `{e}`")


# ─── /addma ──────────────────────────────────────────────────────────────────
MA_TYPE_CHOICES = [
    app_commands.Choice(name="SMA", value="SMA"),
    app_commands.Choice(name="EMA", value="EMA"),
]

@bot.tree.command(name="addma", description="Tambah MA custom ke chart")
@app_commands.describe(
    ticker="Kode saham (contoh: BBCA)",
    ma_type="Tipe moving average",
    period="Periode (contoh: 13, 89, 144)",
)
@app_commands.choices(ma_type=MA_TYPE_CHOICES)
async def addma_cmd(
    interaction: discord.Interaction,
    ticker: str,
    ma_type: app_commands.Choice[str],
    period: int,
):
    if period < 2 or period > 500:
        await interaction.response.send_message("❌ Period harus antara 2–500.", ephemeral=True)
        return

    jk = to_jk(ticker)
    guild_id = interaction.guild_id or 0
    existing = custom_mas[guild_id][jk]

    # cek duplikat
    for m in existing:
        if m["type"].upper() == ma_type.value and m["period"] == period:
            await interaction.response.send_message(
                f"⚠️ **{ma_type.value}{period}** sudah ada di {jk}.", ephemeral=True
            )
            return

    existing.append({"type": ma_type.value, "period": period})
    await interaction.response.send_message(
        f"✅ Berhasil tambah **{ma_type.value}{period}** ke `{jk}`.\n"
        f"Jalankan `/chart {ticker}` untuk melihat hasilnya."
    )


# ─── /alert ──────────────────────────────────────────────────────────────────
DIR_CHOICES = [
    app_commands.Choice(name="Di atas (above)", value="above"),
    app_commands.Choice(name="Di bawah (below)", value="below"),
]

@bot.tree.command(name="alert", description="Set alert harga saham")
@app_commands.describe(
    ticker="Kode saham (contoh: BBCA)",
    harga="Target harga (Rupiah)",
    direction="Notif ketika harga di atas atau di bawah target",
)
@app_commands.choices(direction=DIR_CHOICES)
async def alert_cmd(
    interaction: discord.Interaction,
    ticker: str,
    harga: float,
    direction: app_commands.Choice[str],
):
    jk = to_jk(ticker)
    guild_id = interaction.guild_id or 0
    alerts[guild_id].append({
        "ticker":     jk,
        "price":      harga,
        "direction":  direction.value,
        "channel_id": interaction.channel_id,
        "user_id":    interaction.user.id,
    })
    dir_text = "📈 naik di atas" if direction.value == "above" else "📉 turun di bawah"
    await interaction.response.send_message(
        f"🔔 Alert diset! Kamu akan mendapat notifikasi saat **{jk}** "
        f"{dir_text} **Rp {harga:,.0f}**."
    )


# ─── /foreignflow ─────────────────────────────────────────────────────────────
@bot.tree.command(name="foreignflow", description="Data foreign net buy/sell (estimasi dari yfinance)")
@app_commands.describe(ticker="Kode saham opsional (kosongkan untuk top movers)")
async def foreignflow_cmd(interaction: discord.Interaction, ticker: str = ""):
    await interaction.response.defer()

    if ticker:
        jk = to_jk(ticker)
        tickers_to_check = [jk]
    else:
        # Top 5 saham IDX by market cap sebagai proxy
        tickers_to_check = ["BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK"]

    embed = discord.Embed(
        title="🌐 Foreign Flow (Estimasi)",
        description=(
            "⚠️ yfinance tidak menyediakan data foreign flow resmi IDX.\n"
            "Data di bawah adalah **harga & volume** sebagai proxy aktivitas.\n"
            "Untuk data resmi gunakan: [IDX Foreign Net](https://www.idx.co.id/en/market-data/statistics/)"
        ),
        color=0x58a6ff,
        timestamp=datetime.utcnow(),
    )

    for jk in tickers_to_check:
        try:
            hist = yf.download(jk, period="5d", interval="1d", progress=False, auto_adjust=True)
            if hist is None or hist.empty:
                continue
            close = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
            vol   = int(hist["Volume"].iloc[-1])
            chg   = (close - prev) / prev * 100 if prev else 0
            sign  = "🟢" if chg >= 0 else "🔴"
            embed.add_field(
                name=f"{sign} {jk}",
                value=f"Rp {close:,.0f}  ({chg:+.2f}%)\nVol: {vol:,}",
                inline=True,
            )
        except Exception:
            continue

    embed.set_footer(text="Data via yfinance · Bukan data official IDX")
    await interaction.followup.send(embed=embed)


# ─── Alert Background Task ────────────────────────────────────────────────────
@tasks.loop(minutes=5)
async def check_alerts():
    for guild_id, guild_alerts in list(alerts.items()):
        triggered = []
        for alert in guild_alerts:
            try:
                hist = yf.download(alert["ticker"], period="1d", interval="1m", progress=False, auto_adjust=True)
                if hist is None or hist.empty:
                    continue
                current = float(hist["Close"].iloc[-1])
                hit = (
                    (alert["direction"] == "above" and current >= alert["price"]) or
                    (alert["direction"] == "below" and current <= alert["price"])
                )
                if hit:
                    channel = bot.get_channel(alert["channel_id"])
                    if channel:
                        dir_text = "naik melewati" if alert["direction"] == "above" else "turun ke bawah"
                        await channel.send(
                            f"🔔 <@{alert['user_id']}> **{alert['ticker']}** "
                            f"{dir_text} Rp {alert['price']:,.0f}!\n"
                            f"Harga saat ini: **Rp {current:,.0f}**"
                        )
                    triggered.append(alert)
            except Exception as e:
                log.warning(f"Alert check error: {e}")

        for t in triggered:
            guild_alerts.remove(t)


@check_alerts.before_loop
async def before_check():
    await bot.wait_until_ready()


# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN environment variable tidak diset!")
    bot.run(TOKEN, log_handler=None)
