"""
TMCELL Bot - hyzmat.tmcell.tm порталы аркалы баланс барламак
"""

import aiohttp
import re
from bs4 import BeautifulSoup

BASE_URL = "https://hyzmat.tmcell.tm"
LOGIN_URL = f"{BASE_URL}/ru-ru"
LOGIN_ACTION = f"{BASE_URL}/User"
HOME_URL = f"{BASE_URL}/ru-ru/Home"
BALANCE_URL = f"{BASE_URL}/ru-ru/Home/Balance"


async def check_balance(phone_number: str, password: str) -> dict:
    """
    hyzmat.tmcell.tm порталына гирип, баланс маглуматыны алмак.
    
    Args:
        phone_number: Соңкы 8 сан (кодсыз)
        password: 0831-ден SMS аркалы алан паролы
    
    Returns:
        {
            "success": bool,
            "balance": str | None,
            "details": dict | None,
            "error": str | None
        }
    """
    
    async with aiohttp.ClientSession() as session:
        try:
            # 1-нҗи äдим: Гириш сахыпасыны алмак (CSRF токен ве кукилер)
            async with session.get(LOGIN_URL, timeout=20) as resp:
                html = await resp.text()
                
                # CSRF токеныны формдан чыкармак
                soup = BeautifulSoup(html, "lxml")
                token_input = soup.find("input", {"name": "__RequestVerificationToken"})
                if not token_input:
                    return {"success": False, "error": "Giriş sahypasynda token tapylmady. Portal üýtgedilen bolmagy mümkin."}
                
                token = token_input.get("value", "")
                
                # Cookie'den hem token al
                cookie_token = None
                for key, morsel in resp.cookies.items():
                    if key == "__RequestVerificationToken":
                        cookie_token = morsel.value
                        break
            
            # 2-нҗи äдим: Login POST
            login_data = {
                "__RequestVerificationToken": token,
                "PhoneNumber": f"993{phone_number}",
                "Password": password
            }
            
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE_URL,
                "Referer": LOGIN_URL,
            }
            
            async with session.post(
                LOGIN_ACTION,
                data=login_data,
                headers=headers,
                timeout=20,
                allow_redirects=True
            ) as resp:
                result_html = await resp.text()
                final_url = str(resp.url)
            
            # 3-нҗи äдим: Гириш үстүнликлими барламак
            if "Личный кабинет" not in result_html and "balans" not in result_html.lower():
                # Гириш şowsuz bolan bolmagy mümkin
                if "неверный" in result_html.lower() or "nädogry" in result_html.lower() or "пароль" in result_html.lower():
                    return {"success": False, "error": "Nädogry telefon nomer ýa-da parol. Täzeden barlaň."}
                if "заблокирован" in result_html.lower() or "blokirlenen" in result_html.lower():
                    return {"success": False, "error": "Hasabyňyz 30 minutlyk blokirlendi. 5 gezek nädogry parol girizildi."}
            
            # 4-нҗи äдим: Баланс сахыпасыны алмак
            async with session.get(HOME_URL, timeout=20) as resp:
                home_html = await resp.text()
            
            # 5-нҗи äдим: HTML-ден баланс маглуматыны чыкармак
            balance_info = _parse_balance(home_html)
            
            if balance_info:
                return {
                    "success": True,
                    "balance": balance_info.get("balance", "N/A"),
                    "details": balance_info
                }
            
            # Eger-de esasy sahypada tapylmasa, Balance sahypasyna git
            async with session.get(BALANCE_URL, timeout=20) as resp:
                balance_html = await resp.text()
            
            balance_info = _parse_balance(balance_html)
            
            if balance_info:
                return {
                    "success": True,
                    "balance": balance_info.get("balance", "N/A"),
                    "details": balance_info
                }
            
            # Hiç zat tapylmasa
            return {
                "success": True,
                "balance": "Balans maglumaty tapylmady. El bilen *0800# ýazyň.",
                "details": None
            }
            
        except aiohttp.ClientError as e:
            return {"success": False, "error": f"Portal bilen baglanyşyk säwligi: {str(e)[:100]}"}
        except Exception as e:
            return {"success": False, "error": f"Garaşylmadyk säwlik: {str(e)[:100]}"}


def _parse_balance(html: str) -> dict | None:
    """
    HTML-den баланс маглуматларыны чыкармак.
    TMCELL порталындан: баланс, галан минутлар, SMS, трафик ве ş.m.
    """
    soup = BeautifulSoup(html, "lxml")
    result = {}
    
    # Метод 1: Таблица гөрнүшинде маглумат
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                key = cells[0].get_text(strip=True)
                value = cells[1].get_text(strip=True)
                if key and value:
                    result[key] = value
    
    # Метод 2: span/div etiketkalarynda баланс гөзlegi
    # "Баланс" я-да "Balans" сөзүни гөзлемек
    balance_patterns = [
        r'(?:Баланс|Balans|Balance)[:\s]*([\d.,]+\s*(?:manat|TMT|mnt)?)',
        r'(?:на счету|hasabyňyzda)[:\s]*([\d.,]+\s*(?:manat|TMT|mnt)?)',
        r'([\d.,]+)\s*(?:manat|TMT)',
    ]
    
    for pattern in balance_patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            result["Баланс"] = match.group(1).strip()
            break
    
    # Метод 3: Если в result уже что-то есть с ключом баланс
    for key in list(result.keys()):
        if any(word in key.lower() for word in ['баланс', 'balans', 'balance', 'счет', 'hasap']):
            result["Баланс"] = result[key]
            break
    
    if result:
        return result
    
    # Метод 4: Бүтин тексти сканирлемек
    text = soup.get_text(separator="\n", strip=True)
    lines = text.split("\n")
    
    for i, line in enumerate(lines):
        if any(word in line.lower() for word in ['баланс', 'balans', 'balance']):
            # Баланс хатдаки кеминде 3 хат асакдакылары ал
            result["Баланс"] = line
            for j in range(i+1, min(i+5, len(lines))):
                clean_line = lines[j].strip()
                if clean_line and len(clean_line) < 100:
                    # Гошмача маглумат болмагы мүмкин
                    pass
            break
    
    return result if result else None
