"""
🤖 Indian Stock Market Telegram Bot — FIXED VERSION
Uses NSE Unofficial API (24/7) + yfinance as fallback
"""

import os
import logging
import asyncio
import requests
import json
from datetime import datetime
import pytz
import schedule
import time
import threading
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")
IST                = pytz.timezone("Asia/Kolkata")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

groq_client = Groq(api_key=GROQ_API_KEY)

# ── NSE Stock List ─────────────────────────────────────────────────────────────
NSE_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA",
    "WIPRO", "ULTRACEMCO", "TITAN", "BAJFINANCE", "NESTLEIND",
    "TECHM", "POWERGRID", "HCLTECH", "NTPC", "ONGC",
    "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "COALINDIA", "ADANIENT"
]

# ── NSE Data Fetcher (Primary - works 24/7) ───────────────────────────────────
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

def get_nse_session():
    """Get NSE session with cookies."""
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=10)
        s.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
    except:
        pass
    return s

def fetch_stock_nse(symbol: str, session=None) -> dict | None:
    """Fetch stock data from NSE API."""
    try:
        if session is None:
            session = get_nse_session()
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        pd = data.get("priceInfo", {})
        price = pd.get("lastPrice", 0)
        prev  = pd.get("previousClose", 0)
        change_pct = pd.get("pChange", 0)
        week52 = data.get("priceInfo", {}).get("weekHighLow", {})
        return {
            "symbol": symbol,
            "price": price,
            "prev_close": prev,
            "change_pct": round(change_pct, 2),
            "week_high": week52.get("max", 0),
            "week_low": week52.get("min", 0),
            "volume": data.get("marketDeptOrderBook", {}).get("tradeInfo", {}).get("totalTradedVolume", 0),
        }
    except Exception as e:
        logger.warning(f"NSE fetch failed for {symbol}: {e}")
        return None

def fetch_stock_yfinance(symbol: str) -> dict | None:
    """Fallback: fetch from yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(f"{symbol}.NS")
        hist = t.history(period="5d")
        if len(hist) < 2:
            return None
        curr = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2]
        chg  = ((curr - prev) / prev) * 100
        info = t.fast_info
        return {
            "symbol": symbol,
            "price": round(float(curr), 2),
            "prev_close": round(float(prev), 2),
            "change_pct": round(chg, 2),
            "week_high": getattr(info, "year_high", 0) or 0,
            "week_low":  getattr(info, "year_low", 0) or 0,
            "volume": 0,
        }
    except Exception as e:
        logger.warning(f"yfinance failed for {symbol}: {e}")
        return None

def get_single_stock(symbol: str) -> dict | None:
    """Get stock — try NSE first, then yfinance."""
    session = get_nse_session()
    data = fetch_stock_nse(symbol.upper(), session)
    if data and data["price"] > 0:
        return data
    return fetch_stock_yfinance(symbol.upper())

def get_all_stocks() -> list[dict]:
    """Fetch all stocks in parallel using threading."""
    results = []
    lock = threading.Lock()
    session = get_nse_session()

    def fetch(sym):
        d = fetch_stock_nse(sym, session)
        if not d or d["price"] == 0:
            d = fetch_stock_yfinance(sym)
        if d and d["price"] > 0:
            with lock:
                results.append(d)

    threads = [threading.Thread(target=fetch, args=(s,)) for s in NSE_STOCKS]
    for t in threads: t.start()
    for t in threads: t.join()
    return results

# ── AI Analysis ───────────────────────────────────────────────────────────────
def ai_analyze(prompt: str) -> str:
    try:
        resp = groq_client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": "Tum ek expert Indian stock market analyst ho. Hindi mein concise jawab do."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            temperature=0.7,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"AI analysis unavailable: {e}"

# ── Briefing ──────────────────────────────────────────────────────────────────
def format_stock_row(d: dict, rank: int) -> str:
    arrow = "🟢" if d["change_pct"] >= 0 else "🔴"
    return f"{rank}. {arrow} *{d['symbol']}* ₹{d['price']:,.2f} ({d['change_pct']:+.2f}%)"

def build_briefing() -> str:
    stocks = get_all_stocks()
    if not stocks:
        return "❌ Data fetch nahi hua. NSE server se response nahi mila. Thodi der baad try karo."

    stocks.sort(key=lambda x: x["change_pct"])
    top_losers  = stocks[:10]
    top_gainers = list(reversed(stocks[-10:]))

    now = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    msg = f"📊 *Stock Market Briefing*\n_{now}_\n\n"

    msg += "🔴 *Top 10 Girawat (Losers)*\n"
    for i, s in enumerate(top_losers, 1):
        msg += format_stock_row(s, i) + "\n"

    msg += "\n🟢 *Top 10 Uchhai (Gainers)*\n"
    for i, s in enumerate(top_gainers, 1):
        msg += format_stock_row(s, i) + "\n"

    # AI prediction
    summary = ", ".join([f"{s['symbol']} {s['change_pct']:+.1f}%" for s in stocks])
    prediction = ai_analyze(
        f"Aaj ke NSE data ke basis pe: {summary}\n"
        "Kal ke top 5 gainers aur top 5 losers predict karo — short mein."
    )
    msg += f"\n🤖 *AI Prediction (Kal ke liye)*\n{prediction}"
    return msg

# ── /stock command ─────────────────────────────────────────────────────────────
def build_stock_detail(symbol: str) -> str:
    d = get_single_stock(symbol)
    if not d:
        return f"❌ *{symbol}* ka data nahi mila.\n\nValid stocks: RELIANCE, TCS, HDFCBANK, INFY, SBIN"

    arrow = "🟢" if d["change_pct"] >= 0 else "🔴"
    msg  = f"{arrow} *{d['symbol']}* — Live Data\n"
    msg += f"💰 Price: ₹{d['price']:,.2f}\n"
    msg += f"📊 Change: {d['change_pct']:+.2f}%\n"
    msg += f"⬅️ Prev Close: ₹{d['prev_close']:,.2f}\n"
    if d.get("week_high"):
        msg += f"📈 52W High: ₹{d['week_high']:,.2f}\n"
        msg += f"📉 52W Low:  ₹{d['week_low']:,.2f}\n"
    if d.get("volume"):
        msg += f"📦 Volume: {int(d['volume']):,}\n"

    analysis = ai_analyze(
        f"{symbol} stock: Price ₹{d['price']}, Change {d['change_pct']:+.2f}%, "
        f"52W High ₹{d['week_high']}, 52W Low ₹{d['week_low']}. "
        "Short buy/sell/hold recommendation do."
    )
    msg += f"\n🤖 *AI Recommendation:*\n{analysis}"
    return msg

# ── Telegram Handlers ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Indian Stock Bot — Active!*\n\n"
        "Commands:\n"
        "/briefing — Top gainers & losers + AI prediction\n"
        "/stock RELIANCE — Kisi bhi stock ka detail\n"
        "/help — Help\n\n"
        "Ya seedha stock naam type karo: `HDFCBANK`",
        parse_mode="Markdown",
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Commands:*\n\n"
        "/briefing — Top 10 gainers & losers\n"
        "/stock SYMBOL — Stock detail (e.g. /stock TCS)\n\n"
        "*Available stocks:*\n"
        "RELIANCE, TCS, HDFCBANK, INFY, ICICIBANK, SBIN,\n"
        "BHARTIARTL, ITC, KOTAKBANK, LT, AXISBANK,\n"
        "MARUTI, SUNPHARMA, WIPRO, TATAMOTORS, BAJFINANCE...",
        parse_mode="Markdown",
    )

async def cmd_briefing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Data fetch ho raha hai... 15-20 sec wait karo.")
    text = build_briefing()
    await msg.edit_text(text, parse_mode="Markdown")

async def cmd_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: /stock RELIANCE\nYa seedha type karo: RELIANCE")
        return
    symbol = args[0].upper()
    msg = await update.message.reply_text(f"⏳ {symbol} ka data fetch ho raha hai...")
    text = build_stock_detail(symbol)
    await msg.edit_text(text, parse_mode="Markdown")

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper()
    if text in NSE_STOCKS or len(text) <= 12:
        msg = await update.message.reply_text(f"⏳ {text} ka data fetch ho raha hai...")
        result = build_stock_detail(text)
        await msg.edit_text(result, parse_mode="Markdown")

# ── Scheduler ─────────────────────────────────────────────────────────────────
def send_scheduled(app):
    async def _send():
        text = build_briefing()
        await app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="Markdown")
    asyncio.run_coroutine_threadsafe(_send(), app.loop)

def run_scheduler(app):
    schedule.every().day.at("08:00").do(send_scheduled, app)
    while True:
        schedule.run_pending()
        time.sleep(30)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    logger.info("🚀 Bot start ho raha hai...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("stock",    cmd_stock))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    sched_thread = threading.Thread(target=run_scheduler, args=(app,), daemon=True)
    sched_thread.start()

    logger.info("✅ Bot chal raha hai! Scheduler: 8AM briefing")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
