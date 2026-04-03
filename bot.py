#!/usr/bin/env python3
import requests, schedule, time, re
from datetime import datetime, timezone, timedelta
from collections import Counter

BOT_TOKEN  = "8210013955:AAHPAmR4NYQmUVVnrlgjfit06C7ZamBM-R4"
CHAT_ID    = "7807756451"
THRESHOLD  =7.5
MAX_ALERTS = 5

def now_dk():
    return datetime.now(timezone.utc) + timedelta(hours=2)

SUBREDDITS = ["wallstreetbets","stocks","investing","pennystocks","smallstreetbets","StockMarket"]
HEADERS = {"User-Agent": "Mozilla/5.0"}
REDDIT_HEADERS = {"User-Agent": "AlphaGemBot/3.0"}

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML"}, timeout=10)
    except Exception as e:
        print(f"Telegram fejl: {e}")

def scan_reddit():
    print("  Scanner Reddit...")
    mentions = Counter()
    sentiment = {}
    bullish = ["buy","moon","rocket","bull","long","squeeze","undervalued","gem","breakout"]
    bearish = ["sell","short","crash","dump","bearish","avoid"]
    exclude = {"THE","AND","FOR","YOU","ARE","HAS","NOT","BUT","ALL","ITS","THIS","THAT","WITH","FROM","THEY","HAVE","MORE","WILL","BEEN","YOUR","WHAT","WHEN","WERE","THERE","THEIR","INTO","WHICH","ABOUT","AFTER","WOULD","COULD","NYSE","NASDAQ","ETF","SEC","IPO","CEO","CFO","EPS","GDP","USD","EUR","DKK","SEK","NOK","GBP","ATH","WSB","YOLO","TLDR","IMO","FYI","DD"}
    for sub in SUBREDDITS:
        try:
            r = requests.get(f"https://www.reddit.com/r/{sub}/hot.json?limit=50", headers=REDDIT_HEADERS, timeout=8)
            if r.status_code != 200: continue
            for post in r.json().get("data",{}).get("children",[]):
                d = post.get("data",{})
                title = d.get("title","").upper()
                body = d.get("selftext","").upper()
                score = d.get("score",0)
                comments = d.get("num_comments",0)
                text = title + " " + body
                tickers = re.findall(r'\$([A-Z]{1,5})\b', text)
                tickers += re.findall(r'\b([A-Z]{2,5})\b', title)
                for t in tickers:
                    if t not in exclude and 2 <= len(t) <= 5:
                        w = 1 + (score/1000) + (comments/100)
                        mentions[t] += w
                        bull = sum(1 for x in bullish if x in text.lower())
                        bear = sum(1 for x in bearish if x in text.lower())
                        if t not in sentiment:
                            sentiment[t] = {"bull":0,"bear":0,"posts":0}
                        sentiment[t]["bull"] += bull
                        sentiment[t]["bear"] += bear
                        sentiment[t]["posts"] += 1
            time.sleep(0.5)
        except Exception as e:
            print(f"    Reddit {sub} fejl: {e}")
    result = []
    for ticker, count in mentions.most_common(40):
        s = sentiment.get(ticker,{"bull":0,"bear":0,"posts":1})
        ratio = s["bull"] / max(s["bull"]+s["bear"],1)
        result.append({"ticker":ticker,"mentions":round(count,1),"sentiment":round(ratio,2),"posts":s["posts"]})
    print(f"    {len(result)} aktier fundet paa Reddit")
    return result

def scan_yahoo():
    print("  Scanner Yahoo Finance...")
    found = []
    try:
        r = requests.get("https://query1.finance.yahoo.com/v1/finance/trending/US?count=20", headers=HEADERS, timeout=8)
        if r.status_code == 200:
            for q in r.json().get("finance",{}).get("result",[{}])[0].get("quotes",[]):
                sym = q.get("symbol","")
                if sym and "." not in sym:
                    found.append({"ticker":sym,"source":"Yahoo Trending"})
    except Exception as e:
        print(f"    Yahoo fejl: {e}")
    try:
        r = requests.get("https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=20", headers=HEADERS, timeout=8)
        if r.status_code == 200:
            for q in r.json().get("finance",{}).get("result",[{}])[0].get("quotes",[]):
                sym = q.get("symbol","")
                if sym and "." not in sym:
                    found.append({"ticker":sym,"source":"Yahoo Gainers"})
    except Exception as e:
        print(f"    Yahoo gainers fejl: {e}")
    print(f"    {len(found)} aktier fundet paa Yahoo")
    return found

def get_stock_details(ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=summaryDetail,defaultKeyStatistics,financialData,price"
        r = requests.get(url, headers=HEADERS, timeout=6)
        if r.status_code != 200: return None
        result = r.json().get("quoteSummary",{}).get("result",[])
        if not result: return None
        res = result[0]
        def val(d, k):
            v = d.get(k,{})
            return v.get("raw",v) if isinstance(v,dict) else v
        price_d = res.get("price",{})
        summary = res.get("summaryDetail",{})
        keystats = res.get("defaultKeyStatistics",{})
        financial = res.get("financialData",{})
        return {"ticker":ticker,"name":val(price_d,"longName") or ticker,"price":val(price_d,"regularMarketPrice"),"change_pct":val(price_d,"regularMarketChangePercent"),"market_cap":val(price_d,"marketCap"),"volume":val(price_d,"regularMarketVolume"),"avg_volume":val(summary,"averageVolume"),"pe_ratio":val(summary,"trailingPE"),"short_ratio":val(keystats,"shortRatio"),"revenue_growth":val(financial,"revenueGrowth"),"gross_margins":val(financial,"grossMargins"),"debt_to_equity":val(financial,"debtToEquity"),"current_ratio":val(financial,"currentRatio"),"target_price":val(financial,"targetMeanPrice"),"recommendation":val(financial,"recommendationKey"),"sector":val(price_d,"sector") or "Unknown"}
    except:
        return None

def score_combined(details, reddit_data):
    if not details: return None
    def clamp(v): return max(0, min(10, v))
    pe = details.get("pe_ratio") or 0
    growth = details.get("revenue_growth") or 0
    margins = details.get("gross_margins") or 0
    debt = details.get("debt_to_equity") or 999
    f = 5.0
    if 0 < pe < 20: f += 1.0
    elif 0 < pe < 35: f += 0.5
    elif pe > 80: f -= 0.5
    if growth > 0.30: f += 1.5
    elif growth > 0.15: f += 1.0
    elif growth > 0.05: f += 0.5
    elif growth < 0: f -= 1.0
    if margins > 0.60: f += 1.0
    elif margins > 0.30: f += 0.5
    if debt < 50: f += 0.5
    elif debt > 200: f -= 0.5
    f = clamp(f)
    volume = details.get("volume") or 0
    avg_vol = details.get("avg_volume") or 1
    change = details.get("change_pct") or 0
    vr = volume / max(avg_vol, 1)
    m = 5.0
    if vr > 5: m += 2.5
    elif vr > 3: m += 1.5
    elif vr > 2: m += 1.0
    elif vr > 1.5: m += 0.5
    if change > 10: m += 1.5
    elif change > 5: m += 1.0
    elif change > 2: m += 0.5
    elif change < -5: m -= 1.0
    m = clamp(m)
    ri = next((x for x in reddit_data if x["ticker"]==details["ticker"]), None)
    rd = 5.0
    if ri:
        mn = ri.get("mentions",0)
        st = ri.get("sentiment",0.5)
        if mn > 50: rd += 3.0
        elif mn > 20: rd += 2.0
        elif mn > 10: rd += 1.5
        elif mn > 5: rd += 1.0
        elif mn > 0: rd += 0.5
        if st > 0.7: rd += 1.5
        elif st > 0.5: rd += 0.5
        elif st < 0.3: rd -= 1.0
    rd = clamp(rd)
    sr = details.get("short_ratio") or 0
    sq = 5.0
    if sr > 10: sq += 3.0
    elif sr > 5: sq += 1.5
    elif sr > 3: sq += 0.5
    if vr > 3 and sr > 5: sq += 1.5
    sq = clamp(sq)
    rec = details.get("recommendation") or ""
    target = details.get("target_price") or 0
    price = details.get("price") or 1
    an = 5.0
    if rec in ["strongBuy","buy"]: an += 2.0
    elif rec == "hold": an += 0.5
    elif rec in ["sell","strongSell"]: an -= 2.0
    if target and price:
        up = (target - price) / price
        if up > 0.50: an += 2.0
        elif up > 0.25: an += 1.0
        elif up > 0.10: an += 0.5
        elif up < 0: an -= 1.0
    an = clamp(an)
    master = round(min(10, max(0, (f*1.5 + m*1.2 + rd*1.0 + sq*0.8 + an*1.0) / 5.5)), 1)
    if target and price and target > price:
        upside = round((target-price)/price*100)
    else:
        upside = round(20 + master*8)
    signal = ("💎 SKJULT GEM" if master >= 8.5 else "🚀 STAERKT KOB" if master >= 7.5 else "✅ KOB" if master >= 6.5 else "👀 WATCH" if master >= 5.5 else "❌ UNDGA")
    return {"master":master,"signal":signal,"upside":upside,"f":round(f,1),"m":round(m,1),"rd":round(rd,1),"sq":round(sq,1),"an":round(an,1),"ri":ri}

def format_alert(details, scores):
    ticker = details["ticker"]
    name = (details.get("name") or ticker)[:28]
    price = details.get("price") or 0
    change = details.get("change_pct") or 0
    mcap = details.get("market_cap") or 0
    sector = details.get("sector") or "Unknown"
    vr = round((details.get("volume",0)/max(details.get("avg_volume",1),1)),1)
    rec = details.get("recommendation") or "N/A"
    mcap_s = (f"${mcap/1e9:.1f}mia" if mcap>1e9 else f"${mcap/1e6:.0f}M" if mcap>1e6 else "N/A")
    arrow = "📈" if change > 0 else "📉"
    bar = "█"*int(scores["master"]) + "░"*(10-int(scores["master"]))
    ri_line = ""
    if scores.get("ri"):
        ri = scores["ri"]
        ri_line = f"\n📱 Reddit: {ri['mentions']:.0f} mentions"
    ts = now_dk().strftime('%d/%m/%Y %H:%M')
    return f"""{scores['signal']} <b>{ticker} - {name}</b>
━━━━━━━━━━━━━━━━━━━━
💰 Pris: ${price:.2f} {arrow} {change:+.1f}%
📊 Markedsvaerdi: {mcap_s}
🏭 Sektor: {sector}
📦 Volumen: {vr}x normalt{ri_line}

⚡ <b>SCORE: {scores['master']}/10</b>
{bar}

📊 Fundamental: {scores['f']}/10
⚡ Momentum: {scores['m']}/10
📱 Reddit: {scores['rd']}/10
🔥 Squeeze: {scores['sq']}/10
🎯 Analytiker: {scores['an']}/10

📈 Upside: {scores['upside']}%
🏦 Anbefaling: {rec}
⏰ {ts} DK
━━━━━━━━━━━━━━━━━━━━
⚠️ Ikke investeringsraadgivning"""

def run_scan():
    start = now_dk()
    print(f"\n[{start.strftime('%H:%M')}] Scanner starter...")
    send_telegram(f"🔭 <b>Scanner starter...</b>\n📱 Reddit + 📊 Yahoo\n⏰ {start.strftime('%H:%M')} DK")
    reddit_data = scan_reddit()
    yahoo_data = scan_yahoo()
    all_tickers = set()
    for r in reddit_data[:40]: all_tickers.add(r["ticker"])
    for y in yahoo_data[:30]: all_tickers.add(y["ticker"])
    print(f"  {len(all_tickers)} kandidater fundet")
    send_telegram(f"📋 <b>{len(all_tickers)} kandidater fundet</b>\nScorer og filtrerer...")
    results = []
    for i, ticker in enumerate(sorted(all_tickers)):
        print(f"  [{i+1}/{len(all_tickers)}] {ticker}...", end=" ", flush=True)
        details = get_stock_details(ticker)
        if not details: print("ingen data"); continue
        scores = score_combined(details, reddit_data)
        if not scores: print("fejl"); continue
        print(f"{scores['master']}/10")
        results.append((details, scores))
        time.sleep(0.3)
    results.sort(key=lambda x: -x[1]["master"])
    alerts_sent = 0
    for details, scores in results:
        if scores["master"] >= THRESHOLD and alerts_sent < MAX_ALERTS:
            send_telegram(format_alert(details, scores))
            alerts_sent += 1
            time.sleep(1)
    elapsed = round((now_dk()-start).seconds/60, 1)
    top5 = results[:5]
    if not top5:
        summary = f"🔭 <b>Scan faerdig</b>\nScreenet: {len(all_tickers)}\nIngen over {THRESHOLD}\n⏰ {now_dk().strftime('%d/%m/%Y %H:%M')} DK"
    else:
        lines = [f"📊 <b>SCAN RESULTAT</b>", f"Screenet: {len(all_tickers)} kandidater\n"]
        for i,(det,sc) in enumerate(top5,1):
            medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"#{i}"
            lines.append(f"{medal} <b>{det['ticker']}</b> - {sc['master']}/10 {sc['signal']}")
        lines.append(f"\n💎 Gems (>{THRESHOLD}): {alerts_sent}")
        lines.append(f"⏱ Tid: {elapsed} min")
        lines.append(f"⏰ {now_dk().strftime('%d/%m/%Y %H:%M')} DK")
        summary = "\n".join(lines)
    send_telegram(summary)
    print(f"\nFaerdig - {alerts_sent} alerts paa {elapsed} min")

if __name__ == "__main__":
    print("ALPHA GEM BOT v3")
    send_telegram(f"💎 <b>Alpha Gem Bot v3 online!</b>\n\n📱 Reddit: {len(SUBREDDITS)} subreddits\n📊 Yahoo Finance\n⚡ Taerskel: {THRESHOLD}+\n⏰ Kl. 08:00 og 16:00 DK\n\nStarter scan om 10 sekunder...")
    time.sleep(10)
    run_scan()
    schedule.every().day.at("06:00").do(run_scan)
    schedule.every().day.at("14:00").do(run_scan)
    print("Scheduler aktiv")
    while True:
        schedule.run_pending()
        time.sleep(60)
