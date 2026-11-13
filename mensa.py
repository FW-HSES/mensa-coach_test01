import os, re, json, sys, datetime as dt
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

MODELL = "openai/gpt-oss-120b"
BASE = "https://sws2.maxmanager.xyz/"
AJAX = BASE + "inc/ajax-php_konnektor.inc.php"
GROQ = "https://api.groq.com/openai/v1"
KATS = ("veganer renner", "hauptgericht", "mensa special", "all time classics")
TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
HEAD = {"Origin": BASE.rstrip("/"), "Referer": BASE + "index.php?mode=bed",
        "X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0"}


def sauber(t):
    return " ".join(t.get_text(" ", strip=True).split()).replace("\xa0", " ")


def zahl(m):
    return float(m.group(1).replace(",", ".")) if m else None


def finde_mensen():
    gesucht = {"flandernstrasse": "FLANDERN", "stadtmitte": "STADTMITTE"}
    html = requests.get(BASE, headers=HEAD, timeout=30).text
    alle = re.findall(r"<option\s+value=['\"]([^'\"]*)['\"]\s*/?>\s*([^<]*)", html)
    ids = {}
    for wert, text in alle:
        for key, wort in gesucht.items():
            if wort in text.upper() and key not in ids:
                ids[key] = wert
    print("Mensa-Nummern:", ids)
    if len(ids) < 2:
        print("Auswahlliste:", alle)
        print("Startseite (Anfang):", html[:1500])
        sys.exit(1)
    return ids


def parse(html):
    soup, kat, out = BeautifulSoup(html, "html.parser"), None, []
    for row in soup.select(".row"):
        c = row.get("class", [])
        if "gruppenkopf" in c:
            kat = sauber(row).split(" PREIS ")[0].title()
        if "splMeal" not in c or not kat or not any(k in kat.lower() for k in KATS):
            continue
        text = sauber(row)
        labels = " ".join(
            (e.get("title") or e.get("alt") or "") for e in row.find_all(["img", "span"])
            if "foto" not in ((e.get("alt") or "") + (e.get("title") or "") + (e.get("src") or "")).lower()
        ).lower()
        sp = row.select_one(".mealText span, .splMealText span, .col-md-8 span, span")
        zl = r"(\d+(?:[.,]\d+)?)"
        preis = zahl(re.search(r"STUDIS\s*\|\s*" + zl + r"\s*(?:€|EUR)", text, re.I)
                     or re.search(r"€\s*" + zl + r"\s*/", text))
        vegan = "vegan" in labels
        out.append({
            "kategorie": kat, "name": sauber(sp) if sp else text,
