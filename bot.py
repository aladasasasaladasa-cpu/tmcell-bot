"""
TMCELL Bot — Çok hesap destekli, temiz tek dosya.
Polling + Health endpoint. Koyeb/Railway/Render'da 7/24 çalışır.

Gerekli ortam değişkenleri:
  TELEGRAM_BOT_TOKEN   (zorunlu) — Telegram bot token'ı
  PORT                 (isteğe bağlı, varsayılan 8000) — health endpoint portu
"""
import asyncio
import os
import re
import sys
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

import aiohttp
import aiosqlite
from bs4 import BeautifulSoup

# =========================================================
# KONFIGÜRASYON  (TOKEN asla kod içine gömülmez!)
# =========================================================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TOKEN:
    print("HATA: TELEGRAM_BOT_TOKEN ortam değişkeni tanımlı değil!")
    print("Kurulum için .env.example dosyasına bakın.")
    sys.exit(1)

API = f"https://api.telegram.org/bot{TOKEN}"
DB = os.path.join(os.path.dirname(__file__) or ".", "users.db")
PORT = int(os.environ.get("PORT", 8000))

# =========================================================
# HEALTH ENDPOINT  (uptime izleyicileri için)
# =========================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *args):
        pass

def start_health():
    HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever()

# =========================================================
# VERİTABANI  (çok hesap destekli)
# =========================================================
async def db_init():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                label TEXT DEFAULT '',
                phone TEXT NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_id INTEGER,
                balance TEXT,
                checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def db_get_accounts(uid):
    """Kullanıcının tüm hesaplarını döndürür."""
    async with aiosqlite.connect(DB) as db:
        c = await db.execute(
            "SELECT id, phone, password, label FROM accounts WHERE user_id=? ORDER BY id", (uid,))
        rows = await c.fetchall()
        return [{"id": r[0], "phone": r[1], "password": r[2], "label": r[3]} for r in rows]

async def db_get_account(aid, uid):
    async with aiosqlite.connect(DB) as db:
        c = await db.execute(
            "SELECT id, phone, password, label FROM accounts WHERE id=? AND user_id=?", (aid, uid))
        r = await c.fetchone()
        return {"id": r[0], "phone": r[1], "password": r[2], "label": r[3]} if r else None

async def db_add_account(uid, phone, pw):
    """Yeni hesap ekler, otomatik etiket atar (Hasap 1, Hasap 2, ...)."""
    n = len(await db_get_accounts(uid))
    label = f"Hasap {n + 1}"
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO accounts (user_id, label, phone, password) VALUES (?,?,?,?)",
            (uid, label, phone, pw))
        await db.commit()

async def db_update_account(aid, uid, phone, pw):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE accounts SET phone=?, password=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
            (phone, pw, aid, uid))
        await db.commit()

async def db_delete_account(aid, uid):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM accounts WHERE id=? AND user_id=?", (aid, uid))
        await db.execute("DELETE FROM history WHERE account_id=?", (aid,))
        await db.commit()

async def db_add_history(uid, aid, balance):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO history (user_id, account_id, balance) VALUES (?,?,?)",
            (uid, aid, balance))
        await db.commit()

async def db_last_balance(uid):
    async with aiosqlite.connect(DB) as db:
        c = await db.execute(
            "SELECT balance, checked FROM history WHERE user_id=? ORDER BY checked DESC, id DESC LIMIT 1",
            (uid,))
        r = await c.fetchone()
        return {"balance": r[0], "checked": r[1]} if r else None

# =========================================================
# TMCELL SCRAPER
# =========================================================
async def tmcell_check(phone, password):
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://hyzmat.tmcell.tm/ru-ru", timeout=20) as r:
                html = await r.text()
            soup = BeautifulSoup(html, "lxml")
            token = soup.find("input", {"name": "__RequestVerificationToken"})
            if not token:
                return {"ok": False, "err": "Portal elýeterli däl"}
            data = {
                "__RequestVerificationToken": token.get("value", ""),
                "PhoneNumber": f"993{phone}",
                "Password": password,
            }
            async with s.post("https://hyzmat.tmcell.tm/User", data=data,
                              headers={"Referer": "https://hyzmat.tmcell.tm/ru-ru"},
                              timeout=20, allow_redirects=True) as r:
                home = await r.text()
            low = home.lower()
            if "неверный" in low or "nädogry" in low:
                return {"ok": False, "err": "Nädogry telefon ýa-da parol"}
            if "заблок" in low or "blok" in low:
                return {"ok": False, "err": "Hasap 30 minut bloklandy"}

            soup2 = BeautifulSoup(home, "lxml")
            balance = "Tapylmady"
            details = {}
            for pat in [r'(?:Баланс|Balans)[:\s]*([\d.,]+\s*(?:manat|TMT|mnt)?)',
                        r'([\d.,]+)\s*(?:manat|TMT)', r'на счету[:\s]*([\d.,]+)']:
                m = re.search(pat, home, re.IGNORECASE)
                if m:
                    balance = m.group(1).strip()
                    break
            for t in soup2.find_all("table"):
                for row in t.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        k, v = cells[0].get_text(strip=True), cells[1].get_text(strip=True)
                        if k and v:
                            details[k] = v
                            if any(w in k.lower() for w in ['баланс', 'balans']):
                                balance = v
            if not details:
                for line in soup2.get_text().split("\n"):
                    if any(w in line.lower() for w in ['баланс', 'balans']):
                        balance = line
                        break
            return {"ok": True, "balance": balance, "details": details}
    except Exception as e:
        return {"ok": False, "err": f"Portal säwligi: {str(e)[:80]}"}

# =========================================================
# TELEGRAM API
# =========================================================
async def tg(method, data):
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{API}/{method}", json=data, timeout=15) as r:
            return await r.json()

async def send(chat_id, text, keyboard=None, inline=None):
    d = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        d["reply_markup"] = {"keyboard": keyboard, "resize_keyboard": True}
    if inline:
        d["reply_markup"] = {"inline_keyboard": inline}
    return await tg("sendMessage", d)

async def edit(chat_id, msg_id, text, inline=None):
    d = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "HTML"}
    if inline:
        d["reply_markup"] = {"inline_keyboard": inline}
    await tg("editMessageText", d)

async def delete(chat_id, msg_id):
    await tg("deleteMessage", {"chat_id": chat_id, "message_id": msg_id})

async def answer_cb(cb_id, text=""):
    await tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

# =========================================================
# KLAVYELER
# =========================================================
MAIN = [
    [{"text": "💰 Balansy barla"}, {"text": "⚙️ Hasap sazlamalary"}],
    [{"text": "📋 Soňky barlag"}, {"text": "ℹ️ Kömek"}],
]
SETTINGS = [
    [{"text": "➕ Hasap goş"}, {"text": "🗑 Hasap poz"}],
    [{"text": "🔙 Esasy menýu"}],
]
CANCEL = [[{"text": "❌ Goýbolsun et"}]]

WELCOME = (
    "🇹🇲 <b>TMCELL Balans Bot</b>\n\n"
    "Bu bot <b>TMCELL (Altyn Asyr)</b> balansyňyzy uzak aralykdan barlamaga kömek edýär.\n\n"
    "1️⃣ <b>Hasap goşuň</b> — ⚙️ Hasap sazlamalary → ➕ Hasap goş\n"
    "2️⃣ <b>Balansy barlaň</b> — 💰 Balansy barla\n\n"
    "⚠️ <b>Parol almak:</b> SIM-den <b>0831</b>-e boş SMS iberiň."
)

HELP = (
    "🆘 <b>KÖMEK</b>\n\n"
    "🔹 <b>Hasap goşmak:</b> ⚙️ → ➕ Hasap goş → nomer (soňky 8 san) → parol\n"
    "🔹 <b>Parol almak:</b> <b>0831</b>-e boş SMS iberiň, gelen paroly giriziň\n"
    "🔹 <b>Balans barlamak:</b> 💰 Balansy barla\n"
    "🔹 <b>Nomer görnüşi:</b> Soňky 8 san, mysal: <code>65123456</code>\n"
    "🔹 <b>Köp hasap:</b> Biraz hesap goşup, her birini aýry-aýry barlap bilersiňiz."
)

def phone_disp(phone):
    return f"+993******{phone[-4:]}"

def acc_button(acc):
    return f"{phone_disp(acc['phone'])} ({acc['label']})"

def acc_list_inline(accounts, cb_prefix, extra=None):
    """Hesap listesi inline düğmeleri. cb_prefix = 'check' / 'manage' / 'del'."""
    rows = [[{"text": acc_button(a), "callback_data": f"{cb_prefix}:{a['id']}"}] for a in accounts]
    if extra:
        rows.append(extra)
    return rows

# =========================================================
# DURUM MAKİNESİ  (hesap ekleme / güncelleme)
# =========================================================
# states[chat_id] = {"state": "phone"|"pw"|"confirm", "account_id": int|None,
#                     "phone": str, "pw": str}
states = {}

# =========================================================
# MESAJ İŞLEME
# =========================================================
async def handle_message(chat_id, text):
    if text == "/start":
        states.pop(chat_id, None)
        await send(chat_id, WELCOME, MAIN)

    elif text in ("/help", "ℹ️ Kömek"):
        states.pop(chat_id, None)
        await send(chat_id, HELP, MAIN)

    elif text == "💰 Balansy barla":
        states.pop(chat_id, None)
        accs = await db_get_accounts(chat_id)
        if not accs:
            await send(chat_id, "⚠️ Hiç hasap ýok!\n⚙️ → ➕ Hasap goş",
                       MAIN, [[{"text": "➕ Hasap goş", "callback_data": "add"}]])
            return
        if len(accs) == 1:
            await do_check(chat_id, accs[0], MAIN)
        else:
            await send(chat_id, "📱 <b>Haýsy hasaby barlamaly?</b>",
                       MAIN, acc_list_inline(accs, "check"))

    elif text == "📋 Soňky barlag":
        states.pop(chat_id, None)
        last = await db_last_balance(chat_id)
        if last:
            await send(chat_id,
                       f"📋 <b>Soňky barlag</b>\n🕐 {last['checked']}\n💰 <code>{last['balance']}</code>",
                       MAIN, [[{"text": "🔄 Täzeden", "callback_data": "refresh_last"}]])
        else:
            await send(chat_id, "📋 Entek barlag geçirilmedi.", MAIN)

    elif text == "⚙️ Hasap sazlamalary":
        states.pop(chat_id, None)
        await send(chat_id, "⚙️ <b>Hasap sazlamalary</b>\n\n👇 Saýlaň:", SETTINGS)

    elif text == "🔙 Esasy menýu":
        states.pop(chat_id, None)
        await send(chat_id, "🔙 Esasy menýu", MAIN)

    elif text == "➕ Hasap goş":
        start_add(chat_id)

    elif text == "🗑 Hasap poz":
        states.pop(chat_id, None)
        accs = await db_get_accounts(chat_id)
        if not accs:
            await send(chat_id, "Hasap ýok.", MAIN)
        elif len(accs) == 1:
            await ask_delete(chat_id, accs[0])
        else:
            await send(chat_id, "🗑 <b>Haýsy hasaby pozmaly?</b>",
                       MAIN, acc_list_inline(accs, "del"))

    elif text == "❌ Goýbolsun et":
        states.pop(chat_id, None)
        await send(chat_id, "❌ Goýbolsun edildi.", MAIN)

    elif chat_id in states:
        await handle_add_state(chat_id, text)

# =========================================================
# HESAP EKLEME / GÜNCELLEME DURUMU
# =========================================================
def start_add(chat_id, account_id=None):
    states[chat_id] = {"state": "phone", "account_id": account_id}
    asyncio.create_task(send(chat_id, "📱 Telefon nomeri giriziň (soňky 8 san, mysal: <code>65123456</code>):", CANCEL))

async def handle_add_state(chat_id, text):
    st = states[chat_id]
    if st["state"] == "phone":
        digits = "".join(c for c in text if c.isdigit())
        if len(digits) < 8:
            await send(chat_id, "⚠️ Azyndan 8 san giriziň!", CANCEL)
            return
        st["phone"] = digits[-8:]
        st["state"] = "pw"
        await send(chat_id, f"📱 +993{st['phone']}\n\nIndi <b>paroly</b> giriziň:", CANCEL)
    elif st["state"] == "pw":
        pw = text.strip()
        if len(pw) < 4:
            await send(chat_id, "⚠️ Parol gysga! Täzeden:", CANCEL)
            return
        st["pw"] = pw
        st["state"] = "confirm"
        action = "Täzele" if st["account_id"] else "Goş"
        await send(chat_id,
                   f"📋 <b>Tassyklaň</b> ({action})\n📱 +993{st['phone']}\n🔐 {'•' * len(pw)}",
                   None,
                   [[{"text": "✅ Tassykla", "callback_data": "confirm_yes"},
                     {"text": "❌ Goýbolsun", "callback_data": "confirm_no"}]])

# =========================================================
# BALANS KONTROLÜ
# =========================================================
async def do_check(chat_id, acc, menu=MAIN):
    tmp = await send(chat_id, "⏳ Barlanýar...", menu)
    try:
        await delete(chat_id, tmp["result"]["message_id"])
    except Exception:
        pass
    res = await tmcell_check(acc["phone"], acc["password"])
    if res["ok"]:
        await db_add_history(chat_id, acc["id"], res["balance"])
        txt = (f"💰 <b>BALANS</b>\n"
               f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
               f"📱 {acc_button(acc)}\n\n📱 <b>{res['balance']}</b>")
        if res.get("details"):
            txt += "\n\n📊 <b>Giňişleýin:</b>"
            for k, v in list(res["details"].items())[:6]:
                if k.lower() not in ('баланс', 'balans', 'balance'):
                    txt += f"\n▫️ {k}: {v}"
        await send(chat_id, txt, MAIN,
                   [[{"text": "🔄 Täzeden", "callback_data": f"check:{acc['id']}"}]])
    else:
        await send(chat_id, f"❌ <b>Şowsuz!</b>\n{res['err']}", MAIN,
                   [[{"text": "⚙️ Hasap sazlamalary", "callback_data": "back_settings"}]])

async def ask_delete(chat_id, acc):
    await send(chat_id,
               f"🗑 <b>Pozmak isleýärsiňizmi?</b>\n📱 {acc_button(acc)}",
               None,
               [[{"text": "✅ Hawa", "callback_data": f"del_yes:{acc['id']}"},
                 {"text": "❌ Ýok", "callback_data": "del_no"}]])

# =========================================================
# CALLBACK İŞLEME
# =========================================================
async def handle_callback(chat_id, data, msg_id):
    if data == "add":
        states.pop(chat_id, None)
        await delete(chat_id, msg_id)
        start_add(chat_id)

    elif data == "back_settings":
        await edit(chat_id, msg_id, "⚙️ <b>Hasap sazlamalary</b>\n\n👇 Saýlaň:", SETTINGS)

    elif data.startswith("check:"):
        aid = int(data.split(":")[1])
        acc = await db_get_account(aid, chat_id)
        if not acc:
            await edit(chat_id, msg_id, "⚠️ Hasap tapylmady.")
            return
        if data == f"check:{aid}" and msg_id:
            # Inline yenileme: aynı mesajı düzenle
            await edit(chat_id, msg_id, "⏳ Barlanýar...")
            res = await tmcell_check(acc["phone"], acc["password"])
            if res["ok"]:
                await db_add_history(chat_id, aid, res["balance"])
                txt = (f"💰 <b>BALANS</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                       f"📱 {acc_button(acc)}\n\n📱 <b>{res['balance']}</b>")
                await edit(chat_id, msg_id, txt,
                           [[{"text": "🔄 Täzeden", "callback_data": f"check:{aid}"}]])
            else:
                await edit(chat_id, msg_id, f"❌ {res['err']}")

    elif data == "refresh_last":
        u = await db_get_accounts(chat_id)
        if not u:
            await edit(chat_id, msg_id, "⚠️ Hasap ýok.")
            return
        acc = u[0]
        await edit(chat_id, msg_id, "⏳ Barlanýar...")
        res = await tmcell_check(acc["phone"], acc["password"])
        if res["ok"]:
            await db_add_history(chat_id, acc["id"], res["balance"])
            await edit(chat_id, msg_id, f"💰 <b>BALANS</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n📱 <b>{res['balance']}</b>",
                       [[{"text": "🔄 Täzeden", "callback_data": f"check:{acc['id']}"}]])
        else:
            await edit(chat_id, msg_id, f"❌ {res['err']}")

    elif data.startswith("del:"):
        aid = int(data.split(":")[1])
        acc = await db_get_account(aid, chat_id)
        if not acc:
            await edit(chat_id, msg_id, "⚠️ Hasap tapylmady.")
            return
        await ask_delete(chat_id, acc)

    elif data.startswith("del_yes:"):
        aid = int(data.split(":")[1])
        await db_delete_account(aid, chat_id)
        await edit(chat_id, msg_id, "✅ Hasap pozuldy!")
        await send(chat_id, "👇 Esasy menýu:", MAIN)

    elif data == "del_no":
        await edit(chat_id, msg_id, "❌ Pozmak goýbolsun edildi.")
        await send(chat_id, "👇 Esasy menýu:", MAIN)

    elif data == "confirm_yes":
        st = states.get(chat_id, {})
        if st.get("phone") and st.get("pw"):
            if st.get("account_id"):
                await db_update_account(st["account_id"], chat_id, st["phone"], st["pw"])
                await edit(chat_id, msg_id, f"✅ <b>HASAP TÄZELENDI!</b>\n📱 +993{st['phone']}")
            else:
                await db_add_account(chat_id, st["phone"], st["pw"])
                await edit(chat_id, msg_id, f"✅ <b>HASAP GOŞULDY!</b>\n📱 +993{st['phone']}")
            await send(chat_id, "👇 Indi balansy barlaň:", MAIN)
        states.pop(chat_id, None)

    elif data == "confirm_no":
        await edit(chat_id, msg_id, "❌ Goýbolsun edildi.")
        await send(chat_id, "👇 Esasy menýu:", MAIN)
        states.pop(chat_id, None)

# =========================================================
# POLLING LOOP
# =========================================================
async def poll():
    await db_init()
    offset = 0
    print(f"🤖 Bot polling başladı | @{TOKEN.split(':')[0]} | Health :{PORT}")
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(f"{API}/getUpdates",
                                  json={"offset": offset, "timeout": 25,
                                        "allowed_updates": ["message", "callback_query"]},
                                  timeout=30) as r:
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
                            await handle_callback(cb["message"]["chat"]["id"],
                                                  cb["data"], cb["message"]["message_id"])
                    except Exception as e:
                        print(f"Update hata: {e}")
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Poll hatası: {e}")
            await asyncio.sleep(3)

def main():
    print("=" * 50)
    print("🤖 TMCELL Bot — POLLING + HEALTH (çok hesap)")
    print(f"🏥 Health: 0.0.0.0:{PORT}")
    print("=" * 50)
    Thread(target=start_health, daemon=True).start()
    asyncio.run(poll())

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot durdy.")
