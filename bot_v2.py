"""
TMCELL Bot v2 — Sıfırdan, sadece aiohttp ile.
KÜTÜPHANE YOK. KOPMA YOK. SUSMA YOK.
"""
import asyncio
import aiohttp
import json
import os
import aiosqlite
import re
from datetime import datetime
from bs4 import BeautifulSoup

TOKEN = "8843044615:AAENf7YOQ-1IVBWQtzXVeZFmrzoi35PathI"
API = f"https://api.telegram.org/bot{TOKEN}"
DB = os.path.join(os.path.dirname(__file__), "users.db")

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
    """hyzmat.tmcell.tm — баланс барламак"""
    try:
        async with aiohttp.ClientSession() as s:
            # login page
            async with s.get("https://hyzmat.tmcell.tm/ru-ru", timeout=20) as r:
                html = await r.text()
            soup = BeautifulSoup(html, "lxml")
            token = soup.find("input", {"name": "__RequestVerificationToken"})
            if not token:
                return {"ok": False, "err": "Portal elýeterli däl"}
            token_val = token.get("value", "")

            # login POST
            data = {"__RequestVerificationToken": token_val, "PhoneNumber": f"993{phone}", "Password": password}
            async with s.post("https://hyzmat.tmcell.tm/User", data=data,
                              headers={"Referer": "https://hyzmat.tmcell.tm/ru-ru"},
                              timeout=20, allow_redirects=True) as r:
                home = await r.text()

            if "nädogry" in home.lower() or "неверный" in home.lower() or "пароль" in home.lower():
                return {"ok": False, "err": "Nädogry telefon ýa-da parol"}
            if "blok" in home.lower() or "заблок" in home.lower():
                return {"ok": False, "err": "Hasap 30 minut bloklandy"}

            # parse balance
            text = BeautifulSoup(home, "lxml").get_text(separator="\n", strip=True)
            balance = "Tapylmady"
            details = {}

            # Scan for balance patterns
            for pat in [r'(?:Баланс|Balans)[:\s]*([\d.,]+\s*(?:manat|TMT|mnt)?)',
                        r'([\d.,]+)\s*(?:manat|TMT)',
                        r'на счету[:\s]*([\d.,]+)']:
                m = re.search(pat, home, re.IGNORECASE)
                if m:
                    balance = m.group(1).strip()
                    break

            # Try table-based
            tbl = BeautifulSoup(home, "lxml").find_all("table")
            for t in tbl:
                for row in t.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        k, v = cells[0].get_text(strip=True), cells[1].get_text(strip=True)
                        if k and v:
                            details[k] = v
                            if any(w in k.lower() for w in ['баланс', 'balans', 'balance']):
                                balance = v

            if not details:
                # fallback: scan lines
                lines = text.split("\n")
                for i, line in enumerate(lines):
                    if any(w in line.lower() for w in ['баланс', 'balans']):
                        balance = line
                        for j in range(i+1, min(i+5, len(lines))):
                            if lines[j].strip():
                                details[f"Maglumat {j-i}"] = lines[j].strip()

            return {"ok": True, "balance": balance, "details": details}

    except Exception as e:
        return {"ok": False, "err": f"Portal säwligi: {str(e)[:80]}"}

# ========== TELEGRAM API ==========
async def tg(method, data):
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{API}/{method}", json=data, timeout=15) as r:
            return await r.json()

async def send_msg(chat_id, text, keyboard=None, inline=None, parse="HTML"):
    d = {"chat_id": chat_id, "text": text, "parse_mode": parse}
    if keyboard:
        d["reply_markup"] = {"keyboard": keyboard, "resize_keyboard": True}
    if inline:
        d["reply_markup"] = {"inline_keyboard": inline}
    return await tg("sendMessage", d)

async def answer_cb(cb_id, text=""):
    await tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

async def edit_msg(chat_id, msg_id, text, inline=None):
    d = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if inline:
        d["reply_markup"] = {"inline_keyboard": inline}
    await tg("editMessageText", d)

async def delete_msg(chat_id, msg_id):
    await tg("deleteMessage", {"chat_id": chat_id, "message_id": msg_id})

# ========== KEYBOARDS ==========
MAIN_MENU = [
    [{"text": "💰 Balansy barla"}, {"text": "⚙️ Hasap sazlamalary"}],
    [{"text": "📋 Soňky barlag"}, {"text": "ℹ️ Kömek"}],
]
SETTINGS_MENU = [
    [{"text": "🔑 Hasaby täzele"}, {"text": "🗑 Hasaby poz"}],
    [{"text": "🔙 Esasy menýu"}],
]
CANCEL_MENU = [[{"text": "❌ Goýbolsun et"}]]

# ========== TEXT ==========
WELCOME = """🇹🇲 <b>TMCELL Balans Bota hoş geldiňiz!</b>

Bu bot <b>TMCELL (Altyn Asyr)</b> balansyňyzy <b>uzak aralykdan</b> barlamaga kömek edýär.

📌 <b>Nädip işleýär:</b>
1️⃣ <b>Hasap dörediň</b> — ⚙️ Hasap sazlamalary → Hasaby täzele
2️⃣ <b>Balansy barlaň</b> — 💰 Balansy barla düwmesine basyň

⚠️ <b>Paroly nädip almaly?</b> SIM kartyňyzdan <b>0831</b> nomerine boş SMS iberiň!"""

HELP = """🆘 <b>KÖMEK</b>

🔹 <b>Hasap döretmek:</b> ⚙️ → 🔑 Hasaby täzele → nomer (soňky 8 san) → parol

🔹 <b>Parol almak:</b> <b>0831</b>-e boş SMS iberiň, gelen paroly bota giriziň

🔹 <b>Balans barlamak:</b> 💰 Balansy barla düwmesine basyň

🔹 <b>Nomer görnüşi:</b> Soňky 8 san, mysal: <code>65123456</code>"""

# ========== MAIN LOGIC ==========
user_states = {}  # {user_id: {"state": "...", "phone": "...", "password": "..."}}

async def handle_update(upd):
    """Bütin update'leri işlemek — asyn 비동기, hiç haçan bloklanmaýar"""
    try:
        if "message" in upd:
            msg = upd["message"]
            chat_id = msg["chat"]["id"]
            text = msg.get("text", "")
            await handle_message(chat_id, text, msg)
        elif "callback_query" in upd:
            cb = upd["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            data = cb["data"]
            msg_id = cb["message"]["message_id"]
            await answer_cb(cb["id"])
            await handle_callback(chat_id, data, msg_id, cb)
    except Exception as e:
        print(f"ERROR in handle_update: {e}")

async def handle_message(chat_id, text, msg):
    if text == "/start":
        user_states.pop(chat_id, None)
        await send_msg(chat_id, WELCOME, MAIN_MENU)

    elif text == "/help" or text == "ℹ️ Kömek":
        user_states.pop(chat_id, None)
        await send_msg(chat_id, HELP, MAIN_MENU)

    elif text == "💰 Balansy barla":
        user_states.pop(chat_id, None)
        user = await db_get(chat_id)
        if not user:
            await send_msg(chat_id, "⚠️ Ilki <b>hasap döretmeli!</b>\n\n⚙️ Hasap sazlamalary → 🔑 Hasaby täzele",
                          MAIN_MENU,
                          [[{"text": "🔑 Hasaby döret", "callback_data": "setup"}],
                           [{"text": "ℹ️ Paroly nädip almaly?", "callback_data": "parol_help"}]])
            return
        tmp = await send_msg(chat_id, "⏳ Balans barlanýar...", MAIN_MENU)
        res = await tmcell_check(user["phone"], user["password"])
        await delete_msg(chat_id, tmp["result"]["message_id"])

        if res["ok"]:
            bal = res["balance"]
            det = res.get("details", {})
            txt = f"💰 <b>BALANS</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n📱 <b>{bal}</b>"
            if det:
                txt += "\n\n📊 <b>Giňişleýin:</b>"
                for k, v in list(det.items())[:5]:
                    if k.lower() not in ['баланс', 'balans', 'balance']:
                        txt += f"\n▫️ {k}: {v}"
            await db_add_history(chat_id, bal)
            await send_msg(chat_id, txt, MAIN_MENU,
                          [[{"text": "🔄 Täzeden barla", "callback_data": "refresh"}]])

        else:
            await send_msg(chat_id, f"❌ <b>Şowsuz!</b>\n{res['err']}", MAIN_MENU,
                          [[{"text": "🔑 Hasaby täzele", "callback_data": "setup"}]])

    elif text == "📋 Soňky barlag":
        user_states.pop(chat_id, None)
        last = await db_last_balance(chat_id)
        if last:
            await send_msg(chat_id,
                f"📋 <b>Soňky barlag</b>\n🕐 {last['checked']}\n💰 <code>{last['balance']}</code>",
                MAIN_MENU, [[{"text": "🔄 Täzeden barla", "callback_data": "refresh"}]])
        else:
            await send_msg(chat_id, "📋 Entek barlag geçirilmedi.", MAIN_MENU)

    elif text == "⚙️ Hasap sazlamalary":
        user_states.pop(chat_id, None)
        user = await db_get(chat_id)
        if user:
            mp = f"******{user['phone'][-4:]}"
            await send_msg(chat_id,
                f"⚙️ <b>Hasap sazlamalary</b>\n📱 +993{mp}\n🔐 {'•'*len(user['password'])}\n\n👇 Saýlaň:", SETTINGS_MENU)
        else:
            await send_msg(chat_id, "⚙️ <b>Hasap sazlamalary</b>\n\n⚠️ Hasap döredilmedi.\n👇 Saýlaň:", SETTINGS_MENU)

    elif text == "🔙 Esasy menýu":
        user_states.pop(chat_id, None)
        await send_msg(chat_id, "🔙 Esasy menýu:", MAIN_MENU)

    elif text == "🔑 Hasaby täzele":
        user_states[chat_id] = {"state": "waiting_phone"}
        await send_msg(chat_id, "📱 <b>Telefon nomeriňizi</b> giriziň.\nSoňky 8 san (mysal: <code>65123456</code>)\n\n❌ Goýbolsun etmek üçin düwmä basyň.", CANCEL_MENU)

    elif text == "🗑 Hasaby poz":
        user_states.pop(chat_id, None)
        user = await db_get(chat_id)
        if user:
            await send_msg(chat_id, "⚠️ Hasabyňyzy pozmak isleýärsiňizmi?", None,
                          [[{"text": "✅ Hawa, poz", "callback_data": "del_yes"},
                            {"text": "❌ Ýok", "callback_data": "del_no"}]])
        else:
            await send_msg(chat_id, "Hasabyňyz ýok.", MAIN_MENU)

    elif text == "❌ Goýbolsun et":
        user_states.pop(chat_id, None)
        await send_msg(chat_id, "❌ Goýbolsun edildi.", MAIN_MENU)

    elif chat_id in user_states:
        state = user_states[chat_id]
        if state["state"] == "waiting_phone":
            digits = ''.join(c for c in text if c.isdigit())
            if len(digits) < 8:
                await send_msg(chat_id, "⚠️ Azyndan 8 san giriziň!", CANCEL_MENU)
                return
            state["phone"] = digits[-8:]
            state["state"] = "waiting_password"
            await send_msg(chat_id,
                f"📱 <b>+993{state['phone']}</b>\n\nIndi <b>parolyňyzy</b> giriziň.\n\n🔑 <b>Paroly nädip almaly?</b>\n<b>0831</b>-e boş SMS iberiň!", CANCEL_MENU)

        elif state["state"] == "waiting_password":
            pw = text.strip()
            if len(pw) < 4:
                await send_msg(chat_id, "⚠️ Parol gysga! Täzeden:", CANCEL_MENU)
                return
            state["password"] = pw
            state["state"] = "confirm"
            await send_msg(chat_id,
                f"📋 <b>Tassyklamak</b>\n📱 +993{state['phone']}\n🔐 {'•'*len(pw)}",
                None,
                [[{"text": "✅ Tassykla", "callback_data": "confirm_yes"},
                  {"text": "❌ Goýbolsun", "callback_data": "confirm_no"}]])


async def handle_callback(chat_id, data, msg_id, cb):
    if data == "setup":
        user_states[chat_id] = {"state": "waiting_phone"}
        await delete_msg(chat_id, msg_id)
        await send_msg(chat_id, "📱 Telefon nomeriňizi giriziň (soňky 8 san):", CANCEL_MENU)

    elif data == "parol_help":
        await edit_msg(chat_id, msg_id,
            "🔑 <b>Parol almak:</b>\n\n1️⃣ SIM kartyňyzdan\n2️⃣ <b>0831</b>-e boş SMS iberiň\n3️⃣ Gelen paroly bota giriziň")

    elif data == "refresh":
        user = await db_get(chat_id)
        if not user:
            await edit_msg(chat_id, msg_id, "⚠️ Hasap ýok.")
            return
        await edit_msg(chat_id, msg_id, "⏳ Barlanýar...")
        res = await tmcell_check(user["phone"], user["password"])
        if res["ok"]:
            bal = res["balance"]
            await db_add_history(chat_id, bal)
            await edit_msg(chat_id, msg_id,
                f"💰 <b>BALANS</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n📱 <b>{bal}</b>",
                [[{"text": "🔄 Täzeden barla", "callback_data": "refresh"}]])
        else:
            await edit_msg(chat_id, msg_id, f"❌ {res['err']}")

    elif data == "del_yes":
        await db_del(chat_id)
        await edit_msg(chat_id, msg_id, "✅ Hasap pozuldy!")

    elif data == "del_no":
        await edit_msg(chat_id, msg_id, "❌ Pozmak goýbolsun edildi.")

    elif data == "confirm_yes":
        st = user_states.get(chat_id, {})
        if st.get("phone") and st.get("password"):
            await db_save(chat_id, st["phone"], st["password"])
            await edit_msg(chat_id, msg_id,
                f"✅ <b>HASAP DÖREDILDI!</b>\n📱 +993{st['phone']}\n\nIndi 💰 Balansy barlaň!")
            await send_msg(chat_id, "👇 Esasy menýu:", MAIN_MENU)
        user_states.pop(chat_id, None)

    elif data == "confirm_no":
        await edit_msg(chat_id, msg_id, "❌ Goýbolsun edildi.")
        await send_msg(chat_id, "👇 Esasy menýu:", MAIN_MENU)
        user_states.pop(chat_id, None)


# ========== POLLING LOOP ==========
async def main():
    await db_init()
    print("=" * 50)
    print("🤖 TMCELL Bot v2 — BAŞLADY!")
    print(f"📱 @tmcellgozlegim_bot")
    print("=" * 50)

    offset = 0
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(f"{API}/getUpdates",
                                  json={"offset": offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]},
                                  timeout=30) as r:
                    data = await r.json()

            if data.get("ok") and data.get("result"):
                for upd in data["result"]:
                    offset = upd["update_id"] + 1
                    asyncio.create_task(handle_update(upd))
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Poll error: {e}")
            await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot durdy.")
