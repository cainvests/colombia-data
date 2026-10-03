#!/usr/bin/env python3
"""
CA Invests · Datos de Colombia
Lee las páginas oficiales del DANE y del Banco de la República, extrae el dato más reciente de cada indicador
y escribe data/colombia.json, que la Terminal consulta. Corre solo, cada 6 horas, en GitHub Actions.

Reglas del proceso:
 - Respeta el archivo robots.txt de cada sitio. Si no se puede leer o no permite el acceso, ese indicador se omite.
 - Solo usa la biblioteca estándar de Python (sin dependencias).
 - Si un indicador falla, conserva el último dato bueno y el proceso termina con error para que GitHub te avise por correo.
 - Valida que cada cifra esté en un rango razonable antes de aceptarla.
"""
import json, os, re, sys, time, datetime, html as htmllib
import urllib.request, urllib.robotparser, urllib.parse
from html.parser import HTMLParser

UA = "CAInvestsDataBot/1.0 (+https://cainvests.com; hola@cainvests.com)"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "colombia.json")

DANE_IPC = "https://www.dane.gov.co/index.php/estadisticas-por-tema/precios-y-costos/indice-de-precios-al-consumidor-ipc/ipc-informacion-tecnica"
DANE_GEIH = "https://www.dane.gov.co/index.php/estadisticas-por-tema/mercado-laboral/empleo-y-desempleo"
DANE_PIB = "https://www.dane.gov.co/index.php/estadisticas-por-tema/cuentas-nacionales/cuentas-nacionales-trimestrales/pib-informacion-tecnica"
BANREP_TPM = "https://www.banrep.gov.co/es/servicios-temas/2100"

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
MES_CORTO = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun", 7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}
MES_EN = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
TRIM = {"primer": 1, "segundo": 2, "tercer": 3, "cuarto": 4}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "td", "th"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.parts.append(d)


def html_a_texto(h):
    p = _Text()
    p.feed(h)
    t = htmllib.unescape(" ".join(p.parts)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def num(s):
    s = s.strip().replace("%", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def fecha_dmy(s):
    d, m, y = s.split("/")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def pub_boletin(t):
    m = re.search(r"Bolet[ií]n t[eé]cnico\s+(\d{2}/\d{2}/\d{4})", t)
    return fecha_dmy(m.group(1)) if m else None


def periodo_mes(t):
    m = re.search(r"Informaci[oó]n\s+([A-Za-záéíóúÁÉÍÓÚ]+)\s+(?:de\s+)?(\d{4})", t)
    if not m or m.group(1).lower() not in MESES:
        raise ValueError("no encontré el período (mes y año)")
    return int(m.group(2)), MESES[m.group(1).lower()]


# ---------------- extractores (reciben el texto de la página) ----------------
def parse_ipc(t):
    y, mth = periodo_mes(t)
    m = re.search(r"la anual\s+(-?[\d.,]+)\s*%", t) or re.search(r"variaci[oó]n anual del IPC fue\s+(-?[\d.,]+)\s*%", t)
    if not m:
        raise ValueError("no encontré la inflación anual")
    out = {"v": num(m.group(1)), "p": f"{y:04d}-{mth:02d}", "pub": pub_boletin(t), "src": "DANE"}
    pv = re.search(r"cuando fue de\s+(-?[\d.,]+)\s*%", t)
    if pv:
        out["prev"] = num(pv.group(1))
        out["pl"] = {"es": f"frente a {MES_CORTO[mth]} {y - 1}", "en": f"vs {MES_EN[mth]} {y - 1}"}
    return out


def parse_des(t):
    y, mth = periodo_mes(t)
    m = re.search(r"tasa de desocupaci[oó]n del total nacional fue\s+(-?[\d.,]+)\s*%"
                  r"(?:,?\s*mientras que en el mismo mes de (\d{4}) fue\s+(-?[\d.,]+)\s*%)?", t)
    if not m:
        raise ValueError("no encontré la tasa de desocupación nacional")
    out = {"v": num(m.group(1)), "p": f"{y:04d}-{mth:02d}", "pub": pub_boletin(t), "src": "DANE"}
    if m.group(3):
        out["prev"] = num(m.group(3))
        out["pl"] = {"es": f"frente a {MES_CORTO[mth]} {m.group(2)}", "en": f"vs {MES_EN[mth]} {m.group(2)}"}
    return out


def parse_pib(t):
    m = re.search(r"Informaci[oó]n\s+(primer|segundo|tercer|cuarto)\s+trimestre\s+(\d{4})", t)
    if not m:
        raise ValueError("no encontré el trimestre")
    q, y = TRIM[m.group(1)], int(m.group(2))
    g = re.search(r"serie original,\s*(crece|decrece|disminuye|cae)\s+(-?[\d.,]+)\s*%", t)
    if not g:
        raise ValueError("no encontré el crecimiento del PIB")
    v = num(g.group(2))
    v = v if g.group(1) == "crece" else -abs(v)
    return {"v": v, "p": f"{y:04d}-T{q}", "pub": pub_boletin(t), "src": "DANE",
            "note": {"es": "serie original, preliminar", "en": "original series, preliminary"}}


def parse_tpm(t):
    m = re.search(r"Tasa actual:\s*(-?[\d.,]+)\s*%", t)
    if not m:
        raise ValueError("no encontré la tasa actual")
    out = {"v": num(m.group(1)), "src": "Banco de la República"}
    d = re.search(r"Publicado:\s*(\d{1,2}) de ([a-záéíóú]+) de (\d{4})", t, re.I)
    if d and d.group(2).lower() in MESES:
        y, mth, dd = int(d.group(3)), MESES[d.group(2).lower()], int(d.group(1))
        out["pub"] = f"{y:04d}-{mth:02d}-{dd:02d}"
        out["p"] = f"{y:04d}-{mth:02d}"
    return out


RANGOS = {"ipc": (-5, 60), "des": (0, 40), "pib": (-30, 30), "tpm": (0, 40)}
FUENTES = {
    "ipc": (DANE_IPC, parse_ipc),
    "des": (DANE_GEIH, parse_des),
    "pib": (DANE_PIB, parse_pib),
    "tpm": (BANREP_TPM, parse_tpm),
}


# ---------------- red ----------------
def permitido_por_robots(url):
    p = urllib.parse.urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{p.scheme}://{p.netloc}/robots.txt")
    rp.read()  # 404 = sin restricciones; 401/403 = prohibido; error de red = excepción
    return rp.can_fetch(UA, url)


def descargar(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-CO,es;q=0.9", "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", errors="replace")


def actualizar(previo, fetch=descargar, robots=permitido_por_robots, pausa=2.0, ahora=None):
    ahora = ahora or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"updated": previo.get("updated"), "checked": ahora, "items": dict(previo.get("items", {})), "status": {}}
    cambio = False
    for k, (url, parser) in FUENTES.items():
        try:
            if not robots(url):
                raise PermissionError("robots.txt no permite el acceso automático")
            item = parser(html_a_texto(fetch(url)))
            lo, hi = RANGOS[k]
            if not (lo <= item["v"] <= hi):
                raise ValueError(f"valor fuera de rango razonable: {item['v']}")
            if item.get("pub") is None:
                item.pop("pub", None)
            item["url"] = url
            if out["items"].get(k) != item:
                cambio = True
            out["items"][k] = item
            out["status"][k] = "ok"
        except Exception as e:  # noqa: BLE001
            out["status"][k] = f"error: {type(e).__name__}: {e}"
        if pausa:
            time.sleep(pausa)
    if cambio or not out["updated"]:
        out["updated"] = ahora
    return out


def main():
    try:
        with open(OUT, encoding="utf-8") as f:
            previo = json.load(f)
    except Exception:  # noqa: BLE001
        previo = {}
    res = actualizar(previo)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
        f.write("\n")
    for k, s in res["status"].items():
        print(f"{k:4s} {s}")
    fallos = [k for k, s in res["status"].items() if s != "ok"]
    if fallos:
        print("ATENCIÓN: fallaron:", ", ".join(fallos))
        sys.exit(1)


if __name__ == "__main__":
    main()
