#!/usr/bin/env python3
"""
Diák-lehetőség gyűjtő
---------------------
Weboldalakról és RSS-csatornákról összegyűjti az 1–13. évfolyamos diákoknak
szóló kreatív pályázatokat, versenyeket, mobilitási és továbbtanulási
lehetőségeket, eseményeket. A nyers szövegből a Claude API készít egységes
adatot, az eredmény az adatok.json fájlba kerül.

Használat:
    python gyujto.py                  # minden aktív forrás
    python gyujto.py --csak "pafi"    # csak azok a források, amelyek nevében szerepel
    python gyujto.py --kenyszerit     # akkor is feldolgoz, ha az oldal nem változott
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import anthropic
import feedparser
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------- beállítások
GYOKER = Path(__file__).resolve().parent
FORRASOK_FAJL = GYOKER / "forrasok.json"
ADAT_FAJL = GYOKER / "adatok.json"
ARCHIVUM_FAJL = GYOKER / "archivum.json"
ALLAPOT_FAJL = GYOKER / "allapot.json"

MODELL = os.environ.get("CLAUDE_MODELL", "claude-haiku-4-5-20251001")
AUTO_JOVAHAGYAS = os.environ.get("AUTO_JOVAHAGYAS", "0") == "1"
USER_AGENT = os.environ.get(
    "GYUJTO_USER_AGENT", "DiakLehetosegGyujto/1.0 (oktatasi celu, nem kereskedelmi)"
)
MAX_SZOVEG = 20_000          # ennyi karaktert küldünk forrásonként a Claude-nak
KESLELTETES_MP = 3           # szünet két letöltés között (udvariasság)
IDOKORLAT_MP = 30            # letöltési időkorlát
NEM_LATOTT_NAP = 60         # dátum nélküli tétel (pl. heti szakkör) archiválódik, ha ennyi napja nem szerepel a forrásban

KATEGORIAK = ["kreativ_palyazat", "verseny", "mobilitas", "tovabbtanulas", "esemeny", "szabadido", "egyeb"]

# --------------------------------------------------------- Claude-utasítások
ESZKOZ = {
    "name": "lehetosegek_mentese",
    "description": "A weboldal szövegében talált, diákoknak szóló lehetőségek mentése.",
    "input_schema": {
        "type": "object",
        "properties": {
            "lehetosegek": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cim": {"type": "string", "description": "A lehetőség neve."},
                        "kategoria": {"type": "string", "enum": KATEGORIAK},
                        "osszefoglalo": {
                            "type": "string",
                            "description": "1–2 mondat a saját szavaiddal, legfeljebb 300 karakter.",
                        },
                        "evfolyam_min": {"type": "integer", "minimum": 1, "maximum": 13},
                        "evfolyam_max": {"type": "integer", "minimum": 1, "maximum": 13},
                        "hatarido": {"type": "string", "description": "ÉÉÉÉ-HH-NN, vagy üres."},
                        "esemeny_datum": {"type": "string", "description": "ÉÉÉÉ-HH-NN, vagy üres."},
                        "helyszin": {"type": "string", "description": "Város, ország, 'online', vagy üres."},
                        "koltseg": {"type": "string", "description": "Pl. 'ingyenes', '5000 Ft', vagy üres."},
                        "szervezo": {"type": "string"},
                        "idopont": {"type": "string", "description": "Szöveges időpont rendszeres programnál, pl. 'minden hétfő 16–17', vagy üres."},
                        "link": {"type": "string", "description": "A szövegben szereplő URL."},
                    },
                    "required": ["cim", "kategoria", "osszefoglalo", "evfolyam_min", "evfolyam_max", "link"],
                },
            }
        },
        "required": ["lehetosegek"],
    },
}


def rendszer_utasitas() -> str:
    ma = dt.date.today().isoformat()
    return f"""Magyarországi általános és középiskolás diákoknak (1–13. évfolyam) szóló lehetőségeket gyűjtesz. A mai dátum: {ma}.

A kapott weboldal-szövegből válogasd ki azokat a tételeket, amelyekre diákok maguk (vagy szüleik, tanáraik révén) jelentkezhetnek:
- kreativ_palyazat: rajz, fotó, irodalmi, zenei, film, képregény stb. pályázat
- verseny: tanulmányi, tudományos, sport- vagy tehetségverseny
- mobilitas: külföldi tanulás, csereprogram, nyelvi vagy nemzetközi tábor, ösztöndíj diákoknak
- tovabbtanulas: nyílt nap, felvételi, középiskolai vagy egyetemi előkészítő, nyári egyetem középiskolásoknak
- esemeny: egyszeri előadás, fesztivál, workshop, kiállítás, múzeumi vagy családi program, amelyen gyerekek is részt vesznek
- szabadido: rendszeres szakkör, klub, sportfoglalkozás, tánc- vagy zenecsoport, hazai tábor, napközis tábor
- egyeb: minden más, diákoknak szóló lehetőség

Hagyd ki: az intézményeknek, pedagógusoknak, egyetemistáknak, vállalkozásoknak, csak felnőtteknek vagy időseknek, illetve csak óvodásoknak szóló kiírásokat; a lakossági hirdetményeket, testületi üléseket, álláshirdetéseket; a már lejárt tételeket; a menüpontokat, hirdetéseket.
A családi programokat vedd fel, ha iskolás gyerekek is részt vehetnek rajtuk.
A 18–30 éveseknek szóló (pl. Eurodesk, Erasmus+) lehetőségeket csak akkor vedd fel, ha 18–19 éves középiskolások is jelentkezhetnek; ilyenkor az évfolyam 12–13.

Évfolyam: ha életkor van megadva, számold át (évfolyam ≈ életkor − 6, pl. 10 éves ≈ 4. évfolyam), és szorítsd 1–13 közé. Ha nincs megadva, becsüld a leírásból ("alsós" = 1–4, "felsős" = 5–8, "középiskolás" = 9–13, "általános iskolás" = 1–8).

Rendszeres programnál (pl. heti szakkör) a határidő és az eseménydátum maradjon üres, az időpontot az idopont mezőbe írd.
Az összefoglalót a saját szavaiddal írd, ne másold át a szöveget.
A link a lehetőség saját részletes oldalára mutasson, ha ilyen szerepel a szövegben (a <...> közötti URL-ek). Csak ténylegesen szereplő URL-t használj, soha ne találj ki. Ha nincs saját link, a forrásoldal URL-jét add meg.
Amit nem tudsz biztosan, hagyd üresen. Ha nincs releváns tétel, üres listát adj vissza."""


# ------------------------------------------------------------- segédfüggvények
def betolt(fajl: Path, alapertek):
    if fajl.exists():
        with open(fajl, encoding="utf-8") as f:
            return json.load(f)
    return alapertek


def ment(fajl: Path, adat) -> None:
    with open(fajl, "w", encoding="utf-8") as f:
        json.dump(adat, f, ensure_ascii=False, indent=2)
        f.write("\n")


def ujjlenyomat(szoveg: str) -> str:
    return hashlib.sha256(szoveg.encode("utf-8")).hexdigest()


def normal_link(link: str) -> str:
    link = (link or "").strip().lower()
    link = re.sub(r"^https?://(www\.)?", "", link)
    return link.rstrip("/")


def normal_cim(cim: str) -> str:
    return re.sub(r"[^0-9a-záéíóöőúüű]+", "", (cim or "").lower())


def datum_vagy_none(ertek):
    if not ertek:
        return None
    try:
        return dt.date.fromisoformat(str(ertek).strip()[:10]).isoformat()
    except ValueError:
        return None


def robots_engedi(url: str) -> bool:
    p = urlparse(url)
    rp = robotparser.RobotFileParser()
    rp.set_url(f"{p.scheme}://{p.netloc}/robots.txt")
    try:
        rp.read()
    except Exception:
        return True  # ha a robots.txt nem érhető el, az általános szabály: szabad
    return rp.can_fetch(USER_AGENT, url)


# -------------------------------------------------------------- letöltés
def html_szovegge(html: str, alap_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for elem in soup(["script", "style", "noscript", "nav", "footer", "form", "iframe", "svg"]):
        elem.decompose()
    # a linkeket a szövegben hagyjuk, hogy Claude a részletes oldalra mutathasson
    for a in soup.find_all("a", href=True):
        href = urljoin(alap_url, a["href"])
        if href.startswith("http"):
            a.append(f" <{href}>")
    fo = soup.find("main") or soup.find("article") or soup.body or soup
    sorok = [s.strip() for s in fo.get_text("\n").splitlines() if s.strip()]
    return "\n".join(sorok)[:MAX_SZOVEG]


def rss_szovegge(tartalom: bytes) -> str:
    feed = feedparser.parse(tartalom)
    reszek = []
    for e in feed.entries[:40]:
        leiras = BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ", strip=True)
        reszek.append(
            f"CÍM: {e.get('title', '')}\nLINK: <{e.get('link', '')}>\n"
            f"MEGJELENT: {e.get('published', '')}\n{leiras}"
        )
    return "\n\n".join(reszek)[:MAX_SZOVEG]


def letolt(session: requests.Session, forras: dict) -> str:
    url = forras["url"]
    if not robots_engedi(url):
        raise PermissionError("a robots.txt nem engedi a letöltést")
    valasz = session.get(url, timeout=IDOKORLAT_MP)
    valasz.raise_for_status()
    if forras.get("tipus") == "rss":
        return rss_szovegge(valasz.content)
    valasz.encoding = valasz.apparent_encoding or valasz.encoding
    return html_szovegge(valasz.text, url)


# ------------------------------------------------------------ Claude-hívás
def kinyer(kliens: anthropic.Anthropic, forras: dict, szoveg: str) -> list:
    valasz = kliens.messages.create(
        model=MODELL,
        max_tokens=8000,
        system=rendszer_utasitas(),
        tools=[ESZKOZ],
        tool_choice={"type": "tool", "name": ESZKOZ["name"]},
        messages=[{
            "role": "user",
            "content": (
                f"Forrás: {forras['nev']}\nForrásoldal URL: {forras['url']}\n"
                + (f"Megjegyzés ehhez a forráshoz: {forras['megjegyzes']}\n" if forras.get("megjegyzes") else "")
                + f"\n---\n{szoveg}"
            ),
        }],
    )
    for blokk in valasz.content:
        if blokk.type == "tool_use":
            return blokk.input.get("lehetosegek", []) or []
    return []


# ------------------------------------------------------ tisztítás, összefésülés
def tisztit(t: dict, forras_url: str):
    cim = (t.get("cim") or "").strip()
    link = (t.get("link") or "").strip()
    if not cim:
        return None
    if not link.startswith("http"):
        link = forras_url
    try:
        emin = max(1, min(13, int(t.get("evfolyam_min") or 1)))
        emax = max(1, min(13, int(t.get("evfolyam_max") or 13)))
    except (TypeError, ValueError):
        emin, emax = 1, 13
    if emin > emax:
        emin, emax = emax, emin
    kategoria = t.get("kategoria") if t.get("kategoria") in KATEGORIAK else "egyeb"
    hatarido = datum_vagy_none(t.get("hatarido"))
    ma = dt.date.today().isoformat()
    if hatarido and hatarido < ma:
        return None  # már lejárt

    def s(kulcs, hossz=200):
        ertek = (t.get(kulcs) or "").strip()
        return ertek[:hossz] or None

    return {
        "cim": cim[:200],
        "kategoria": kategoria,
        "osszefoglalo": s("osszefoglalo", 400),
        "evfolyam_min": emin,
        "evfolyam_max": emax,
        "hatarido": hatarido,
        "esemeny_datum": datum_vagy_none(t.get("esemeny_datum")),
        "helyszin": s("helyszin"),
        "koltseg": s("koltseg"),
        "szervezo": s("szervezo"),
        "idopont": s("idopont"),
        "link": link,
    }


def osszefesul(tetelek: list, ujak: list, forras: dict) -> list:
    ma = dt.date.today().isoformat()
    link_index = {normal_link(t["link"]): t for t in tetelek}
    cim_index = {normal_cim(t["cim"]): t for t in tetelek}
    hozzaadott = []
    for nyers in ujak:
        t = tisztit(nyers, forras["url"])
        if not t:
            continue
        # a forrásoldal saját linkje nem egyedi azonosító, ott csak a cím számít
        sajat_link = normal_link(t["link"]) != normal_link(forras["url"])
        meglevo = (link_index.get(normal_link(t["link"])) if sajat_link else None) \
            or cim_index.get(normal_cim(t["cim"]))
        if meglevo:
            for k, v in t.items():  # csak az üres mezőket töltjük ki, a kézi javítás megmarad
                if v and not meglevo.get(k):
                    meglevo[k] = v
            meglevo["utoljara_latva"] = ma
            continue
        t.update({
            "id": hashlib.sha1((normal_link(t["link"]) + normal_cim(t["cim"])).encode()).hexdigest()[:12],
            "forras": forras["nev"],
            "terulet": forras.get("terulet"),
            "elso_latva": ma,
            "utoljara_latva": ma,
            "statusz": "jovahagyva" if AUTO_JOVAHAGYAS else "jovahagyasra_var",
        })
        tetelek.append(t)
        link_index[normal_link(t["link"])] = t
        cim_index[normal_cim(t["cim"])] = t
        hozzaadott.append(t)
    return hozzaadott


def lejart(t: dict, ma: str) -> bool:
    if t.get("hatarido"):
        return t["hatarido"] < ma
    if t.get("esemeny_datum"):
        return t["esemeny_datum"] < ma
    utoljara = dt.date.fromisoformat(t.get("utoljara_latva") or t.get("elso_latva") or ma)
    return (dt.date.today() - utoljara).days > NEM_LATOTT_NAP


def archival(adatok: dict) -> int:
    ma = dt.date.today().isoformat()
    archivum = betolt(ARCHIVUM_FAJL, [])
    marad, regi = [], []
    for t in adatok["tetelek"]:
        (regi if lejart(t, ma) else marad).append(t)
    if regi:
        archivum.extend(regi)
        ment(ARCHIVUM_FAJL, archivum)
    elif not ARCHIVUM_FAJL.exists():
        ment(ARCHIVUM_FAJL, archivum)
    adatok["tetelek"] = marad
    return len(regi)


# ------------------------------------------------------------- értesítés
def evf_szoveg(t: dict) -> str:
    if t["evfolyam_min"] == 1 and t["evfolyam_max"] == 13:
        return "minden évf."
    if t["evfolyam_min"] == t["evfolyam_max"]:
        return f"{t['evfolyam_min']}. évf."
    return f"{t['evfolyam_min']}–{t['evfolyam_max']}. évf."


def ertesit(ujak: list, adatok: dict) -> None:
    """Reggeli összefoglaló küldése az ntfy alkalmazásba, ha van új vagy hamarosan lejáró tétel."""
    tema = os.environ.get("NTFY_TEMA", "").strip()
    if not tema:
        return
    ma = dt.date.today()
    surgos = sorted(
        (t for t in adatok["tetelek"]
         if t.get("statusz") != "elutasitva" and t.get("hatarido")
         and 0 <= (dt.date.fromisoformat(t["hatarido"]) - ma).days <= 5
         and t not in ujak),
        key=lambda t: t["hatarido"],
    )
    if not ujak and not surgos:
        print("Értesítés: nincs új vagy sürgős tétel, nem küldök.")
        return

    sorok = []
    if ujak:
        ujak = sorted(ujak, key=lambda t: t.get("hatarido") or t.get("esemeny_datum") or "9999")
        sorok.append(f"{len(ujak)} új lehetőség:")
        for t in ujak[:8]:
            hat = f", határidő: {t['hatarido'][5:].replace('-', '.')}." if t.get("hatarido") else ""
            sorok.append(f"• {t['cim']} ({evf_szoveg(t)}{hat})")
        if len(ujak) > 8:
            sorok.append(f"…és még {len(ujak) - 8}")
    if surgos:
        if sorok:
            sorok.append("")
        sorok.append("Hamarosan lejár:")
        for t in surgos[:5]:
            nap = (dt.date.fromisoformat(t["hatarido"]) - ma).days
            mikor = "ma" if nap == 0 else "holnap" if nap == 1 else f"{nap} nap múlva"
            sorok.append(f"• {t['cim']} ({mikor})")

    uzenet = {
        "topic": tema,
        "title": f"Diák-lehetőségek: {len(ujak)} új" if ujak else "Diák-lehetőségek: lejáró határidők",
        "message": "\n".join(sorok)[:3800],
        "tags": ["school_satchel"],
    }
    tarolo = os.environ.get("GITHUB_REPOSITORY", "")
    oldal = os.environ.get("OLDAL_URL") or (
        f"https://{tarolo.split('/')[0].lower()}.github.io/{tarolo.split('/')[1]}/" if "/" in tarolo else ""
    )
    if oldal:
        uzenet["click"] = oldal  # az értesítésre koppintva megnyílik a weboldal
    try:
        requests.post("https://ntfy.sh/", json=uzenet, timeout=15).raise_for_status()
        print("Értesítés elküldve.")
    except Exception as e:  # az értesítés hibája ne állítsa le a gyűjtést
        print(f"Az értesítést nem sikerült elküldeni: {e}")


# ---------------------------------------------------------------------- fő
def main() -> int:
    ap = argparse.ArgumentParser(description="Diák-lehetőség gyűjtő")
    ap.add_argument("--csak", help="csak azok a források, amelyek nevében ez szerepel")
    ap.add_argument("--kenyszerit", action="store_true", help="változatlan oldalt is feldolgoz")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("HIBA: hiányzik az ANTHROPIC_API_KEY környezeti változó.")
        return 1

    forrasok = betolt(FORRASOK_FAJL, [])
    adatok = betolt(ADAT_FAJL, {"frissitve": None, "tetelek": []})
    allapot = betolt(ALLAPOT_FAJL, {})

    kliens = anthropic.Anthropic()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    uj_tetelek, feldolgozott, hibak, naplo = [], 0, [], []
    for forras in forrasok:
        if not forras.get("aktiv", True):
            continue
        if args.csak and args.csak.lower() not in forras["nev"].lower():
            continue
        nev = forras["nev"]
        try:
            szoveg = letolt(session, forras)
            h = ujjlenyomat(szoveg)
            if not args.kenyszerit and allapot.get(forras["url"], {}).get("hash") == h:
                for t in adatok["tetelek"]:
                    if t.get("forras") == nev:
                        t["utoljara_latva"] = dt.date.today().isoformat()
                naplo.append(f"– {nev}: nem változott")
            else:
                talalatok = kinyer(kliens, forras, szoveg)
                uj = osszefesul(adatok["tetelek"], talalatok, forras)
                uj_tetelek.extend(uj)
                allapot[forras["url"]] = {"hash": h, "utolso_feldolgozas": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
                naplo.append(f"✓ {nev}: {len(talalatok)} találat, {len(uj)} új")
            feldolgozott += 1
        except Exception as e:  # egy hibás forrás nem állítja le a többit
            hibak.append(nev)
            naplo.append(f"✗ {nev}: {type(e).__name__}: {e}")
        print(naplo[-1], flush=True)
        time.sleep(KESLELTETES_MP)

    if AUTO_JOVAHAGYAS:
        for t in adatok["tetelek"]:
            if t.get("statusz") == "jovahagyasra_var":
                t["statusz"] = "jovahagyva"

    archivalt = archival(adatok)
    adatok["tetelek"].sort(key=lambda t: (t.get("hatarido") or t.get("esemeny_datum") or "9999", t["cim"]))
    adatok["frissitve"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    ment(ADAT_FAJL, adatok)
    ment(ALLAPOT_FAJL, allapot)

    var = sum(1 for t in adatok["tetelek"] if t.get("statusz") == "jovahagyasra_var")
    osszegzes = (
        f"Új tétel: {len(uj_tetelek)} | archivált: {archivalt} | "
        f"összesen: {len(adatok['tetelek'])} | jóváhagyásra vár: {var} | hibás forrás: {len(hibak)}"
    )
    print(osszegzes)

    # összefoglaló a GitHub Actions futás oldalára
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Gyűjtés eredménye\n\n" + osszegzes + "\n\n")
            f.write("\n".join(f"- {sor}" for sor in naplo) + "\n")

    ertesit(uj_tetelek, adatok)

    # csak akkor jelez hibát, ha egyetlen forrás sem sikerült
    return 1 if hibak and feldolgozott == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
