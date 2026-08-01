"""
TMCELL Bot — HEPSI BIR ARADA
Polling + HTTP server. Render'da tek komutla çalışır.
"""
import asyncio, aiohttp, json, os, aiosqlite, re, sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from bs4 import BeautifulSoup

TOKEN = "8843044615:AAENf7YOQ-1IVBWQtzXVeZFmrzoi35PathI"
API = f"https://api.telegram.org/bot{TOKEN}"
DB = os.path.join(os.path.dirname(__file__) or ".", "users.db")
PORT = int(os.environ.get("PORT", 8000))
offset_file = os.path.join(os.path.dirname(__file__) or ".", ".offset")

# ===== HEALTH HTTP =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass

def start_health():
    s = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    s.serve_forever()

# ===== DB =====
async def db_init():
    async with aiosqlite.connect(DB) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, phone TEXT, password TEXT, updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, balance TEXT, checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        await db.commit()

async def db_save(uid, phone, pw):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT OR REPLACE INTO users VALUES(?,?,?,CURRENT_TIMESTAMP)", (uid, phone, pw)); await db.commit()

async def db_get(uid):
    async with aiosqlite.connect(DB) as db:
        c = await db.execute("SELECT phone,password FROM users WHERE user_id=?", (uid,))
        r = await c.fetchone()
        return {"phone": r[0], "password": r[1]} if r else None

async def db_del(uid):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM users WHERE user_id=?", (uid,)); await db.commit()

async def db_add_hist(uid, bal):
    async with aiosqlite.connect(DB) as db:
        await db.execute("INSERT INTO history (user_id,balance) VALUES(?,?)", (uid, bal)); await db.commit()

async def db_last(uid):
    async with aiosqlite.connect(DB) as db:
        c = await db.execute("SELECT balance,checked FROM history WHERE user_id=? ORDER BY checked DESC LIMIT 1", (uid,))
        r = await c.fetchone()
        return {"balance": r[0], "checked": r[1]} if r else None

# ===== TMCELL =====
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
            balance, details = "Tapylmady", {}
            for pat in [r'(?:Баланс|Balans)[:\s]*([\d.,]+\s*(?:manat|TMT|mnt)?)', r'([\d.,]+)\s*(?:manat|TMT)']:
                m = re.search(pat, home, re.IGNORECASE)
                if m: balance = m.group(1).strip(); break
            for t in soup2.find_all("table"):
                for row in t.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        k, v = cells[0].get_text(strip=True), cells[1].get_text(strip=True)
                        if k and v: details[k] = v
                        if any(w in k.lower() for w in ['баланс', 'balans']): balance = v
            return {"ok": True, "balance": balance, "details": details}
    except Exception as e:
        return {"ok": False, "err": f"Portal säwligi: {str(e)[:80]}"}

# ===== TG API =====
async def tg(method, data):
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{API}/{method}", json=data, timeout=10) as r:
            return await r.json()

async def send(chat_id, text, keyboard=None, inline=None):
    d = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard: d["reply_markup"] = {"keyboard": keyboard, "resize_keyboard": True}
    if inline: d["reply_markup"] = {"inline_keyboard": inline}
    return await tg("sendMessage", d)

async def edit(chat_id, msg_id, text, inline=None):
    d = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if inline: d["reply_markup"] = {"inline_keyboard": inline}
    await tg("editMessageText", d)

async def delete(chat_id, msg_id):
    await tg("deleteMessage", {"chat_id": chat_id, "message_id": msg_id})

async def answer_cb(cb_id):
    await tg("answerCallbackQuery", {"callback_query_id": cb_id})

# ===== KEYBOARDS =====
MAIN = [[{"text":"💰 Balansy barla"},{"text":"⚙️ Hasap sazlamalary"}],[{"text":"📋 Soňky barlag"},{"text":"ℹ️ Kömek"}]]
SETTINGS = [[{"text":"🔑 Hasaby täzele"},{"text":"🗑 Hasaby poz"}],[{"text":"🔙 Esasy menýu"}]]
CANCEL = [[{"text":"❌ Goýbolsun et"}]]

states = {}

async def handle_message(chat_id, text):
    if text == "/start":
        states.pop(chat_id, None)
        await send(chat_id, "🇹🇲 <b>TMCELL Balans Bot</b>\n\n<b>1.</b> ⚙️ Hasap sazlamalary → 🔑 Hasaby täzele\n<b>2.</b> 💰 Balansy barla basyň!", MAIN)

    elif text in ("/help", "ℹ️ Kömek"):
        states.pop(chat_id, None)
        await send(chat_id, "🔑 <b>Parol:</b> SIM-den <b>0831</b>-e boş SMS iberiň\n📱 <b>Nomer:</b> soňky 8 san\n\n⚙️ → Hasaby täzele → giriziň", MAIN)

    elif text == "💰 Balansy barla":
        states.pop(chat_id, None)
        u = await db_get(chat_id)
        if not u:
            await send(chat_id, "⚠️ Hasap ýok!\n⚙️ → Hasaby täzele", MAIN, [[{"text":"🔑 Hasaby döret","callback_data":"cb_setup"}]])
            return
        tmp = await send(chat_id, "⏳ Barlanýar...", MAIN)
        r = await tmcell_check(u["phone"], u["password"])
        await delete(chat_id, tmp["result"]["message_id"])
        if r["ok"]:
            await db_add_hist(chat_id, r["balance"])
            txt = f"💰 <b>BALANS</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n📱 <b>{r['balance']}</b>"
            if r.get("details"):
                for k,v in list(r["details"].items())[:5]:
                    if k.lower() not in ('баланс','balans','balance'): txt += f"\n▫️ {k}: {v}"
            await send(chat_id, txt, MAIN, [[{"text":"🔄 Täzeden","callback_data":"cb_refresh"}]])
        else:
            await send(chat_id, f"❌ {r['err']}", MAIN)

    elif text == "📋 Soňky barlag":
        states.pop(chat_id, None)
        last = await db_last(chat_id)
        if last:
            await send(chat_id, f"📋 <b>Soňky:</b>\n🕐 {last['checked']}\n💰 <code>{last['balance']}</code>", MAIN, [[{"text":"🔄 Täzeden","callback_data":"cb_refresh"}]])
        else:
            await send(chat_id, "📋 Entek barlag ýok.", MAIN)

    elif text == "⚙️ Hasap sazlamalary":
        states.pop(chat_id, None)
        u = await db_get(chat_id)
        if u: await send(chat_id, f"⚙️ <b>Hasap</b>\n📱 +993******{u['phone'][-4:]}\n🔐 {'•'*len(u['password'])}", SETTINGS)
        else: await send(chat_id, "⚙️ Hasap döredilmedi.", SETTINGS)

    elif text == "🔙 Esasy menýu":
        states.pop(chat_id, None); await send(chat_id, "🔙 Esasy menýu", MAIN)

    elif text == "🔑 Hasaby täzele":
        states[chat_id] = {"s": "phone"}; await send(chat_id, "📱 Telefon nomeriňizi giriziň (soňky 8 san):", CANCEL)

    elif text == "🗑 Hasaby poz":
        states.pop(chat_id, None)
        if await db_get(chat_id):
            await send(chat_id, "⚠️ Pozmak isleýärsiňizmi?", None, [[{"text":"✅ Hawa","callback_data":"cb_del_yes"},{"text":"❌ Ýok","callback_data":"cb_del_no"}]])
        else: await send(chat_id, "Hasap ýok.", MAIN)

    elif text == "❌ Goýbolsun et":
        states.pop(chat_id, None); await send(chat_id, "❌ Goýbolsun edildi.", MAIN)

    elif chat_id in states:
        s = states[chat_id]
        if s["s"] == "phone":
            d = ''.join(c for c in text if c.isdigit())
            if len(d) < 8: await send(chat_id, "⚠️ Azyndan 8 san!", CANCEL); return
            s["phone"] = d[-8:]; s["s"] = "pw"
            await send(chat_id, f"📱 +993{s['phone']}\nIndi <b>paroly</b> giriziň:", CANCEL)
        elif s["s"] == "pw":
            pw = text.strip()
            if len(pw) < 4: await send(chat_id, "⚠️ Gysga!", CANCEL); return
            s["pw"] = pw; s["s"] = "confirm"
            await send(chat_id, f"📋 <b>Tassyklaň:</b>\n📱 +993{s['phone']}\n🔐 {'•'*len(pw)}", None, [[{"text":"✅ Tassykla","callback_data":"cb_conf_yes"},{"text":"❌ Goýbolsun","callback_data":"cb_conf_no"}]])

async def handle_callback(chat_id, data, msg_id):
    if data == "cb_setup":
        states[chat_id] = {"s": "phone"}; await delete(chat_id, msg_id)
        await send(chat_id, "📱 Telefon nomer (soňky 8 san):", CANCEL)
    elif data == "cb_refresh":
        u = await db_get(chat_id)
        if not u: await edit(chat_id, msg_id, "⚠️ Hasap ýok."); return
        await edit(chat_id, msg_id, "⏳ Barlanýar...")
        r = await tmcell_check(u["phone"], u["password"])
        if r["ok"]:
            await db_add_hist(chat_id, r["balance"])
            await edit(chat_id, msg_id, f"💰 <b>BALANS</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n📱 <b>{r['balance']}</b>", [[{"text":"🔄 Täzeden","callback_data":"cb_refresh"}]])
        else: await edit(chat_id, msg_id, f"❌ {r['err']}")
    elif data == "cb_del_yes": await db_del(chat_id); await edit(chat_id, msg_id, "✅ Pozuldy!")
    elif data == "cb_del_no": await edit(chat_id, msg_id, "❌ Goýbolsun")
    elif data == "cb_conf_yes":
        s = states.get(chat_id, {})
        if s.get("phone") and s.get("pw"):
            await db_save(chat_id, s["phone"], s["pw"])
            await edit(chat_id, msg_id, f"✅ <b>HASAP DÖREDILDI!</b>\n📱 +993{s['phone']}")
            await send(chat_id, "👇 Indi balansy barlaň:", MAIN)
        states.pop(chat_id, None)
    elif data == "cb_conf_no": await edit(chat_id, msg_id, "❌ Goýbolsun"); await send(chat_id, "👇 Esasy menýu:", MAIN); states.pop(chat_id, None)

# ===== POLLING =====
async def poll():
    await db_init()
    offset = 0
    print(f"🤖 Bot polling: Her 3 saniyede")
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(f"{API}/getUpdates", json={"offset": offset, "timeout": 25}, timeout=30) as r:
                    data = await r.json()
            if data.get("ok") and data.get("result"):
                for upd in data["result"]:
                    offset = upd["update_id"] + 1
                    try:
                        if "message" in upd:
                            msg = upd["message"]
                            await handle_message(msg["chat"]["id"], msg.get("text", ""))
                        elif "callback_query" in upd:
                            cb = upd["callback_query"]
                            await answer_cb(cb["id"])
                            await handle_callback(cb["message"]["chat"]["id"], cb["data"], cb["message"]["message_id"])
                    except Exception as e:
                        print(f"ERR: {e}")
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Poll error: {e}")
            await asyncio.sleep(3)

def main():
    print("="*50)
    print("🤖 TMCELL Bot — POLLING + HEALTH")
    print(f"📱 @tmcellgozlegim_bot")
    print(f"🏥 Health: 0.0.0.0:{PORT}")
    print("="*50)
    Thread(target=start_health, daemon=True).start()
    asyncio.run(poll())

if __name__ == "__main__":
    main()
