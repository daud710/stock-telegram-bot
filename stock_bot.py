"""
🤖 Indian Stock Market Telegram Bot
- NSE Direct API (24/7 live data, market band ho tab bhi)
- Detailed format with charts, MA, signals
- Groq AI via requests (no extra package)
"""

import asyncio
import logging
import os
import schedule
import time
import threading
import feedparser
import pytz
import requests
import sys
from datetime import datetime
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

sys.setrecursionlimit(10000)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")
IST = pytz.timezone("Asia/Kolkata")

NSE_STOCKS = [
    "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","SBIN",
    "BAJFINANCE","KOTAKBANK","AXISBANK","ITC","MARUTI","WIPRO","ULTRACEMCO",
    "TITAN","SUNPHARMA","ONGC","NTPC","POWERGRID","TATAMOTORS","LT",
    "ASIANPAINT","ADANIPORTS","HCLTECH","NESTLEIND","BAJAJFINSV","DIVISLAB",
    "DRREDDY","EICHERMOT","GRASIM","HEROMOTOCO","HINDALCO","JSWSTEEL",
    "SBILIFE","TATACONSUM","TATASTEEL","TECHM","COALINDIA","BPCL","ADANIENT",
]

NEWS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.moneycontrol.com/rss/MCtopnews.xml",
]

seen_news = set()
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── NSE API (24/7, works after market close too) ──────────────────────────────
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

def get_nse_session():
    s = requests.Session()
    s.headers.update(NSE_HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=10)
        s.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
    except:
        pass
    return s

def fetch_nse_quote(symbol: str, session) -> dict | None:
    """Fetch single stock quote from NSE API."""
    try:
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol.upper()}"
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return None
        d = r.json()
        pi = d.get("priceInfo", {})
        price      = pi.get("lastPrice", 0) or pi.get("close", 0)
        prev_close = pi.get("previousClose", 0)
        if not price or not prev_close:
            return None
        change_pct = round(((price - prev_close) / prev_close) * 100, 2)
        wh = pi.get("weekHighLow", {})
        ti = d.get("marketDeptOrderBook", {}).get("tradeInfo", {})
        metadata = d.get("metadata", {})
        return {
            "symbol":     symbol.upper(),
            "name":       metadata.get("companyName", symbol),
            "price":      round(price, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": change_pct,
            "open":       round(pi.get("open", 0), 2),
            "high":       round(pi.get("intraDayHighLow", {}).get("max", 0) or pi.get("high", 0), 2),
            "low":        round(pi.get("intraDayHighLow", {}).get("min", 0) or pi.get("low", 0), 2),
            "week_high":  round(wh.get("max", 0), 2),
            "week_low":   round(wh.get("min", 0), 2),
            "volume":     ti.get("totalTradedVolume", 0),
            "value":      ti.get("totalTradedValue", 0),
        }
    except Exception as e:
        logger.warning(f"NSE quote failed {symbol}: {e}")
        return None

def fetch_nse_history(symbol: str, session) -> list[float]:
    """Fetch 3-month price history from NSE."""
    try:
        url = f"https://www.nseindia.com/api/historical/cm/equity?symbol={symbol.upper()}&series=[%22EQ%22]&from=2024-01-01&to=2025-12-31"
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json().get("data", [])
        closes = [float(row["CH_CLOSING_PRICE"]) for row in data if row.get("CH_CLOSING_PRICE")]
        return closes[-65:]  # last ~3 months
    except:
        return []

def fetch_all_stocks_nse() -> list[dict]:
    """Fetch all stocks using NSE market data API (one call = all stocks)."""
    try:
        session = get_nse_session()
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            raise Exception(f"Status {r.status_code}")
        all_data = r.json().get("data", [])
        results = []
        stock_set = set(NSE_STOCKS)
        for item in all_data:
            sym = item.get("symbol", "")
            if sym not in stock_set:
                continue
            price      = item.get("lastPrice", 0) or item.get("previousClose", 0)
            prev_close = item.get("previousClose", 0)
            if not price or not prev_close:
                continue
            change_pct = round(((price - prev_close) / prev_close) * 100, 2)
            results.append({
                "symbol":     sym,
                "name":       item.get("meta", {}).get("companyName", sym) if isinstance(item.get("meta"), dict) else sym,
                "price":      round(price, 2),
                "prev_close": round(prev_close, 2),
                "change_pct": change_pct,
            })
        logger.info(f"NSE bulk fetch: {len(results)} stocks")
        return results
    except Exception as e:
        logger.warning(f"NSE bulk fetch failed: {e}")
        return []

def get_all_stocks() -> list[dict]:
    """Get all stocks — bulk NSE API first, individual fallback."""
    results = fetch_all_stocks_nse()
    if len(results) >= 10:
        return results
    # Fallback: individual fetch
    logger.info("Falling back to individual NSE fetch...")
    session = get_nse_session()
    out = []
    for sym in NSE_STOCKS:
        d = fetch_nse_quote(sym, session)
        if d:
            out.append(d)
        time.sleep(0.3)
    return out

def get_single_stock_detail(symbol: str) -> dict | None:
    """Get detailed stock data for /stock command."""
    session = get_nse_session()
    quote = fetch_nse_quote(symbol.upper(), session)
    if not quote:
        return None
    history = fetch_nse_history(symbol.upper(), session)

    closes = history if len(history) >= 5 else []
    ma20 = round(sum(closes[-20:]) / min(20, len(closes)), 2) if len(closes) >= 5 else "N/A"
    ma50 = round(sum(closes[-50:]) / min(50, len(closes)), 2) if len(closes) >= 10 else "N/A"

    curr = quote["price"]
    signal = "NEUTRAL"
    signal_reason = "Market average trend"
    if isinstance(ma20, float):
        if curr > ma20:
            signal, signal_reason = "BULLISH", "Price is above 20-day average"
        else:
            signal, signal_reason = "BEARISH", "Price is below 20-day average"
    if quote["week_high"] and curr >= quote["week_high"] * 0.97:
        signal, signal_reason = "STRONG BULLISH", "Near 52-week high — strong momentum"
    elif quote["week_low"] and curr <= quote["week_low"] * 1.03:
        signal, signal_reason = "OVERSOLD", "Near 52-week low — possible bounce"

    pos_52w = "N/A"
    if quote["week_high"] and quote["week_low"] and quote["week_high"] != quote["week_low"]:
        pos_52w = round(((curr - quote["week_low"]) / (quote["week_high"] - quote["week_low"])) * 100, 1)

    bar_chart = make_bar_chart(closes, width=30)

    # Performance returns from history
    def ret(n):
        if len(closes) >= n:
            old = closes[-n]
            return round(((curr - old) / old) * 100, 2)
        return 0.0

    quote.update({
        "ma20": ma20, "ma50": ma50,
        "signal": signal, "signal_reason": signal_reason,
        "pos_52w": pos_52w,
        "bar_chart": bar_chart,
        "ret_1w": ret(5), "ret_1m": ret(22), "ret_3m": ret(65),
        "vol_status": "N/A",
    })
    return quote

# ── Groq AI ───────────────────────────────────────────────────────────────────
def call_groq(prompt: str, system: str = "", max_tokens: int = 600) -> str:
    try:
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": "llama3-8b-8192", "messages": messages, "max_tokens": max_tokens, "temperature": 0.7}
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return ""

def ai_analyze(gainers, losers):
    gainer_str = ", ".join([f"{g['symbol']} ({g['change_pct']:+.1f}%)" for g in gainers])
    loser_str  = ", ".join([f"{l['symbol']} ({l['change_pct']:+.1f}%)" for l in losers])
    prompt = f"""Indian stock market movers today:
GAINERS: {gainer_str}
LOSERS: {loser_str}
For each stock write ONE short simple reason (5-8 words max). Realistic Indian market context.
Format:
GAINERS:
SYMBOL: reason here
LOSERS:
SYMBOL: reason here"""
    return call_groq(prompt)

def parse_ai_reasons(ai_text: str) -> dict:
    reasons = {}
    for line in ai_text.splitlines():
        line = line.strip()
        if ":" in line and not line.upper().startswith(("GAINER","LOSER")):
            parts = line.split(":", 1)
            if len(parts) == 2:
                reasons[parts[0].strip().upper()] = parts[1].strip()
    return reasons

# ── Chart ─────────────────────────────────────────────────────────────────────
def make_bar_chart(prices: list, width: int = 30) -> str:
    if not prices or len(prices) < 2:
        return "━" * width
    sample = prices[-width:]
    mn, mx = min(sample), max(sample)
    rng = mx - mn if mx != mn else 1
    bars = "▁▂▃▄▅▆▇█"
    return "".join(bars[min(int(((p - mn) / rng) * 7), 7)] for p in sample)

# ── Format Messages ───────────────────────────────────────────────────────────
def format_stock_detail(d: dict) -> str:
    sig_emoji = {"BULLISH":"🟢","STRONG BULLISH":"🚀","BEARISH":"🔴","OVERSOLD":"⚡","NEUTRAL":"🟡"}.get(d["signal"],"🟡")
    chg_emoji = "📈" if d["change_pct"] > 0 else "📉"

    def ret_str(v):
        return f"{'▲' if v > 0 else '▼'} {abs(v):.1f}%"

    pos = d.get("pos_52w", "N/A")
    if isinstance(pos, float):
        filled = min(int(pos / 10), 10)
        bar52 = "█" * filled + "░" * (10 - filled) + f" {pos}%"
    else:
        bar52 = "N/A"

    msg  = f"📊 *{d.get('name', d['symbol'])}*\n"
    msg += f"`{d['symbol']}` | NSE\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"💰 *Current Price:*  `₹{d['price']}`\n"
    msg += f"⬅️ *Prev Close:*  `₹{d['prev_close']}`\n"
    msg += f"{chg_emoji} *Aaj ka Change:*  `{d['change_pct']:+.2f}%`\n\n"

    if d.get("bar_chart") and d["bar_chart"] != "━" * 30:
        msg += f"📉📈 *3 Month Price Chart:*\n`{d['bar_chart']}`\n_Low → High_\n\n"

    msg += "📅 *Performance:*\n```\n"
    msg += f"1W: {ret_str(d['ret_1w'])}  1M: {ret_str(d['ret_1m'])}\n"
    msg += f"3M: {ret_str(d['ret_3m'])}\n```\n\n"

    if d.get("week_high") and d.get("week_low"):
        msg += f"📌 *52W:* Low `₹{d['week_low']}` — High `₹{d['week_high']}`\n`[{bar52}]`\n\n"

    if d.get("high") and d.get("low"):
        msg += f"🎯 Today High `₹{d['high']}` | Low `₹{d['low']}`\n"

    ma20 = d.get("ma20","N/A")
    ma50 = d.get("ma50","N/A")
    msg += f"📐 MA20: `₹{ma20}` | MA50: `₹{ma50}`\n\n"

    if d.get("volume"):
        msg += f"📦 Volume: `{int(d['volume']):,}`\n\n"

    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━\n{sig_emoji} *{d['signal']}* — _{d['signal_reason']}_\n\n"
    msg += "⚠️ _Sirf information. Apna research karo._"
    return msg

def format_briefing(gainers, losers, reasons) -> str:
    now = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    msg  = f"🌅 *GOOD MORNING — Daily Market Briefing*\n📅 {now}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n📈 *TOP 10 GAINERS*\n\n"
    for i, s in enumerate(gainers, 1):
        reason = reasons.get(s["symbol"].upper(), "Strong buying interest")
        msg += f"🟢 *{i}. {s['symbol']}*  `{s['change_pct']:+.2f}%`\n   ₹{s['price']}  |  _{reason}_\n\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n📉 *TOP 10 LOSERS*\n\n"
    for i, s in enumerate(losers, 1):
        reason = reasons.get(s["symbol"].upper(), "Selling pressure today")
        msg += f"🔴 *{i}. {s['symbol']}*  `{s['change_pct']:+.2f}%`\n   ₹{s['price']}  |  _{reason}_\n\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n💡 _Kisi bhi stock naam bhejo — detail milegi!_\n⚠️ _Sirf information. Investment advice nahi._"
    return msg

def format_news_alert(title, summary, source) -> str:
    msg  = "📰 *MARKET NEWS ALERT*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📌 *{title}*\n\n"
    if summary:
        clean = summary[:280].replace("<b>","").replace("</b>","").replace("<br>","").replace("&amp;","&")
        msg += f"_{clean}_\n\n"
    msg += f"🔗 _Source: {source}_\n━━━━━━━━━━━━━━━━━━━━━━━━"
    return msg

def get_top_movers(data, n=10):
    gainers = sorted(data, key=lambda x: x["change_pct"], reverse=True)[:n]
    losers  = sorted(data, key=lambda x: x["change_pct"])[:n]
    return gainers, losers

def fetch_latest_news(max_items=5):
    articles = []
    for url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                article = {
                    "title": entry.get("title",""),
                    "summary": entry.get("summary",""),
                    "id": entry.get("id", entry.get("link","")),
                    "source": feed.feed.get("title","News")
                }
                if article["id"] not in seen_news:
                    articles.append(article)
        except:
            pass
    return articles[:max_items]

# ── Telegram Handlers ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = ("🤖 *Indian Stock Market Bot — 24/7 Active!*\n\n"
           "📋 *Commands:*\n"
           "• /briefing — Top 10 gainers & losers\n"
           "• /stock RELIANCE — Full stock detail\n"
           "• /news — Latest market news\n"
           "• /help — All commands\n\n"
           "💡 Shortcut: Bas naam type karo — `RELIANCE` ya `TCS`\n"
           "⏰ Auto 8 AM briefing har roz\n"
           "📡 NSE live data — 24/7 kaam karta hai!\n"
           "⚠️ _Investment advice nahi._")
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stocks = ", ".join(NSE_STOCKS[:20]) + "..."
    msg = (f"📖 *Commands:*\n\n"
           f"/briefing — Top 10 gainers & losers + AI reasons\n"
           f"/stock SYMBOL — Full detail (chart, MA, signals)\n"
           f"/news — Latest news\n"
           f"/help — Ye message\n\n"
           f"💡 Direct naam bhi kaam karta hai:\n`{stocks}`\n\n"
           f"⏰ Auto: *8:00 AM IST* briefing")
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_briefing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    wait = await update.message.reply_text("⏳ _Data fetch ho raha hai... 15-20 sec wait karo._", parse_mode=ParseMode.MARKDOWN)
    try:
        data = get_all_stocks()
        if not data:
            await wait.edit_text("❌ NSE se data nahi mila. Thodi der baad try karo.")
            return
        gainers, losers = get_top_movers(data)
        reasons = parse_ai_reasons(ai_analyze(gainers, losers))
        await wait.delete()
        await update.message.reply_text(format_briefing(gainers, losers, reasons), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await wait.edit_text(f"❌ Error: {e}")

async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 _Latest news aa rahi hai..._", parse_mode=ParseMode.MARKDOWN)
    articles = fetch_latest_news(max_items=5)
    if not articles:
        await update.message.reply_text("Abhi koi naya news nahi.")
        return
    for article in articles:
        try:
            await update.message.reply_text(
                format_news_alert(article["title"], article["summary"], article["source"]),
                parse_mode=ParseMode.MARKDOWN
            )
            await asyncio.sleep(1)
        except:
            await update.message.reply_text(f"📰 {article['title']}")

async def send_stock_detail(msg_obj, symbol: str):
    wait = await msg_obj.reply_text(f"🔍 _{symbol} ka data NSE se fetch ho raha hai..._", parse_mode=ParseMode.MARKDOWN)
    try:
        d = get_single_stock_detail(symbol)
        if not d:
            await wait.edit_text(f"❌ `{symbol}` ka data nahi mila.\nValid: RELIANCE, TCS, HDFCBANK, INFY, SBIN")
            return
        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data=f"stock_{symbol}"),
        ]]
        await wait.delete()
        await msg_obj.reply_text(
            format_stock_detail(d),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        await wait.edit_text(f"❌ Error: {str(e)[:100]}")

async def cmd_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /stock SYMBOL\nExample: /stock RELIANCE")
        return
    await send_stock_detail(update.message, ctx.args[0].upper())

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper().replace(" ", "")
    if text in NSE_STOCKS or (2 <= len(text) <= 15 and text.isalpha()):
        await send_stock_detail(update.message, text)
    else:
        await update.message.reply_text(
            "Stock naam bhejo: `RELIANCE` ya `TCS`\nYa /help karo.",
            parse_mode=ParseMode.MARKDOWN
        )

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if parts[0] == "stock" and len(parts) >= 2:
        symbol = parts[1]
        await query.edit_message_text(f"🔄 _{symbol} refresh ho raha hai..._", parse_mode=ParseMode.MARKDOWN)
        d = get_single_stock_detail(symbol)
        if not d:
            await query.edit_message_text("❌ Data nahi mila.")
            return
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data=f"stock_{symbol}")]]
        await query.edit_message_text(format_stock_detail(d), parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

# ── Scheduler ──────────────────────────────────────────────────────────────────
async def send_morning_briefing(bot: Bot):
    try:
        data = get_all_stocks()
        if not data:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="❌ Aaj briefing nahi aayi — NSE data unavailable.")
            return
        gainers, losers = get_top_movers(data)
        reasons = parse_ai_reasons(ai_analyze(gainers, losers))
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=format_briefing(gainers, losers, reasons),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Morning briefing error: {e}")

async def send_news_alerts(bot: Bot):
    global seen_news
    for article in fetch_latest_news():
        if article["id"] not in seen_news:
            seen_news.add(article["id"])
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=format_news_alert(article["title"], article["summary"], article["source"]),
                    parse_mode=ParseMode.MARKDOWN
                )
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"News send error: {e}")

def run_scheduler(bot: Bot, loop):
    schedule.every().day.at("08:00").do(
        lambda: asyncio.run_coroutine_threadsafe(send_morning_briefing(bot), loop)
    )
    schedule.every(30).minutes.do(
        lambda: asyncio.run_coroutine_threadsafe(send_news_alerts(bot), loop)
    )
    logger.info("✅ Scheduler: 8AM briefing + 30min news")
    while True:
        schedule.run_pending()
        time.sleep(30)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN missing!")
        return
    logger.info("🚀 Bot start ho raha hai...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(CommandHandler("news",     cmd_news))
    app.add_handler(CommandHandler("stock",    cmd_stock))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    loop = asyncio.get_event_loop()
    threading.Thread(target=run_scheduler, args=(app.bot, loop), daemon=True).start()
    logger.info("✅ Bot chal raha hai! 24/7 NSE data active.")
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
