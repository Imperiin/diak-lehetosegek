# Diák-lehetőség gyűjtő

Naponta összegyűjti az 1–13. évfolyamos diákoknak szóló kreatív pályázatokat,
versenyeket, mobilitási és továbbtanulási lehetőségeket és eseményeket.

## Fájlok

| Fájl | Szerepe |
|---|---|
| `gyujto.py` | A gyűjtő program |
| `forrasok.json` | A figyelt weboldalak listája – ezt bővítsd |
| `.github/workflows/gyujtes.yml` | Napi automatikus futtatás |
| `adatok.json` | Az eredmény (a program hozza létre) |
| `archivum.json` | A lejárt tételek (jövőre jól jöhet, sok pályázat évente ismétlődik) |
| `allapot.json` | Megjegyzi, melyik oldal változott – így nem fizetsz feleslegesen API-hívásért |

## Beállítás

1. **Anthropic API-kulcs:** regisztrálj a https://console.anthropic.com oldalon, tölts fel kreditet,
   és hozz létre egy API-kulcsot. (Ez külön számlázás, a Claude.ai előfizetés nem tartalmazza.)
   Állíts be havi költségkorlátot a Console-ban.
2. **GitHub-tároló:** https://github.com → *New repository* → pl. `diak-lehetosegek`.
   Ha később ingyenes GitHub Pages oldalt akarsz hozzá, legyen **Public**.
3. **Fájlok feltöltése:** *Add file → Upload files*, húzd be a fájlokat.
   A `.github` mappát egyes gépek elrejtik – ha nem jelenik meg, hozd létre kézzel:
   *Add file → Create new file*, névnek írd be: `.github/workflows/gyujtes.yml`, és másold bele a tartalmát.
4. **Kulcs megadása:** *Settings → Secrets and variables → Actions → New repository secret*.
   Név: `ANTHROPIC_API_KEY`, érték: a kulcsod. (Soha ne írd a kulcsot fájlba!)
5. **Írási jog:** *Settings → Actions → General → Workflow permissions* →
   *Read and write permissions* → *Save*.
6. **Első futtatás:** *Actions* fül → *Lehetőségek gyűjtése* → *Run workflow*.
   Pár perc múlva a futás oldalán látod az összefoglalót, a tárolóban pedig megjelenik az `adatok.json`.

Ezután minden reggel magától lefut.

## Jóváhagyás

Az új tételek `"statusz": "jovahagyasra_var"` állapotban kerülnek be. Az `adatok.json`
szerkesztésével (ceruza ikon GitHubon) írd át `"jovahagyva"`-ra vagy `"elutasitva"`-ra.
Az elutasított tételt a program nem veszi fel újra. A weboldal csak a jóváhagyottakat mutatja majd.

Ha mindent automatikusan jóvá akarsz hagyni: *Settings → Secrets and variables → Actions →
Variables* → `AUTO_JOVAHAGYAS` = `1`. Gyerekeknek szóló oldalnál a kézi ellenőrzés javasolt.

## Új forrás felvétele

Adj új elemet a `forrasok.json`-hoz:

```json
{ "nev": "Forrás neve", "url": "https://...", "tipus": "html", "aktiv": true }
```

Ha az oldalnak van RSS-csatornája, használd azt (`"tipus": "rss"`) – megbízhatóbb.
Egy forrást kikapcsolhatsz az `"aktiv": false` beállítással.

**Fontos:** a program tiszteletben tartja a `robots.txt` tiltásait, és csak rövid, saját
összefoglalót tárol, az eredeti oldalra linkelve. Új forrás felvétele előtt nézd meg az oldal
felhasználási feltételeit – egyes pályázatfigyelő portálok tartalma részben előfizetéses.

## Futtatás saját gépen (nem kötelező)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."     # Windows: set ANTHROPIC_API_KEY=sk-ant-...
python gyujto.py --csak "pafi"            # egyetlen forrás kipróbálása
```
