# 🤖 TMCELL Balans Bot

TMCELL (Altyn Asyr) abonentleri üçin **Telegram balans barlag bota**.
Birden köp TMCELL hasabyňyzy dolandyryp, balansyňyzy uzak aralykdan barlaň.

## ✨ Aýratynlyklar

- 💰 **Balans barlamak** — hyzmat.tmcell.tm portalyndan real-time balans
- 📚 **Köp hasap** — bir ulanyjy birnäçe TMCELL hasabyny aýry-aýry dolandyryp bilýär
- 📋 **Soňky barlag** — iň soňky balans maglumaty
- ⚙️ **Hasap sazlamalary** — hasap goşmak, täzelemek, pozmak
- 🔒 **Gizlin token** — token kod içinde DÄL, ortam değişkeninden okunýar
- 🏥 **Health endpoint** — uptime izlemesi üçin (port 8000)

## 📁 Faýllar

| Faýl | Düşündiriş |
|------|-----------|
| `bot.py` | **Esasy bot** (polling + health, çok hasap) |
| `tmcell_api.py` | TMCELL scraper moduly |
| `database.py` | Veritabanı moduly |
| `Dockerfile` | Docker/containers üçin |
| `Procfile` | Koyeb/Render buildpack üçin |
| `koyeb.yaml` | Koyeb otomatik config |
| `render.yaml` | Render Blueprint (eskiden galan) |

## 🚀 Işlediş

### Lokal (test)

```bash
cp .env.example .env      # token'ýňyzy .env-e ýazyň
pip install -r requirements.txt
python bot.py
```

> ⚠️ Token kodu içine ýazmaň! Hemme zat `TELEGRAM_BOT_TOKEN` ortam değişkeninden okunýar.

## ☁️ 7/24 çalşyrmak — Koyeb (üstünlikli 7/24, mugt)

Koyeb mugt `nano` instance bilen **hemişe açyk** (always-on) 7/24 işleýär.

**Dashboard üsti bilen (iň aňsat):**

1. [koyeb.com](https://koyeb.com)-de akkaunt açyň, GitHub-a birikdiriň.
2. **Create App** → GitHub deposyny saýlaň (`tmcell-bot`).
3. **Builder**: `Docker` (Dockerfile bar) saýlaň.
4. **Instance**: `nano` saýlaň.
5. **Environment variables** bölüminde:
   - `TELEGRAM_BOT_TOKEN` = `<siziň token>` (BotFather'dan)
   - `PORT` = `8000`
6. **Deploy** basyň. Bot düşünýänçä 7/24 işleýär.

**Config faýly bilen (koyeb.yaml):** Koyeb `koyeb.yaml` bar bolsa
dashboardda "Create App" edende avtomatik tanap alýar.

### Beýleki platformalar

- **Railway**: Dockerfile-ny tanap alýar, env değişkenini set ediň.
- **Render**: `render.yaml` bar, env değişkeni (token) set ediň.
  ⚠️ Render mugt plan uzak işlemeýänçe "uyku" (spin-down) edip bilýär.

## 🔑 Token nireden?

1. Telegram-da [@BotFather](https://t.me/BotFather)-a ýazyň.
2. `/newbot` → at beriň → token alyň.
3. Token-y platforma panelinde `TELEGRAM_BOT_TOKEN` hökmünde goýuň.

## ⚠️ Howpsuzlyk

Bot tokeny **kod içine gömülipdir** (eski faýllarda) we GitHub-a ýazylýar.
Eger repo açyk bolsa, token-a başgalar girip biler. Şonuň üçin:

1. Token-ýňyzy @BotFather-da täzeläň (`/revoke`).
2. Täze token-y diňe platforma env değişkeninde saklaň.

## 🛠 Gelişme

Bot `bot.py` bir faýlda. Esasy bölümler:

- **DB**: `accounts` (çok hasap) + `history` tablalary
- **Scraper**: `tmcell_check()` — hyzmat.tmcell.tm login + balans parse
- **Bot**: mesaj/callback işleýiş durum makinesi
- **Polling**: `getUpdates` bilen 3 sanyýede bir barlaýar
