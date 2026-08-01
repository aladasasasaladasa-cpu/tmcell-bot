"""
TMCELL Bot v3 — Webhook versiyon
Render.com'da 7/24 çalışır. Uyku modu YOK.
"""
import asyncio
import aiohttp
from aiohttp import web
import json
import os
import aiosqlite
import re
from datetime import datetime
from bs4 import BeautifulSoup

TOKEN = "8843044615:AAENf7YOQ-1IVBWQtzXVeZFmrzoi35PathI"
API = f"https://api.telegram.org/bot{TOKEN}"
DB = "users.db"
PORT = int(os.environ.get("PORT", 8000))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

# ========== DB ==========
async def db_init():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, phone TEXT, password TEXT, updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, balance TEXT, checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        await db.commit()

async def db_save(uid, phone, pw):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,CURRENT_TIMESTAMP)", (uid, phone, pw))
        await db.commit()

async def db_get(uid):
    async with aiosqlite.connect(DB) as db:
        c = await db.execute("SELECT phone,password FROM users WHERE user_id=?", (uid,))
        r = await c.fetchone()
        return {"phone": r[0], "password": r[1]} if r else None

async def db_del(uid):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM users WHERE user_id=?", (uid,))
        await db.commit()

async def db_add_history(uid, bal):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO history (user_id,balance) VALUES (?,?)", (uid, bal))
        await db.commit()

async def db_last_balance(uid):
    async with aiosqlite.connect(DB) as db:
        c = await db.execute("SELECT balance,checked FROM history WHERE user_id=? ORDER BY checked DESC LIMIT 1", (uid,))
        r = await c.fetchone()
        return {"balance": r[0], "checked": r[1]} if r else None

# ========== TMCELL SCRAPER ==========
async def tmcell_check(phone, password):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://hyzmat.tmcell.tm/ru-ru", timeout=20) as r:
                html = await r.text()
            soup = BeautifulSoup(html, "lxml")
            token = soup.find("input", {"name": "__RequestVerificationToken"})
            if not token: return {"ok": False, "err": "Portal elýeterli däl"}
            
            data = {"__RequestVerificationToken": token.get("value", ""),
                    "PhoneNumber": f"993{phone}", "Password": password}
            async with s.post("https://hyzmat.tmcell.tm/User", data=data,
                              headers={"Referer": "https://hyzmat.tmcell.tm/ru-ru"},
                              timeout=20, allow_redirects=True) as r:
                home = await r.text()

            if "неверный" in home.lower() or "nädogry" in home.lower():
                return {"ok": False, "err": "Nädogry telefon ýa-da parol"}
            if "заблок" in home.lower():
                return {"ok": False, "err": "Hasap 30 minut bloklandy"}

            soup2 = BeautifulSoup(home, "lxml")
            balance = "Tapylmady"
            details = {}
            for pat in [r'(?:Баланс|Balans)[:\s]*([\d.,]+\s*(?:manat|TMT|mnt)?)',
                        r'([\d.,]+)\s*(?:manat|TMT)', r'на счету[:\s]*([\d.,]+)']:
                m = re.search(pat, home, re.IGNORECASE)
                if m: balance = m.group(1).strip(); break

            for t in soup2.find_all("table"):
                for row in t.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        k, v = cells[0].get_text(strip=True), cells[1].get_text(strip=True)
                        if k and v: details[k] = v
                        if any(w in k.lower() for w in ['баланс', 'balans']): balance = v
            
            if not details:
                for line in soup2.get_text().split("\n"):
                    if any(w in line.lower() for w in ['баланс', 'balans']):
                        balance = line; break

            return {"ok": True, "balance": balance, "details": details}
    except Exception as e:
        return {"ok": False, "err": f"Portal säwligi: {str(e)[:80]}"}

# ========== TELEGRAM API ==========
async def tg_send(chat_id, text, keyboard=None, inline=None):
    d = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard: d["reply_markup"] = {"keyboard": keyboard, "resize_keyboard": True}
    if inline: d["reply_markup"] = {"inline_keyboard": inline}
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{API}/sendMessage", json=d, timeout=10) as r:
            return await r.json()

async def tg_answer_cb(cb_id, text=""):
    async with aiohttp.ClientSession() as s:
        await s.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cb_id, "text": text})

async def tg_edit(chat_id, msg_id, text, inline=None):
    d = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if inline: d["reply_markup"] = {"inline_keyboard": inline}
    async with aiohttp.ClientSession() as s:
        await s.post(f"{API}/editMessageText", json=d)

async def tg_delete(chat_id, msg_id):
    async with aiohttp.ClientSession() as s:
        await s.post(f"{API}/deleteMessage", json={"chat_id": chat_id, "message_id": msg_id})

# ========== KEYBOARDS ==========
MAIN = [[{"text":"💰 Balansy barla"},{"text":"⚙️ Hasap sazlamalary"}],
        [{"text":"📋 Soňky barlag"},{"text":"ℹ️ Kömek"}]]
SETTINGS = [[{"text":"🔑 Hasaby täzele"},{"text":"🗑 Hasaby poz"}],[{"text":"🔙 Esasy menýu"}]]
CANCEL = [[{"text":"❌ Goýbolsun et"}]]

WELCOME = "🇹🇲 <b>TMCELL Balans Bot</b>\n\n<b>⚙️ Hasap sazlamalary → 🔑 Hasaby täzele</b>\nSoň <b>💰 Balansy barla</b> basyň!"

# ========== STATE ==========
states = {}

async def process_message(chat_id: int, text: str, msg_id: int = 0):
    if text == "/start":
        states.pop(chat_id, None)
        await tg_send(chat_id, WELCOME, MAIN)

    elif text in ("/help", "ℹ️ Kömek"):
        states.pop(chat_id, None)
        await tg_send(chat_id, "🔑 <b>Parol almak:</b> SIM kartyňyzdan <b>0831</b>-e boş SMS iberiň.\n📱 <b>Nomer:</b> Soňky 8 san.\n\n<b>⚙️ Hasap sazlamalary → Hasaby täzele</b>", MAIN)

    elif text == "💰 Balansy barla":
        states.pop(chat_id, None)
        u = await db_get(chat_id)
        if not u:
            await tg_send(chat_id, "⚠️ Ilki hasap dörediň!\n⚙️ Hasap sazlamalary → 🔑 Hasaby täzele", MAIN,
                         [[{"text":"🔑 Hasaby döret","callback_data":"cb_setup"}]])
            return
        tmp = await tg_send(chat_id, "⏳ Barlanýar...")
        r = await tmcell_check(u["phone"], u["password"])
        await tg_delete(chat_id, tmp["result"]["message_id"])
        if r["ok"]:
            bal = r["balance"]
            await db_add_history(chat_id, bal)
            txt = f"💰 <b>BALANS</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n📱 <b>{bal}</b>"
            if r.get("details"):
                txt += "\n\n📊 <b>Giňişleýin:</b>"
                for k,v in list(r["details"].items())[:5]:
                    if k.lower() not in ('баланс','balans','balance'):
                        txt += f"\n▫️ {k}: {v}"
            await tg_send(chat_id, txt, MAIN, [[{"text":"🔄 Täzeden","callback_data":"cb_refresh"}]])
        else:
            await tg_send(chat_id, f"❌ {r['err']}", MAIN)

    elif text == "📋 Soňky barlag":
        states.pop(chat_id, None)
        last = await db_last_balance(chat_id)
        if last:
            await tg_send(chat_id, f"📋 <b>Soňky:</b>\n🕐 {last['checked']}\n💰 <code>{last['balance']}</code>", MAIN,
                         [[{"text":"🔄 Täzeden","callback_data":"cb_refresh"}]])
        else:
            await tg_send(chat_id, "📋 Entek barlag ýok.", MAIN)

    elif text == "⚙️ Hasap sazlamalary":
        states.pop(chat_id, None)
        u = await db_get(chat_id)
        if u:
            mp = f"******{u['phone'][-4:]}"
            await tg_send(chat_id, f"⚙️ <b>Hasap</b>\n📱 +993{mp}\n🔐 {'•'*len(u['password'])}", SETTINGS)
        else:
            await tg_send(chat_id, "⚙️ Hasap döredilmedi.", SETTINGS)

    elif text == "🔙 Esasy menýu":
        states.pop(chat_id, None)
        await tg_send(chat_id, "🔙 Esasy menýu", MAIN)

    elif text == "🔑 Hasaby täzele":
        states[chat_id] = {"s": "phone"}
        await tg_send(chat_id, "📱 Telefon nomeriňizi giriziň (soňky 8 san):", CANCEL)

    elif text == "🗑 Hasaby poz":
        states.pop(chat_id, None)
        if await db_get(chat_id):
            await tg_send(chat_id, "⚠️ Pozmak isleýärsiňizmi?", None,
                         [[{"text":"✅ Hawa","callback_data":"cb_del_yes"},{"text":"❌ Ýok","callback_data":"cb_del_no"}]])
        else:
            await tg_send(chat_id, "Hasap ýok.", MAIN)

    elif text == "❌ Goýbolsun et":
        states.pop(chat_id, None)
        await tg_send(chat_id, "❌ Goýbolsun edildi.", MAIN)

    elif chat_id in states:
        s = states[chat_id]
        if s["s"] == "phone":
            d = ''.join(c for c in text if c.isdigit())
            if len(d) < 8: await tg_send(chat_id, "⚠️ Azyndan 8 san!", CANCEL); return
            s["phone"] = d[-8:]
            s["s"] = "pw"
            await tg_send(chat_id, f"📱 +993{s['phone']}\nIndi <b>paroly</b> giriziň:", CANCEL)
        elif s["s"] == "pw":
            pw = text.strip()
            if len(pw) < 4: await tg_send(chat_id, "⚠️ Gysga!", CANCEL); return
            s["pw"] = pw; s["s"] = "confirm"
            await tg_send(chat_id, f"📋 <b>Tassyklaň:</b>\n📱 +993{s['phone']}\n🔐 {'•'*len(pw)}", None,
                         [[{"text":"✅ Tassykla","callback_data":"cb_conf_yes"},{"text":"❌ Goýbolsun","callback_data":"cb_conf_no"}]])

async def process_callback(chat_id: int, data: str, msg_id: int):
    if data == "cb_setup":
        states[chat_id] = {"s": "phone"}
        await tg_delete(chat_id, msg_id)
        await tg_send(chat_id, "📱 Telefon nomer (soňky 8 san):", CANCEL)

    elif data == "cb_refresh":
        u = await db_get(chat_id)
        if not u: await tg_edit(chat_id, msg_id, "⚠️ Hasap ýok."); return
        await tg_edit(chat_id, msg_id, "⏳ Barlanýar...")
        r = await tmcell_check(u["phone"], u["password"])
        if r["ok"]:
            bal = r["balance"]
            await db_add_history(chat_id, bal)
            await tg_edit(chat_id, msg_id, f"💰 <b>BALANS</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n📱 <b>{bal}</b>",
                         [[{"text":"🔄 Täzeden","callback_data":"cb_refresh"}]])
        else:
            await tg_edit(chat_id, msg_id, f"❌ {r['err']}")

    elif data == "cb_del_yes":
        await db_del(chat_id)
        await tg_edit(chat_id, msg_id, "✅ Pozuldy!")

    elif data == "cb_del_no":
        await tg_edit(chat_id, msg_id, "❌ Goýbolsun edildi.")

    elif data == "cb_conf_yes":
        s = states.get(chat_id, {})
        if s.get("phone") and s.get("pw"):
            await db_save(chat_id, s["phone"], s["pw"])
            await tg_edit(chat_id, msg_id, f"✅ <b>HASAP DÖREDILDI!</b>\n📱 +993{s['phone']}")
            await tg_send(chat_id, "👇 Indi balansy barlaň:", MAIN)
        states.pop(chat_id, None)

    elif data == "cb_conf_no":
        await tg_edit(chat_id, msg_id, "❌ Goýbolsun edildi.")
        await tg_send(chat_id, "👇 Esasy menýu:", MAIN)
        states.pop(chat_id, None)


# ========== WEBHOOK HANDLER ==========
async def webhook_handler(request):
    try:
        data = await request.json()
        if "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            text = msg.get("text", "")
            await process_message(chat_id, text)
        elif "callback_query" in data:
            cb = data["callback_query"]
            cb_id = cb["id"]
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            data_cb = cb["data"]
            await tg_answer_cb(cb_id)
            await process_callback(chat_id, data_cb, msg_id)
        return web.Response(text="OK", status=200)
    except Exception as e:
        print(f"Webhook error: {e}")
        return web.Response(text="OK", status=200)

async def health(request):
    return web.Response(text="OK", status=200)

async def set_webhook(url):
    """Telegram-a webhook url-i bellemek"""
    async with aiohttp.ClientSession() as s:
        await s.post(f"{API}/deleteWebhook")
        await s.post(f"{API}/setWebhook", json={"url": f"{url}/webhook"})

async def keepalive(app):
    """Her 5 minutdan health-check ping"""
    while True:
        await asyncio.sleep(300)
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://tmcell-bot-xxxx.onrender.com/health", timeout=5) as r:
                    pass
        except:
            pass  # Internal ping, ignore errors

async def on_startup(app):
    await db_init()
    if WEBHOOK_URL:
        await set_webhook(WEBHOOK_URL)
        print(f"✅ Webhook set: {WEBHOOK_URL}/webhook")
    # Keepalive task
    asyncio.create_task(keepalive(app))

async def main():
    app = web.Application()
    app.router.add_post("/webhook", webhook_handler)
    app.router.add_get("/health", health)
    app.on_startup.append(on_startup)
    
    print(f"🤖 TMCELL Bot v3 — WEBHOOK MODE")
    print(f"🚀 Starting on port {PORT}")
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    
    print(f"✅ Bot running on port {PORT}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
