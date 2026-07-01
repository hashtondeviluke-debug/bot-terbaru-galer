"""
IDX Stock Discord Bot
Deploy-ready untuk Railway.app
"""

import os
import io
import asyncio
import logging
import base64
import re
from collections import defaultdict
from datetime import datetime, timedelta

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

from telethon import TelegramClient
from telethon.sessions import StringSession

import gambling
import trading

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────
TOKEN              = os.environ.get("DISCORD_TOKEN", "")
GEMINI_KEY         = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_API_ID    = int(os.environ.get("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH  = os.environ.get("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION   = os.environ.get("TELEGRAM_SESSION", "")   # StringSession
TELEGRAM_CHANNEL   = os.environ.get("TELEGRAM_CHANNEL", "tuntunsekuritas")

# Telethon client (shared, start saat bot ready)
tg_client: TelegramClient | None = None

# ─── In-memory State ─────────────────────────────────────────────────────────
custom_mas: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
alerts: dict[int, list[dict]] = defaultdict(list)

# ─── Helpers ─────────────────────────────────────────────────────────────────
def to_jk(ticker: str) -> str:
    t = ticker.upper().strip()
    return t if t.endswith(".JK") else f"{t}.JK"


def scalar(val) -> float:
    import pandas as pd
    if isinstance(val, pd.Series):
        val = val.iloc[0]
    return float(val)


def get_col(df, col: str):
    import pandas as pd
    if isinstance(df.columns, pd.MultiIndex):
        return df[col].iloc[:, 0]
    return df[col]


def calc_ma(series, period: int, ma_type: str):
    if ma_type.upper() == "EMA":
        return series.ewm(span=period, adjust=False).mean()
    return series.rolling(window=period).mean()


MA_COLORS = {
    "EMA20":  "#FFD700",
    "EMA50":  "#FF8C00",
    "SMA50":  "#00BFFF",
    "SMA200": "#FF69B4",
}

TIMEFRAME_MAP = {
    "3m":  ("5d",  "15m"),
    "30m": ("1mo", "90m"),
    "1d":  ("6mo", "1d"),
    "1w":  ("2y",  "1wk"),
}

# ─── Chart Builder ───────────────────────────────────────────────────────────
def build_chart(ticker: str, timeframe: str, extra_mas: list[dict]) -> io.BytesIO:
    period, interval = TIMEFRAME_MAP[timeframe]
    df = yf.download(ticker, period=period, interval=interval,
                     progress=False, auto_adjust=True)

    if df is None or df.empty:
        raise ValueError(f"Tidak ada data untuk {ticker}")

    df.index = df.index.tz_localize(None) if df.index.tzinfo else df.index

    close = get_col(df, "Close")
    opens = get_col(df, "Open")
    high  = get_col(df, "High")
    low   = get_col(df, "Low")
    vol   = get_col(df, "Volume")

    default_mas = [
        {"type": "EMA", "period": 20,  "label": "EMA20",  "color": MA_COLORS["EMA20"]},
        {"type": "EMA", "period": 50,  "label": "EMA50",  "color": MA_COLORS["EMA50"]},
        {"type": "SMA", "period": 50,  "label": "SMA50",  "color": MA_COLORS["SMA50"]},
        {"type": "SMA", "period": 200, "label": "SMA200", "color": MA_COLORS["SMA200"]},
    ]
    for m in extra_mas:
        lbl = f"{m['type'].upper()}{m['period']}"
        default_mas.append({"type": m["type"], "period": m["period"],
                             "label": lbl, "color": "#ADFF2F"})

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

    dates = np.arange(len(df))
    w = 0.4
    for i in dates:
        o = scalar(opens.iloc[i])
        c = scalar(close.iloc[i])
        h = scalar(high.iloc[i])
        l = scalar(low.iloc[i])
        color = "#3fb950" if c >= o else "#f85149"
        ax1.plot([i, i], [l, h], color=color, linewidth=0.8)
        ax1.add_patch(Rectangle((i - w/2, min(o, c)), w, abs(c - o),
                                 color=color, zorder=2))

    for m in default_mas:
        if len(close) >= m["period"]:
            ma_vals = calc_ma(close, m["period"], m["type"])
            ax1.plot(dates, ma_vals.values, label=m["label"],
                     color=m["color"], linewidth=1.2, zorder=3)

    ax1.legend(loc="upper left", fontsize=7, framealpha=0.3,
               facecolor="#161b22", edgecolor="#30363d", labelcolor="white")
    ax1.set_title(f"{ticker}  ·  {timeframe.upper()} Chart",
                  color="white", fontsize=13, pad=10)
    ax1.set_xlim(-1, len(dates))
    ax1.yaxis.set_tick_params(labelright=True, labelleft=False)
    ax1.set_xticks([])

    vol_colors = [
        "#3fb950" if scalar(close.iloc[i]) >= scalar(opens.iloc[i]) else "#f85149"
        for i in dates
    ]
    ax2.bar(dates, vol.values, color=vol_colors, width=0.8, alpha=0.7)
    ax2.set_xlim(-1, len(dates))
    ax2.set_ylabel("Volume", color="#8b949e", fontsize=8)
    ax2.yaxis.set_tick_params(labelright=True, labelleft=False)

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


# ─── Gemini Vision: Analisa Chart ────────────────────────────────────────────
ANALYZE_PROMPT = """Kamu analis teknikal IDX. Jawab dalam format ini PERSIS, setiap section 1 baris saja, tanpa penjelasan panjang:

📌 TICKER: [nama & timeframe]
📈 TREND: [Uptrend/Downtrend/Sideways - alasan 5 kata]
🔴 RESISTANCE: [level1, level2]
🟢 SUPPORT: [level1, level2]
⚡ SINYAL: [sinyal utama 1 kalimat]
🎯 REKOMENDASI: [Buy/Sell/Wait | Entry: X | TP: X | SL: X]
⚠️ Bukan saran investasi."""

async def analyze_chart_with_gemini(image_bytes: bytes, mime_type: str, extra_note: str = "") -> str:
    """Kirim gambar ke Gemini API dengan fallback ke model lain kalau 429."""
    if not GEMINI_KEY:
        return (
            "❌ `GEMINI_API_KEY` belum diset di environment variable Railway.\n"
            "Daftar gratis di: https://aistudio.google.com/app/apikey"
        )

    # Urutan fallback: model terbaik dulu, kalau limit lanjut ke berikutnya
    MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]

    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    prompt = ANALYZE_PROMPT + (f"\n\nCatatan dari user: {extra_note}" if extra_note else "")

    payload = {
        "contents": [
            {
                "parts": [
                    {"inline_data": {"mime_type": mime_type, "data": b64}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 2048,
            "temperature": 0.1,
        },
    }

    last_error = ""
    async with aiohttp.ClientSession() as session:
        for model in MODELS:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={GEMINI_KEY}"
            )
            try:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 429:
                        log.warning(f"Model {model} kena rate limit, coba model berikutnya...")
                        last_error = f"429 rate limit"
                        continue  # coba model berikutnya
                    if resp.status != 200:
                        err = await resp.text()
                        log.warning(f"Model {model} error {resp.status}, coba berikutnya...")
                        last_error = f"{resp.status}"
                        continue
                    data = await resp.json()
                    result = data["candidates"][0]["content"]["parts"][0]["text"]
                    log.info(f"Analisa berhasil pakai model: {model}")
                    return result
            except Exception as e:
                log.warning(f"Model {model} exception: {e}, coba berikutnya...")
                last_error = str(e)
                continue

    raise RuntimeError(f"Semua model Gemini kena limit atau error. Last error: {last_error}")


# ─── Bot Setup ───────────────────────────────────────────────────────────────
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    global tg_client
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")

    # Start Telethon client
    if TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_SESSION:
        try:
            tg_client = TelegramClient(
                StringSession(TELEGRAM_SESSION),
                TELEGRAM_API_ID,
                TELEGRAM_API_HASH,
            )
            await tg_client.start()
            log.info("✅ Telethon client connected")
        except Exception as e:
            log.error(f"❌ Telethon gagal connect: {e}")
            tg_client = None
    else:
        log.warning("⚠️ TELEGRAM_API_ID/HASH/SESSION tidak diset, /today tidak akan berfungsi")

    try:
        synced = await bot.tree.sync()
        log.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        log.error(f"Sync error: {e}")
    if not check_alerts.is_running():
        check_alerts.start()
    if not resolve_bets_task.is_running():
        resolve_bets_task.start()

    # Setup gambling & betting commands
    gambling.setup_economy(bot)
    gambling.setup_betting(bot)
    trading.setup_trading(bot)
    # Re-sync supaya command baru terdaftar
    try:
        synced2 = await bot.tree.sync()
        log.info(f"Re-synced {len(synced2)} slash commands (after gambling setup)")
    except Exception as e:
        log.error(f"Re-sync error: {e}")


@tasks.loop(minutes=10)
async def resolve_bets_task():
    """Auto-resolve taruhan yang sudah selesai tiap 10 menit."""
    try:
        from fetch_sports import resolve_bets
        from gambling import load_data, save_data
        data   = load_data()
        notifs = await resolve_bets(bot, data)
        if notifs:
            save_data(data)
            for n in notifs:
                uid = int(n["user_id"])
                try:
                    user = await bot.fetch_user(uid)
                    await user.send(n["text"])
                except Exception:
                    pass
    except Exception as e:
        log.warning(f"resolve_bets_task error: {e}")


@resolve_bets_task.before_loop
async def before_resolve():
    await bot.wait_until_ready()


# ─── /price ──────────────────────────────────────────────────────────────────
@bot.tree.command(name="price", description="Harga saham IDX saat ini")
@app_commands.describe(ticker="Kode saham (contoh: BBCA, TLKM)")
async def price_cmd(interaction: discord.Interaction, ticker: str):
    await interaction.response.defer()
    jk = to_jk(ticker)
    try:
        hist = yf.download(jk, period="5d", interval="1d",
                           progress=False, auto_adjust=True)

        if hist is None or hist.empty:
            await interaction.followup.send(f"❌ Data tidak ditemukan untuk **{jk}**.")
            return

        close_s = get_col(hist, "Close")
        high_s  = get_col(hist, "High")
        low_s   = get_col(hist, "Low")
        vol_s   = get_col(hist, "Volume")

        last    = scalar(close_s.iloc[-1])
        prev    = scalar(close_s.iloc[-2]) if len(close_s) >= 2 else last
        chg     = last - prev
        chg_pct = (chg / prev * 100) if prev else 0
        vol     = int(scalar(vol_s.iloc[-1]))
        hi      = scalar(high_s.iloc[-1])
        lo      = scalar(low_s.iloc[-1])

        sign  = "🟢" if chg >= 0 else "🔴"
        arrow = "▲" if chg >= 0 else "▼"

        embed = discord.Embed(
            title=f"{sign} {jk}",
            color=0x3fb950 if chg >= 0 else 0xf85149,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="💰 Harga",      value=f"Rp {last:,.0f}", inline=True)
        embed.add_field(name=f"{arrow} Perubahan",
                        value=f"Rp {chg:+,.0f}  ({chg_pct:+.2f}%)", inline=True)
        embed.add_field(name="\u200b",        value="\u200b", inline=False)
        embed.add_field(name="📈 High",       value=f"Rp {hi:,.0f}", inline=True)
        embed.add_field(name="📉 Low",        value=f"Rp {lo:,.0f}", inline=True)
        embed.add_field(name="📊 Volume",     value=f"{vol:,}", inline=True)
        embed.set_footer(text="Data via yfinance · IDX")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        log.exception(e)
        await interaction.followup.send(
            f"❌ Error saat mengambil data **{jk}**: `{e}`")


# ─── /chart ──────────────────────────────────────────────────────────────────
TF_CHOICES = [
    app_commands.Choice(name="3 Menit  (candle 15m, 5 hari)",  value="3m"),
    app_commands.Choice(name="30 Menit (candle 90m, 1 bulan)", value="30m"),
    app_commands.Choice(name="1 Hari   (candle 1d,  6 bulan)", value="1d"),
    app_commands.Choice(name="1 Minggu (candle 1wk, 2 tahun)", value="1w"),
]

@bot.tree.command(name="chart", description="Candlestick chart + MA untuk saham IDX")
@app_commands.describe(
    ticker="Kode saham (contoh: BBCA)",
    timeframe="Pilih timeframe",
)
@app_commands.choices(timeframe=TF_CHOICES)
async def chart_cmd(
    interaction: discord.Interaction,
    ticker: str,
    timeframe: app_commands.Choice[str],
):
    await interaction.response.defer()
    jk       = to_jk(ticker)
    guild_id = interaction.guild_id or 0
    extra    = custom_mas[guild_id].get(jk, [])

    try:
        loop = asyncio.get_event_loop()
        buf  = await loop.run_in_executor(
            None, build_chart, jk, timeframe.value, extra)
        file = discord.File(buf, filename=f"{jk}_{timeframe.value}.png")
        await interaction.followup.send(
            content=f"📊 **{jk}** — `{timeframe.name}`",
            file=file,
        )
    except Exception as e:
        log.exception(e)
        await interaction.followup.send(
            f"❌ Gagal membuat chart **{jk}**: `{e}`")


# ─── Cooldown tracker untuk /analyzechart ────────────────────────────────────
# analyze_cooldowns[user_id] = timestamp terakhir pakai
analyze_cooldowns: dict[int, float] = {}
ANALYZE_COOLDOWN_SECONDS = 30

# ─── /analyzechart ───────────────────────────────────────────────────────────
@bot.tree.command(
    name="analyzechart",
    description="Upload screenshot chart TradingView → dianalisa AI (support, resistance, sinyal)"
)
@app_commands.describe(
    chart="Upload screenshot chart TradingView kamu (PNG/JPG)",
    catatan="Catatan tambahan opsional (contoh: fokus ke area breakout)",
)
async def analyzechart_cmd(
    interaction: discord.Interaction,
    chart: discord.Attachment,
    catatan: str = "",
):
    import time

    # Cek cooldown per user
    user_id = interaction.user.id
    now = time.time()
    last_used = analyze_cooldowns.get(user_id, 0)
    sisa = ANALYZE_COOLDOWN_SECONDS - (now - last_used)
    if sisa > 0:
        await interaction.response.send_message(
            f"⏳ Sabar dulu! Kamu bisa pakai `/analyzechart` lagi dalam **{int(sisa)+1} detik**.",
            ephemeral=True)
        return

    # Validasi tipe file
    allowed_mime = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
    mime = chart.content_type or ""
    if not any(mime.startswith(m) for m in allowed_mime):
        await interaction.response.send_message(
            "❌ File harus berupa gambar (PNG, JPG, WEBP).", ephemeral=True)
        return

    # Validasi ukuran (max 5 MB)
    if chart.size > 5 * 1024 * 1024:
        await interaction.response.send_message(
            "❌ Ukuran gambar maksimal 5 MB.", ephemeral=True)
        return

    # Catat waktu pakai
    analyze_cooldowns[user_id] = now

    await interaction.response.defer(thinking=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(chart.url) as resp:
                image_bytes = await resp.read()

        # Normalisasi mime type
        if "jpeg" in mime or "jpg" in mime:
            clean_mime = "image/jpeg"
        elif "webp" in mime:
            clean_mime = "image/webp"
        elif "gif" in mime:
            clean_mime = "image/gif"
        else:
            clean_mime = "image/png"

        # Kirim ke Gemini Vision (gratis)
        result = await analyze_chart_with_gemini(image_bytes, clean_mime, catatan)

        # Kirim header + gambar sebagai embed
        embed = discord.Embed(
            title="🤖 Analisa Chart AI",
            color=0x58a6ff,
            timestamp=datetime.utcnow(),
        )
        embed.set_image(url=chart.url)
        embed.set_footer(
            text=f"Powered by Gemini · Upload by {interaction.user.display_name}"
        )

        # Kirim hasil analisa sebagai plain text (limit 2000 char per message)
        # Split per baris supaya tidak kepotong di tengah kalimat
        chunks = []
        current = ""
        for line in result.split("\n"):
            if len(current) + len(line) + 1 > 1900:
                chunks.append(current)
                current = line
            else:
                current += ("\n" if current else "") + line
        if current:
            chunks.append(current)

        await interaction.followup.send(embed=embed)
        for chunk in chunks:
            await interaction.followup.send(chunk)

    except Exception as e:
        log.exception(e)
        await interaction.followup.send(
            f"❌ Gagal menganalisa chart: `{e}`")


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
        await interaction.response.send_message(
            "❌ Period harus antara 2–500.", ephemeral=True)
        return

    jk       = to_jk(ticker)
    guild_id = interaction.guild_id or 0
    existing = custom_mas[guild_id][jk]

    for m in existing:
        if m["type"].upper() == ma_type.value and m["period"] == period:
            await interaction.response.send_message(
                f"⚠️ **{ma_type.value}{period}** sudah ada di `{jk}`.",
                ephemeral=True)
            return

    existing.append({"type": ma_type.value, "period": period})
    await interaction.response.send_message(
        f"✅ Tambah **{ma_type.value}{period}** ke `{jk}`.\n"
        f"Gunakan `/chart {ticker}` untuk melihat hasilnya.")


# ─── /clearma ────────────────────────────────────────────────────────────────
@bot.tree.command(name="clearma", description="Hapus semua MA custom untuk suatu saham")
@app_commands.describe(ticker="Kode saham (contoh: BBCA)")
async def clearma_cmd(interaction: discord.Interaction, ticker: str):
    jk       = to_jk(ticker)
    guild_id = interaction.guild_id or 0
    existing = custom_mas[guild_id].get(jk, [])

    if not existing:
        await interaction.response.send_message(
            f"ℹ️ Tidak ada MA custom untuk `{jk}`.", ephemeral=True)
        return

    count = len(existing)
    custom_mas[guild_id][jk] = []
    await interaction.response.send_message(
        f"🗑️ Berhasil hapus **{count} MA custom** dari `{jk}`.\n"
        f"Chart sekarang hanya tampil EMA20, EMA50, SMA50, SMA200.")


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
    jk       = to_jk(ticker)
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
        f"🔔 Alert diset! Notifikasi saat **{jk}** "
        f"{dir_text} **Rp {harga:,.0f}**.")


# ─── Alert Background Task ────────────────────────────────────────────────────
@tasks.loop(minutes=5)
async def check_alerts():
    for guild_id, guild_alerts in list(alerts.items()):
        triggered = []
        for alert in guild_alerts:
            try:
                hist = yf.download(alert["ticker"], period="1d", interval="1m",
                                   progress=False, auto_adjust=True)
                if hist is None or hist.empty:
                    continue
                close_s = get_col(hist, "Close")
                current = scalar(close_s.iloc[-1])
                hit = (
                    (alert["direction"] == "above" and current >= alert["price"]) or
                    (alert["direction"] == "below" and current <= alert["price"])
                )
                if hit:
                    channel = bot.get_channel(alert["channel_id"])
                    if channel:
                        dir_text = ("naik melewati" if alert["direction"] == "above"
                                    else "turun ke bawah")
                        await channel.send(
                            f"🔔 <@{alert['user_id']}> **{alert['ticker']}** "
                            f"{dir_text} Rp {alert['price']:,.0f}!\n"
                            f"Harga saat ini: **Rp {current:,.0f}**")
                    triggered.append(alert)
            except Exception as e:
                log.warning(f"Alert check error: {e}")

        for t in triggered:
            guild_alerts.remove(t)


@check_alerts.before_loop
async def before_check():
    await bot.wait_until_ready()


# ─── /today ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL   = os.environ.get("TELEGRAM_CHANNEL", "")  # contoh: growinmandiri

async def fetch_telegram_today() -> dict:
    """
    Fetch semua pesan hari ini dari public Telegram channel pakai Telethon.
    Tidak perlu join/admin channel.
    """
    global tg_client
    if not tg_client or not tg_client.is_connected():
        raise RuntimeError("Telethon client belum siap. Cek TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION.")

    channel  = TELEGRAM_CHANNEL.lstrip("@")
    now_utc  = datetime.utcnow().replace(tzinfo=__import__('datetime').timezone.utc)
    today    = now_utc.date()

    # Fetch pesan dari channel hari ini
    messages_raw = []
    async for msg in tg_client.iter_messages(
        f"@{channel}",
        limit=50,
        offset_date=now_utc,
        reverse=False,
    ):
        if msg.date.date() < today:
            break
        if msg.date.date() == today and msg.date <= now_utc:
            messages_raw.append(msg)

    messages_raw.reverse()  # urutkan dari pagi ke siang

    if not messages_raw:
        raise RuntimeError(
            f"Belum ada pesan hari ini dari @{channel}.\n"
            f"Channel mungkin belum posting hari ini."
        )

    messages = []
    pdfs     = []

    for msg in messages_raw:
        text = msg.text or msg.message or ""
        if text:
            messages.append({"text": text, "date": msg.date})

        # Download dokumen PDF
        if msg.document:
            mime = getattr(msg.document, "mime_type", "") or ""
            if "pdf" in mime and len(pdfs) < 3:
                try:
                    fname = "dokumen.pdf"
                    for attr in (msg.document.attributes or []):
                        if hasattr(attr, "file_name") and attr.file_name:
                            fname = attr.file_name
                            break
                    buf = io.BytesIO()
                    await tg_client.download_media(msg, file=buf)
                    buf.seek(0)
                    pdfs.append({"name": fname, "bytes": buf.read()})
                except Exception as e:
                    log.warning(f"Gagal download PDF: {e}")

    return {"messages": messages, "pdfs": pdfs}


def format_news_embed(text: str) -> discord.Embed:
    """Format teks news Telegram jadi Discord embed yang rapi."""
    today_str = datetime.now().strftime("%A, %d %B %Y")

    embed = discord.Embed(
        title=f"📰 Market Update — {today_str}",
        color=0x1DA1F2,
        timestamp=datetime.utcnow(),
    )

    # Parse berita bernomor: "1. Judul https://..."
    import re
    lines = text.split("\n")
    news_items = []
    current = ""

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Deteksi baris bernomor
        if re.match(r"^\d+\.", line):
            if current:
                news_items.append(current)
            current = line
        else:
            current += " " + line if current else line

    if current:
        news_items.append(current)

    if news_items:
        # Tampilkan berita sebagai list ringkas
        news_text = ""
        for item in news_items:
            # Pisah nomor, judul, dan link
            match = re.match(r"^(\d+)\.\s*(.+?)\s*(https?://\S+)?$", item)
            if match:
                num   = match.group(1)
                judul = match.group(2).strip()
                link  = match.group(3) or ""
                if link:
                    news_text += f"**{num}.** [{judul}]({link})\n"
                else:
                    news_text += f"**{num}.** {judul}\n"
            else:
                news_text += f"• {item}\n"

            if len(news_text) > 3500:
                news_text += "...\n"
                break

        embed.description = news_text
    else:
        embed.description = text[:3500]

    embed.set_footer(text="Sumber: Telegram Channel · Bukan saran investasi")
    return embed


@bot.tree.command(name="today", description="Fetch semua market update hari ini dari Telegram")
async def today_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    try:
        data     = await fetch_telegram_today()
        messages = data["messages"]
        pdfs     = data["pdfs"]

        today_str = datetime.now().strftime("%d %B %Y")

        # Kirim setiap pesan sebagai embed terpisah (supaya tidak kepotong)
        for i, msg in enumerate(messages):
            import re
            text     = msg["text"]
            time_str = (msg["date"].astimezone(__import__('datetime').timezone(__import__('datetime').timedelta(hours=7)))).strftime("%H:%M")

            embed = discord.Embed(
                title=f"📰 Market Update {today_str} — {time_str} WIB" if i == 0
                      else f"📋 Update {time_str} WIB",
                color=0x1DA1F2,
                timestamp=datetime.utcnow(),
            )

            # Parse berita bernomor
            lines      = text.split("\n")
            news_items = []
            current    = ""
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if re.match(r"^\d+\.", line):
                    if current:
                        news_items.append(current)
                    current = line
                else:
                    current += " " + line if current else line
            if current:
                news_items.append(current)

            if news_items:
                desc = ""
                for item in news_items:
                    match = re.match(r"^(\d+)\.\s*(.+?)\s*(https?://\S+)?$", item)
                    if match:
                        num, judul, link = match.group(1), match.group(2).strip(), match.group(3) or ""
                        desc += f"**{num}.** [{judul}]({link})\n" if link else f"**{num}.** {judul}\n"
                    else:
                        desc += f"{item}\n"
                    if len(desc) > 3800:
                        desc += "*(dipotong)*"
                        break
                embed.description = desc
            else:
                embed.description = text[:3800]

            embed.set_footer(text=f"@{TELEGRAM_CHANNEL} · Bukan saran investasi")

            # Lampirkan PDF hanya di pesan pertama
            if i == 0 and pdfs:
                files = [discord.File(io.BytesIO(p["bytes"]), filename=p["name"]) for p in pdfs]
                await interaction.followup.send(embed=embed, files=files)
            else:
                await interaction.followup.send(embed=embed)

        if not messages:
            await interaction.followup.send("ℹ️ Belum ada update hari ini.")

    except Exception as e:
        log.exception(e)
        await interaction.followup.send(f"❌ Gagal fetch update hari ini: `{e}`")


# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN environment variable tidak diset!")
    bot.run(TOKEN, log_handler=None)
