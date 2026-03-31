"""
🤖 Indian Stock Market Telegram Bot — UPGRADED (Groq Version)
================================================
FEATURES:
  - Stock history with ASCII price chart
  - 1W / 1M / 3M / 6M / 1Y data
  - 52-week high/low analysis
  - Support/Resistance levels
  - Volume analysis
  - Buy/Sell signal (simple)
  - Beautiful formatted messages with emojis
  - Groq AI (Free & Fast)
"""

import asyncio
import logging
import os
import schedule
import time
import threading
import feedparser
import yfinance as yf
import pytz
import requests
import sys
sys.setrecursionlimit(10000)
from datetime import datetime, timedelta
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ─────────────────────────────────────────────
# 🔧 CONFIG
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")

IST = pytz.timezone("Asia/Kolkata")

# ─────────────────────────────────────────────
# 📊 STOCK LIST
# ─────────────────────────────────────────────
NSE_STOCKS = {
    "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "HDFCBANK": "HDFCBANK.NS",
    "INFY": "INFY.NS", "ICICIBANK": "ICICIBANK.NS", "HINDUNILVR": "HINDUNILVR.NS",
    "SBIN": "SBIN.NS", "BAJFINANCE": "BAJFINANCE.NS", "KOTAKBANK": "KOTAKBANK.NS",
    "AXISBANK": "AXISBANK.NS", "ITC": "ITC.NS", "MARUTI": "MARUTI.NS",
    "WIPRO": "WIPRO.NS", "ULTRACEMCO": "ULTRACEMCO.NS", "TITAN": "TITAN.NS",
    "SUNPHARMA": "SUNPHARMA.NS", "ONGC": "ONGC.NS", "NTPC": "NTPC.NS",
    "POWERGRID": "POWERGRID.NS", "TATAMOTORS": "TATAMOTORS.NS", "LT": "LT.NS",
    "ASIANPAINT": "ASIANPAINT.NS", "ADANIPORTS": "ADANIPORTS.NS",
    "HCLTECH": "HCLTECH.NS", "NESTLEIND": "NESTLEIND.NS", "BAJAJFINSV": "BAJAJFINSV.NS",
    "DIVISLAB": "DIVISLAB.NS", "DRREDDY": "DRREDDY.NS", "EICHERMOT": "EICHERMOT.NS",
    "GRASIM": "GRASIM.NS", "HEROMOTOCO": "HEROMOTOCO.NS", "HINDALCO": "HINDALCO.NS",
    "JSWSTEEL": "JSWSTEEL.NS", "M&M": "M&M.NS", "SBILIFE": "SBILIFE.NS",
    "TATACONSUM": "TATACONSUM.NS", "TATASTEEL": "TATASTEEL.NS", "TECHM": "TECHM.NS",
    "COALINDIA": "COALINDIA.NS", "BPCL": "BPCL.NS",
}

NEWS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "https://feeds.feedburner.com/ndtvprofit-latest",
]

seen_news = set()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 🤖 GROQ AI (FREE)
# ─────────────────────────────────────────────
def ai_analyze(gainers, losers):
    gainer_str = ", ".join([f"{g['name']} ({g['change']:+.1f}%)" for g in gainers])
    loser_str  = ", ".join([f"{l['name']} ({l['change']:+.1f}%)" for l in losers])
    prompt = f"""Indian stock market movers today:
GAINERS: {gainer_str}
LOSERS: {loser_str}

For each stock write ONE short simple reason (5-8 words max). Indian market context. Realistic.
Format:
GAINERS:
STOCKNAME: reason here
LOSERS:
STOCKNAME: reason here"""
def get_stock_data():
    results = []
    for name, ticker in NSE_STOCKS.items():
        try:
            stock = yf.Ticker(ticker)
            hist  = stock.history(period="5d")
            if len(hist) >= 2:
                prev = hist["Close"].iloc[-2]
                curr = hist["Close"].iloc[-1]
                chg  = ((curr - prev) / prev) * 100
                results.append({"name": name, "ticker": ticker, "price": round(curr, 2), "change": round(chg, 2)})
        except:
            pass
    return results

    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama3-8b-8192",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 600,
            "temperature": 0.7
        }
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Groq AI error: {e}")
        return ""

# ─────────────────────────────────────────────
# 📈 ASCII CHART GENERATOR
# ─────────────────────────────────────────────
def make_bar_chart(prices, width=24):
    if not prices or len(prices) < 2:
        return "No data"
    sample = prices[-width:]
    mn = min(sample)
    mx = max(sample)
    rng = mx - mn if mx != mn else 1
    bars = "▁▂▃▄▅▆▇█"
    result = ""
    for p in sample:
        normalized = (p - mn) / rng
        bar_idx = min(int(normalized * 7), 7)
        result += bars[bar_idx]
    return result

# ─────────────────────────────────────────────
# 📊 STOCK HISTORY FETCHER
# ─────────────────────────────────────────────
def get_stock_history(symbol, period="3mo"):
    ticker_name = NSE_STOCKS.get(symbol.upper(), symbol.upper() + ".NS")
    try:
        stock = yf.Ticker(ticker_name)
        info = stock.info

        hist_1w  = stock.history(period="5d")
        hist_1m  = stock.history(period="1mo")
        hist_3m  = stock.history(period="3mo")
        hist_6m  = stock.history(period="6mo")
        hist_1y  = stock.history(period="1y")

        if hist_1m.empty:
            return None

        curr_price = round(hist_1m["Close"].iloc[-1], 2)
        prev_price = round(hist_1m["Close"].iloc[-2], 2) if len(hist_1m) >= 2 else curr_price
        today_chg  = round(((curr_price - prev_price) / prev_price) * 100, 2)

        curr_vol = int(hist_1m["Volume"].iloc[-1]) if "Volume" in hist_1m else 0
        avg_vol  = int(hist_1m["Volume"].mean()) if "Volume" in hist_1m else 0

        high_52w = round(hist_1y["High"].max(), 2) if not hist_1y.empty else "N/A"
        low_52w  = round(hist_1y["Low"].min(), 2)  if not hist_1y.empty else "N/A"

        price_1w  = round(hist_1w["Close"].iloc[0], 2)  if not hist_1w.empty else curr_price
        price_1m  = round(hist_1m["Close"].iloc[0], 2)  if not hist_1m.empty else curr_price
        price_3m  = round(hist_3m["Close"].iloc[0], 2)  if not hist_3m.empty else curr_price
        price_6m  = round(hist_6m["Close"].iloc[0], 2)  if not hist_6m.empty else curr_price
        price_1y  = round(hist_1y["Close"].iloc[0], 2)  if not hist_1y.empty else curr_price

        ret_1w = round(((curr_price - price_1w) / price_1w) * 100, 2)
        ret_1m = round(((curr_price - price_1m) / price_1m) * 100, 2)
        ret_3m = round(((curr_price - price_3m) / price_3m) * 100, 2)
        ret_6m = round(((curr_price - price_6m) / price_6m) * 100, 2)
        ret_1y = round(((curr_price - price_1y) / price_1y) * 100, 2)

        support    = round(hist_1m["Low"].min(), 2)
        resistance = round(hist_1m["High"].max(), 2)

        closes = hist_3m["Close"].tolist() if not hist_3m.empty else []
        ma20 = round(sum(closes[-20:]) / min(20, len(closes)), 2) if closes else "N/A"
        ma50 = round(sum(closes[-50:]) / min(50, len(closes)), 2) if len(closes) >= 10 else "N/A"

        signal = "NEUTRAL"
        signal_reason = "Market average trend"
        if isinstance(ma20, float) and curr_price > ma20:
            signal = "BULLISH"
            signal_reason = "Price is above 20-day average"
        elif isinstance(ma20, float) and curr_price < ma20:
            signal = "BEARISH"
            signal_reason = "Price is below 20-day average"
        if isinstance(high_52w, float) and curr_price >= high_52w * 0.97:
            signal = "STRONG BULLISH"
            signal_reason = "Near 52-week high — strong momentum"
        elif isinstance(low_52w, float) and curr_price <= low_52w * 1.03:
            signal = "OVERSOLD"
            signal_reason = "Near 52-week low — possible bounce"

        if isinstance(high_52w, float) and isinstance(low_52w, float):
            pos_52w = round(((curr_price - low_52w) / (high_52w - low_52w)) * 100, 1)
        else:
            pos_52w = "N/A"

        vol_status = "High Volume" if curr_vol > avg_vol * 1.3 else "Low Volume" if curr_vol < avg_vol * 0.7 else "Normal Volume"

        chart_prices = hist_3m["Close"].tolist() if not hist_3m.empty else []
        bar_chart = make_bar_chart(chart_prices, width=30)

        name   = info.get("longName", symbol)
        sector = info.get("sector", "N/A")
        mktcap = info.get("marketCap", 0)
        mktcap_str = f"₹{round(mktcap/1e9, 1)}B" if mktcap else "N/A"
        pe     = info.get("trailingPE", None)
        pb     = info.get("priceToBook", None)
        div    = info.get("dividendYield", None)

        return {
            "symbol": symbol.upper(),
            "name": name,
            "sector": sector,
            "curr_price": curr_price,
            "prev_price": prev_price,
            "today_chg": today_chg,
            "ret_1w": ret_1w, "ret_1m": ret_1m,
            "ret_3m": ret_3m, "ret_6m": ret_6m, "ret_1y": ret_1y,
            "high_52w": high_52w, "low_52w": low_52w,
            "pos_52w": pos_52w,
            "support": support, "resistance": resistance,
            "ma20": ma20, "ma50": ma50,
            "signal": signal, "signal_reason": signal_reason,
            "curr_vol": curr_vol, "avg_vol": avg_vol, "vol_status": vol_status,
            "mktcap": mktcap_str,
            "pe": round(pe, 1) if pe else "N/A",
            "pb": round(pb, 2) if pb else "N/A",
            "div": f"{round(div*100, 2)}%" if div else "N/A",
            "bar_chart": bar_chart,
        }
    except Exception as e:
        logger.error(f"History fetch error for {symbol}: {e}")
        return None

# ─────────────────────────────────────────────
# 💬 FORMAT MESSAGES
# ─────────────────────────────────────────────
def format_stock_detail(d):
    sig_emoji = {"BULLISH": "🟢", "STRONG BULLISH": "🚀", "BEARISH": "🔴", "OVERSOLD": "⚡", "NEUTRAL": "🟡"}.get(d["signal"], "🟡")
    chg_emoji = "📈" if d["today_chg"] > 0 else "📉"

    def ret_str(v):
        arrow = "▲" if v > 0 else "▼"
        return f"{arrow} {abs(v):.1f}%"

    if isinstance(d["pos_52w"], float):
        filled = int(d["pos_52w"] / 10)
        bar52 = "█" * filled + "░" * (10 - filled) + f" {d['pos_52w']}%"
    else:
        bar52 = "N/A"

    msg  = f"📊 *{d['name']}*\n"
    msg += f"`{d['symbol']}` | {d['sector']}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"💰 *Current Price:*  `₹{d['curr_price']}`\n"
    msg += f"{chg_emoji} *Aaj ka Change:*  `{d['today_chg']:+.2f}%`\n\n"
    msg += f"📉📈 *3 Month Price Chart:*\n"
    msg += f"`{d['bar_chart']}`\n"
    msg += f"_Low → High (last 3 months)_\n\n"
    msg += "📅 *Performance (Returns):*\n"
    msg += "```\n"
    msg += f"1 Week  : {ret_str(d['ret_1w'])}\n"
    msg += f"1 Month : {ret_str(d['ret_1m'])}\n"
    msg += f"3 Month : {ret_str(d['ret_3m'])}\n"
    msg += f"6 Month : {ret_str(d['ret_6m'])}\n"
    msg += f"1 Year  : {ret_str(d['ret_1y'])}\n"
    msg += "```\n\n"
    msg += f"📌 *52-Week Range:*\n"
    msg += f"Low:  `₹{d['low_52w']}`\n"
    msg += f"High: `₹{d['high_52w']}`\n"
    msg += f"`[{bar52}]`\n\n"
    msg += f"🎯 *Support & Resistance (1 Month):*\n"
    msg += f"Support    : `₹{d['support']}`\n"
    msg += f"Resistance : `₹{d['resistance']}`\n\n"
    msg += f"📐 *Moving Averages:*\n"
    msg += f"MA20 : `₹{d['ma20']}`\n"
    msg += f"MA50 : `₹{d['ma50']}`\n\n"
    vol_bar = "🔊" if d["vol_status"] == "High Volume" else "🔉" if d["vol_status"] == "Normal Volume" else "🔈"
    msg += f"{vol_bar} *Volume:*  {d['vol_status']}\n"
    if d["curr_vol"]:
        msg += f"Today: `{d['curr_vol']:,}`  |  Avg: `{d['avg_vol']:,}`\n\n"
    msg += f"🏦 *Fundamentals:*\n"
    msg += f"Market Cap : `{d['mktcap']}`\n"
    msg += f"P/E Ratio  : `{d['pe']}`\n"
    msg += f"P/B Ratio  : `{d['pb']}`\n"
    msg += f"Dividend   : `{d['div']}`\n\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"{sig_emoji} *Signal:  {d['signal']}*\n"
    msg += f"_Reason: {d['signal_reason']}_\n\n"
    msg += "⚠️ _Sirf information hai. Apna research zarur karo._"
    return msg


def format_briefing(gainers, losers, reasons):
    now = datetime.now(IST).strftime("%d %b %Y, %I:%M %p IST")
    msg  = f"🌅 *GOOD MORNING — Daily Market Briefing*\n"
    msg += f"📅 {now}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += "📈 *TOP 10 GAINERS*\n\n"
    for i, s in enumerate(gainers, 1):
        reason = reasons.get(s["name"].upper(), "Strong buying interest")
        msg += f"🟢 *{i}. {s['name']}*  `{s['change']:+.2f}%`\n"
        msg += f"   ₹{s['price']}  |  _{reason}_\n\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += "📉 *TOP 10 LOSERS*\n\n"
    for i, s in enumerate(losers, 1):
        reason = reasons.get(s["name"].upper(), "Selling pressure today")
        msg += f"🔴 *{i}. {s['name']}*  `{s['change']:+.2f}%`\n"
        msg += f"   ₹{s['price']}  |  _{reason}_\n\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "💡 _Kisi bhi stock ka naam bhejo — detailed history milegi!_\n"
    msg += "⚠️ _Sirf information hai. Investment advice nahi._"
    return msg


def format_news_alert(title, summary, source):
    msg  = "📰 *MARKET NEWS ALERT*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"📌 *{title}*\n\n"
    if summary:
        clean = summary[:280].replace("<b>","").replace("</b>","").replace("<br>","").replace("&amp;","&").replace("&lt;","<").replace("&gt;",">")
        msg += f"_{clean}_\n\n"
    msg += f"🔗 _Source: {source}_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━"
    return msg

# ─────────────────────────────────────────────
# 📈 MARKET DATA FUNCTIONS
# ─────────────────────────────────────────────
def get_stock_data():
    results = []
    for name, ticker in NSE_STOCKS.items():
        try:
            stock = yf.Ticker(ticker)
            hist  = stock.history(period="2d")
            if len(hist) >= 2:
                prev = hist["Close"].iloc[-2]
                curr = hist["Close"].iloc[-1]
                chg  = ((curr - prev) / prev) * 100
                results.append({"name": name, "ticker": ticker, "price": round(curr, 2), "change": round(chg, 2)})
        except:
            pass
    return results

def get_top_movers(data, n=10):
    return sorted(data, key=lambda x: x["change"], reverse=True)[:n], sorted(data, key=lambda x: x["change"])[:n]

def parse_ai_reasons(ai_text):
    reasons = {}
    for line in ai_text.splitlines():
        line = line.strip()
        if ":" in line and not line.upper().startswith(("GAINER","LOSER")):
            parts = line.split(":", 1)
            if len(parts) == 2:
                reasons[parts[0].strip().upper()] = parts[1].strip()
    return reasons

def fetch_latest_news(max_items=5):
    articles = []
    for url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                article = {
                    "title":   entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                    "link":    entry.get("link", ""),
                    "id":      entry.get("id", entry.get("link", "")),
                    "source":  feed.feed.get("title", "News"),
                }
                if article["id"] and article["id"] not in seen_news:
                    articles.append(article)
        except:
            pass
    return articles[:max_items]

# ─────────────────────────────────────────────
# ⏰ SCHEDULED JOBS
# ─────────────────────────────────────────────
async def send_morning_briefing(bot: Bot):
    logger.info("Sending morning briefing...")
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="⏳ _Subah ki briefing aa rahi hai..._", parse_mode=ParseMode.MARKDOWN)
    try:
        data = get_stock_data()
        if not data:
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="❌ Market data unavailable.")
            return
        gainers, losers = get_top_movers(data)
        reasons = parse_ai_reasons(ai_analyze(gainers, losers))
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=format_briefing(gainers, losers, reasons), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Briefing error: {e}")

async def send_news_alerts(bot: Bot):
    global seen_news
    for article in fetch_latest_news():
        if article["id"] not in seen_news:
            seen_news.add(article["id"])
            try:
                await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=format_news_alert(article["title"], article["summary"], article["source"]), parse_mode=ParseMode.MARKDOWN)
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"News error: {e}")

# ─────────────────────────────────────────────
# 🤖 COMMAND HANDLERS
# ─────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 *Indian Stock Market Bot!*\n\n"
        "Ab kisi bhi stock ka *naam* bhejo — poori history milegi!\n\n"
        "📋 *Commands:*\n"
        "• /briefing — Aaj ke top gainers & losers\n"
        "• /news     — Latest market news\n"
        "• /stock RELIANCE — Detailed history\n"
        "• /help     — Sab commands\n\n"
        "💡 *Shortcut:* Bas stock naam type karo jaise:\n"
        "`RELIANCE` ya `TCS` ya `INFY`\n\n"
        "⏰ *Auto:* 8 AM briefing + har 30 min news\n"
        "⚠️ _Investment advice nahi — sirf information._"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stocks_list = ", ".join(list(NSE_STOCKS.keys())[:20]) + "..."
    msg = (
        "📖 *Sab Commands*\n\n"
        "/start    — Welcome\n"
        "/briefing — Top 10 gainers & losers\n"
        "/news     — Latest market news\n"
        "/stock \\[NAME\\] — Detailed stock history\n"
        "/help     — Ye message\n\n"
        "💡 *Direct naam bhi bhej sakte ho:*\n"
        f"`{stocks_list}`\n\n"
        "⏰ Auto briefing: *8:00 AM IST daily*\n"
        "📰 News: *Har 30 minute*"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_briefing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ _Live data fetch ho raha hai... 15-20 sec wait karo._", parse_mode=ParseMode.MARKDOWN)
    try:
        data = get_stock_data()
        if not data:
            await update.message.reply_text("❌ Data nahi mila. Try again.")
            return
        gainers, losers = get_top_movers(data)
        reasons = parse_ai_reasons(ai_analyze(gainers, losers))
        await update.message.reply_text(format_briefing(gainers, losers, reasons), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 _Latest news aa rahi hai..._", parse_mode=ParseMode.MARKDOWN)
    articles = fetch_latest_news(max_items=5)
    if not articles:
        await update.message.reply_text("Abhi koi naya news nahi. Thodi der mein try karo.")
        return
    for article in articles:
        try:
            await update.message.reply_text(format_news_alert(article["title"], article["summary"], article["source"]), parse_mode=ParseMode.MARKDOWN)
            await asyncio.sleep(1)
        except:
            await update.message.reply_text(f"📰 {article['title']}")

async def send_stock_detail(msg_obj, symbol):
    wait_msg = await msg_obj.reply_text(
        f"🔍 _{symbol} ka pura data fetch ho raha hai...\n15-20 second wait karo._",
        parse_mode=ParseMode.MARKDOWN
    )
    try:
        d = get_stock_history(symbol)
        if not d:
            await wait_msg.edit_text(f"❌ `{symbol}` ka data nahi mila.\n\nCheck karo: RELIANCE, TCS, HDFCBANK, INFY, SBIN")
            return
        text = format_stock_detail(d)
        keyboard = [
            [
                InlineKeyboardButton("📅 1 Week",  callback_data=f"hist_{symbol}_1wk"),
                InlineKeyboardButton("📅 1 Month", callback_data=f"hist_{symbol}_1mo"),
                InlineKeyboardButton("📅 3 Month", callback_data=f"hist_{symbol}_3mo"),
            ],
            [
                InlineKeyboardButton("📅 6 Month", callback_data=f"hist_{symbol}_6mo"),
                InlineKeyboardButton("📅 1 Year",  callback_data=f"hist_{symbol}_1y"),
                InlineKeyboardButton("🔄 Refresh", callback_data=f"hist_{symbol}_3mo"),
            ]
        ]
        await wait_msg.delete()
        await msg_obj.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await wait_msg.edit_text(f"❌ Error: {str(e)[:100]}")

async def cmd_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text("Usage: /stock SYMBOL\n\nExample:\n/stock RELIANCE\n/stock TCS")
        return
    await send_stock_detail(update.message, args[0].upper())

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().upper().replace(" ", "")
    if text in NSE_STOCKS or (len(text) >= 2 and len(text) <= 15 and text.isalpha()):
        await send_stock_detail(update.message, text)
    else:
        await update.message.reply_text(
            "Stock ka naam bhejo jaise:\n`RELIANCE` ya `TCS` ya `INFY`\n\nYa /help type karo.",
            parse_mode=ParseMode.MARKDOWN
        )

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if len(parts) < 3 or parts[0] != "hist":
        return
    symbol = parts[1]
    period = parts[2]
    await query.edit_message_text(f"🔄 _{symbol} — {period} data load ho raha hai..._", parse_mode=ParseMode.MARKDOWN)
    try:
        d = get_stock_history(symbol, period)
        if not d:
            await query.edit_message_text(f"❌ Data nahi mila {symbol} ke liye.")
            return
        text = format_stock_detail(d)
        keyboard = [
            [
                InlineKeyboardButton("📅 1 Week",  callback_data=f"hist_{symbol}_1wk"),
                InlineKeyboardButton("📅 1 Month", callback_data=f"hist_{symbol}_1mo"),
                InlineKeyboardButton("📅 3 Month", callback_data=f"hist_{symbol}_3mo"),
            ],
            [
                InlineKeyboardButton("📅 6 Month", callback_data=f"hist_{symbol}_6mo"),
                InlineKeyboardButton("📅 1 Year",  callback_data=f"hist_{symbol}_1y"),
                InlineKeyboardButton("🔄 Refresh", callback_data=f"hist_{symbol}_3mo"),
            ]
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {str(e)[:100]}")

# ─────────────────────────────────────────────
# 🔄 SCHEDULER
# ─────────────────────────────────────────────
def run_scheduler(bot: Bot, loop):
    def briefing(): asyncio.run_coroutine_threadsafe(send_morning_briefing(bot), loop)
    def news():     asyncio.run_coroutine_threadsafe(send_news_alerts(bot), loop)
    schedule.every().day.at("08:00").do(briefing)
    schedule.every(30).minutes.do(news)
    logger.info("✅ Scheduler: 8AM briefing + 30min news")
    while True:
        schedule.run_pending()
        time.sleep(30)

# ─────────────────────────────────────────────
# 🚀 MAIN
# ─────────────────────────────────────────────
def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN set karo!")
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
    logger.info("✅ Bot chal raha hai!")
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
