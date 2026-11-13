import os, re, json, sys, datetime as dt
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

MODELL = "llama-3.3-70b-versatile"
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
    ids, alle = {}, []
    for url in (BASE, BASE + "index.php?mode=bed"):
        html = requests.get(url, headers=HEAD, timeout=30).text
        for o in BeautifulSoup(html, "html.parser").find_all("option"):
            text = sauber(o)
            alle.append(f"{o.get('value')}={text}")
            for key, wort in gesucht.items():
                if wort in text.upper() and key not in ids:
                    ids[key] = o.get("value")
        if len(ids) == 2:
            break
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
            "preis_studierende": preis, "vegan": vegan,
            "vegetarisch": vegan or "vegetar" in labels,
            "kcal_100g": zahl(re.search(r"Brennwert:\s*[\d,.]+\s*kj\s*/\s*" + zl + r"\s*kcal", text, re.I)),
            "eiweiss_100g": zahl(re.search(r"Eiwei(?:ß|ss):\s*" + zl, text, re.I)),
        })
    return out


def bewerte(namen):
    liste = "\n".join(f"{i}. {n}" for i, n in enumerate(namen, 1))
    prompt = ("Bewerte diese Mensa-Gerichte für Studierende. Antworte nur als JSON im Format "
              '{"ergebnisse":[{"nr":1,"gesundheit":7,"kcal_portion":650,"begruendung":"max. 12 Wörter"}]}. '
              "gesundheit ist eine Zahl von 1 bis 10, kcal_portion eine Schätzung für eine Portion. "
              "Gerichte:\n" + liste)
    r = requests.post(GROQ + "/chat/completions", timeout=120,
                      headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]},
                      json={"model": MODELL, "temperature": 0.2,
                            "response_format": {"type": "json_object"},
                            "messages": [{"role": "user", "content": prompt}]})
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
    daten = json.loads(r.json()["choices"][0]["message"]["content"])
    return {e["nr"]: e for e in daten["ergebnisse"]}


def main():
    jetzt = dt.datetime.now(ZoneInfo("Europe/Berlin"))
    montag = jetzt.date() - dt.timedelta(days=jetzt.weekday())
    ids, ergebnis, erste_antwort = finde_mensen(), {}, None
    for key, loc in ids.items():
        tage = []
        for i in range(5):
            d = montag + dt.timedelta(days=i)
            payload = {"func": "make_spl", "locId": str(loc), "date": d.isoformat(), "lang": "de",
                       "startThisWeek": montag.isoformat(),
                       "startNextWeek": (montag + dt.timedelta(days=7)).isoformat()}
            r = requests.post(AJAX, data=payload, headers=HEAD, timeout=30)
            r.raise_for_status()
            erste_antwort = erste_antwort or r.text
            gerichte = parse(r.text)
            print(f"{key} {d.isoformat()} {TAGE[i]}: {len(gerichte)} Gerichte")
            tage.append({"datum": d.isoformat(), "wochentag": TAGE[i], "gerichte": gerichte})
        ergebnis[key] = tage
    namen = sorted({g["name"] for t in ergebnis.values() for tag in t for g in tag["gerichte"]})
    if not namen:
        print("0 Gerichte. Antwort (Anfang):", (erste_antwort or "")[:1500])
        sys.exit(1)
    try:
        bew = bewerte(namen)
    except Exception as e:
        print("Groq-Fehler:", e)
        try:
            m = requests.get(GROQ + "/models", timeout=30,
                             headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]})
            print("Verfügbare Modelle:", [x["id"] for x in m.json().get("data", [])])
        except Exception as e2:
            print("Modellliste nicht abrufbar:", e2)
        sys.exit(1)
    nr = {n: i for i, n in enumerate(namen, 1)}
    os.makedirs("data", exist_ok=True)
    for key, tage in ergebnis.items():
        for tag in tage:
            for g in tag["gerichte"]:
                b = bew.get(nr[g["name"]], {})
                g["gesundheit"] = b.get("gesundheit")
                g["kcal_portion"] = b.get("kcal_portion")
                g["begruendung"] = b.get("begruendung")
        with open(f"data/{key}.json", "w", encoding="utf-8") as f:
            json.dump({"stand": jetzt.isoformat(timespec="seconds"), "tage": tage},
                      f, ensure_ascii=False, indent=1)
    print("Fertig:", len(namen), "Gerichte bewertet")


main()
