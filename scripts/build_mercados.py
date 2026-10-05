#!/usr/bin/env python3
"""
CA Invests · Datos de mercados (tasas, divisas, cripto)

Lee tres fuentes y escribe archivos JSON que la Terminal consulta:
  - U.S. Treasury (curva de rendimientos diaria)      -> data/rates.json
  - Banco Central Europeo (tipos de referencia)        -> data/forex.json
  - CoinGecko (plan Demo, con atribución)              -> data/crypto.json y data/crypto-history.json
  - Estado de cada fuente                              -> data/mercados-status.json

Reglas:
  - Solo biblioteca estándar de Python.
  - Cada fuente se actualiza solo cuando "toca" (para no abusar de los servicios).
  - Si una fuente falla, se conserva el último dato bueno y el proceso termina con error (GitHub avisa por correo).
  - Se validan rangos antes de aceptar una cifra.
  - Una clave de CoinGecko es opcional y se guarda como secreto de GitHub (COINGECKO_DEMO_KEY). Nunca va en el código.
"""
import json, os, sys, time, datetime
import re, urllib.request, urllib.error, urllib.parse, urllib.robotparser
import xml.etree.ElementTree as ET

UA = "CAInvestsDataBot/1.0 (+https://cainvests.com; hola@cainvests.com)"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")

TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
                "?data=daily_treasury_yield_curve&field_tdr_date_value={year}")
TENORS = {"BC_3MONTH": "US3M", "BC_1YEAR": "US1Y", "BC_2YEAR": "US2Y", "BC_5YEAR": "US5Y",
          "BC_7YEAR": "US7Y", "BC_10YEAR": "US10Y", "BC_20YEAR": "US20Y", "BC_30YEAR": "US30Y"}

ECB_90D = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
ECB_ALL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
# Pares de la Terminal que el BCE puede cubrir (USD/CNH no: el BCE publica CNY, no CNH offshore)
FX_PAIRS = ["EUR/USD", "USD/JPY", "GBP/USD", "AUD/USD", "USD/CAD", "USD/CHF", "NZD/USD", "EUR/JPY", "GBP/JPY",
            "EUR/GBP", "EUR/CHF", "AUD/JPY", "USD/MXN", "USD/BRL", "USD/INR", "USD/SGD", "USD/ZAR", "USD/TRY"]

CG_MARKETS = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={ids}"
              "&order=market_cap_desc&per_page=100&page=1&sparkline=false&price_change_percentage=24h%2C7d%2C30d")
CG_HIST = "https://api.coingecko.com/api/v3/coins/{id}/market_chart?vs_currency=usd&days=365&interval=daily"
CG_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "USDT": "tether", "BNB": "binancecoin", "SOL": "solana", "XRP": "ripple",
    "USDC": "usd-coin", "DOGE": "dogecoin", "ADA": "cardano", "AVAX": "avalanche-2", "TRX": "tron",
    "SHIB": "shiba-inu", "DOT": "polkadot", "LINK": "chainlink", "BCH": "bitcoin-cash", "TON": "the-open-network",
    "NEAR": "near", "POL": "polygon-ecosystem-token", "LTC": "litecoin", "UNI": "uniswap",
    "ICP": "internet-computer", "DAI": "dai", "APT": "aptos", "ETC": "ethereum-classic", "XLM": "stellar",
    "HBAR": "hedera-hashgraph", "FIL": "filecoin", "CRO": "crypto-com-chain", "ATOM": "cosmos",
    "IMX": "immutable-x", "ARB": "arbitrum", "VET": "vechain", "OP": "optimism", "MNT": "mantle",
    "INJ": "injective-protocol", "AAVE": "aave", "GRT": "the-graph", "MKR": "maker", "RENDER": "render-token",
    "RUNE": "thorchain", "ALGO": "algorand", "THETA": "theta-token", "SUI": "sui", "SEI": "sei-network",
    "LDO": "lido-dao", "STX": "blockstack", "PEPE": "pepe", "WIF": "dogwifcoin", "BONK": "bonk", "FET": "fetch-ai",
}

# Banco de la República · servicio oficial SDMX (Serankua). Aquí solo se LISTA el catálogo de series disponibles.
BANREP_CATALOGO = ["https://totoro.banrep.gov.co/nsi-jax-ws/rest/dataflow/ESTAT/all/latest",
                   "https://totoro.banrep.gov.co/nsi-jax-ws/rest/dataflow/all/all/latest"]
CLAVES_TES = re.compile(r"(\bTES\b|cero\s*cup|zero.?coupon|t[ií]tulos de tesorer|deuda p[uú]blica|pol[ií]tica monetaria|\bTPM\b|\bIPC\b|inflaci|\bIBR\b|\bDTF\b|\bUVR\b)", re.I)

# cada cuánto toca actualizar cada fuente (horas)
INTERVALS = {"rates": 6, "forex": 6, "crypto": 25 / 60, "crypto_history": 25 / 60, "banrep_catalogo": 24}
KEEP = 400  # puntos de historial por activo


# ---------------------------------------------------------------- utilidades
def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def local(tag):
    return tag.rsplit("}", 1)[-1]


def sig(v, n=8):
    return float(f"{v:.{n}g}")


def pct(a, b):
    return round((a / b - 1) * 100, 2) if b else None


def merge_hist(old, new_rows, keep=KEEP):
    """old y new_rows: listas [fecha, valor]. La fecha nueva reemplaza a la vieja."""
    d = {r[0]: r[1] for r in (old or [])}
    d.update({r[0]: r[1] for r in new_rows})
    return [[k, d[k]] for k in sorted(d)][-keep:]


def get(url, headers=None, timeout=60):
    h = {"User-Agent": UA, "Accept": "application/json, application/xml, text/xml, */*"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


# ---------------------------------------------------------------- U.S. Treasury
def parse_treasury(xml_text):
    root = ET.fromstring(xml_text)
    out = {}
    for el in root.iter():
        if local(el.tag) != "properties":
            continue
        row = {local(c.tag): (c.text or "").strip() for c in el}
        d = row.get("NEW_DATE", "")[:10]
        if not d:
            continue
        vals = {}
        for tag, ident in TENORS.items():
            try:
                v = float(row.get(tag, ""))
            except ValueError:
                continue
            if 0 < v < 25:
                vals[ident] = v
        if vals:
            out[d] = vals
    return out


def build_rates(prev, fetch, now):
    year = now.year
    days = {}
    years = [year] if prev.get("items") else [year - 1, year]
    for y in years:
        days.update(parse_treasury(fetch(TREASURY_URL.format(year=y))))
    if not days:
        raise ValueError("el archivo de Treasury no trajo datos")
    items = dict(prev.get("items", {}))
    for ident in TENORS.values():
        rows = [[d, v[ident]] for d, v in days.items() if ident in v]
        if not rows:
            continue
        h = merge_hist((items.get(ident) or {}).get("h"), rows)
        last, before = h[-1], (h[-2] if len(h) > 1 else None)
        items[ident] = {"p": last[1], "c": pct(last[1], before[1]) if before else None, "d": last[0], "h": h}
    asof = max(i["d"] for i in items.values())
    return {"updated": iso(now), "asof": asof, "source": "U.S. Department of the Treasury", "items": items}


# ---------------------------------------------------------------- BCE
def parse_ecb(xml_text):
    root = ET.fromstring(xml_text)
    out = {}
    for el in root.iter():
        if local(el.tag) == "Cube" and "time" in el.attrib:
            rates = {"EUR": 1.0}
            for c in el:
                if "currency" in c.attrib and "rate" in c.attrib:
                    try:
                        rates[c.attrib["currency"]] = float(c.attrib["rate"])
                    except ValueError:
                        pass
            out[el.attrib["time"]] = rates
    return out


def pair_value(rates, pair):
    a, b = pair.split("/")
    if a in rates and b in rates and rates[a] > 0:
        return rates[b] / rates[a]
    return None


def build_forex(prev, fetch, now):
    items = dict(prev.get("items", {}))
    need_full = any(len((items.get(p) or {}).get("h", [])) < 200 for p in FX_PAIRS)
    days = parse_ecb(fetch(ECB_ALL if need_full else ECB_90D))
    if not days:
        raise ValueError("el archivo del BCE no trajo datos")
    for pair in FX_PAIRS:
        rows = []
        for d, rates in days.items():
            v = pair_value(rates, pair)
            if v and v > 0:
                rows.append([d, sig(v, 7)])
        if not rows:
            continue
        h = merge_hist((items.get(pair) or {}).get("h"), rows)
        last, before = h[-1], (h[-2] if len(h) > 1 else None)
        items[pair] = {"p": last[1], "c": pct(last[1], before[1]) if before else None, "d": last[0], "h": h}
    asof = max(i["d"] for i in items.values())
    return {"updated": iso(now), "asof": asof, "source": "European Central Bank", "items": items}


# ---------------------------------------------------------------- CoinGecko
def parse_markets(js, ids=CG_IDS):
    by_id = {x.get("id"): x for x in js if isinstance(x, dict)}
    items, missing = {}, []

    def val(x, *keys):
        for k in keys:
            v = x.get(k)
            if isinstance(v, (int, float)):
                return v
        return None

    for sym, cid in ids.items():
        x = by_id.get(cid)
        price = val(x or {}, "current_price")
        if price is None or price <= 0:
            missing.append(sym)
            continue
        c24 = val(x, "price_change_percentage_24h_in_currency", "price_change_percentage_24h")
        c7 = val(x, "price_change_percentage_7d_in_currency")
        c30 = val(x, "price_change_percentage_30d_in_currency")
        items[sym] = {"p": sig(price), "c": None if c24 is None else round(c24, 2),
                      "c7": None if c7 is None else round(c7, 2), "c30": None if c30 is None else round(c30, 2),
                      "mc": val(x, "market_cap"), "v": val(x, "total_volume"), "rk": val(x, "market_cap_rank"),
                      "t": x.get("last_updated")}
    return items, missing


def parse_market_chart(js):
    rows = {}
    for ts, price in (js.get("prices") or []):
        if isinstance(price, (int, float)) and price > 0:
            d = datetime.datetime.fromtimestamp(ts / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
            rows[d] = sig(price)
    return [[d, rows[d]] for d in sorted(rows)]


def cg_headers():
    k = os.environ.get("COINGECKO_DEMO_KEY", "").strip()
    return {"x-cg-demo-api-key": k} if k else {}


def build_crypto(prev, fetch, now):
    ids = ",".join(CG_IDS.values())
    js = json.loads(fetch(CG_MARKETS.format(ids=ids), cg_headers()))
    if not isinstance(js, list) or not js:
        raise ValueError("CoinGecko no devolvió la lista de monedas")
    items, missing = parse_markets(js)
    if len(items) < 25:
        raise ValueError(f"CoinGecko devolvió muy pocas monedas ({len(items)})")
    return {"updated": iso(now), "source": "CoinGecko", "missing": missing, "items": items}


def build_crypto_history(prev, fetch, now, pause=7.0, batch=8):
    """Baja el historial de unas pocas monedas por ejecución (las que faltan o son más viejas), para no pasar el
    límite de CoinGecko. En unas horas quedan las 50 y luego cada moneda se refresca una vez al día."""
    items = dict(prev.get("items", {}))
    fetched = dict(prev.get("fetched", {}))

    def viejo(sym):
        t = parse_iso(fetched.get(sym, ""))
        return t is None or (now - t).total_seconds() > 20 * 3600

    todo = [s for s in sorted(CG_IDS, key=lambda x: fetched.get(x, "")) if viejo(s) or s not in items][:batch]
    if not todo:
        return prev
    errors, nuevos = [], 0
    for sym in todo:
        try:
            rows = parse_market_chart(json.loads(fetch(CG_HIST.format(id=CG_IDS[sym]), cg_headers())))
            if not rows:
                errors.append(f"{sym}: sin datos")
            else:
                items[sym] = merge_hist(items.get(sym), rows, 370)
                fetched[sym] = iso(now)
                nuevos += 1
        except urllib.error.HTTPError as e:
            errors.append(f"{sym}: HTTP {e.code}")
            if e.code in (401, 403, 429):
                break  # límite o clave requerida: no insistir en esta ejecución
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sym}: {type(e).__name__}")
        if pause:
            time.sleep(pause)
    if nuevos == 0:
        raise ValueError("no se pudo bajar ningún historial (" + "; ".join(errors[:3]) + ")")
    pending = [s for s in CG_IDS if s not in items]
    return {"updated": iso(now), "source": "CoinGecko", "partial": bool(pending), "pending": pending,
            "fetched": fetched, "items": items}


# ---------------------------------------------------------------- Banco de la República: catálogo SDMX
def robots_ok(url):
    p = urllib.parse.urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{p.scheme}://{p.netloc}/robots.txt")
    rp.read()  # 404 = sin restricciones; 401/403 = prohibido; error de red = excepción
    return rp.can_fetch(UA, url)


def parse_dataflows(xml_text):
    """Devuelve [{id, agency, version, es, en}] a partir de la respuesta SDMX-ML de /dataflow."""
    root = ET.fromstring(xml_text)
    out = []
    for el in root.iter():
        if local(el.tag) != "Dataflow":
            continue
        names = {}
        for c in el:
            if local(c.tag) == "Name":
                names[c.attrib.get("{http://www.w3.org/XML/1998/namespace}lang", "")] = (c.text or "").strip()
        out.append({"id": el.attrib.get("id", ""), "agency": el.attrib.get("agencyID", ""), "version": el.attrib.get("version", ""),
                    "es": names.get("es", ""), "en": names.get("en", "") or (next(iter(names.values())) if names else "")})
    return [f for f in out if f["id"]]


def build_banrep_catalogo(prev, fetch, now, robots=robots_ok):
    last_err = None
    for url in BANREP_CATALOGO:
        try:
            if not robots(url):
                raise PermissionError("robots.txt no permite el acceso automático")
            flows = parse_dataflows(fetch(url))
            if flows:
                break
        except Exception as e:  # noqa: BLE001
            last_err = e
    else:
        raise ValueError(f"no se pudo leer el catálogo del Banco de la República ({type(last_err).__name__ if last_err else 'vacío'}: {last_err})")
    for f in flows:
        f["match"] = bool(CLAVES_TES.search(f["es"] + " " + f["en"] + " " + f["id"]))
    flows.sort(key=lambda f: (not f["match"], f["id"]))
    return {"updated": iso(now), "source": "Banco de la República · SDMX (Serankua)", "count": len(flows),
            "matches": [f["id"] for f in flows if f["match"]], "flows": flows[:600]}


# ---------------------------------------------------------------- orquestación
SOURCES = {
    "rates": ("rates.json", build_rates),
    "forex": ("forex.json", build_forex),
    "crypto": ("crypto.json", build_crypto),
    "crypto_history": ("crypto-history.json", build_crypto_history),
    "banrep_catalogo": ("banrep-catalogo.json", build_banrep_catalogo),
}


def due(status, name, now, force):
    if force:
        return True
    last = parse_iso((status.get("attempts") or {}).get(name, ""))
    return last is None or (now - last).total_seconds() >= INTERVALS[name] * 3600 - 60


def run(now=None, fetch=get, data_dir=DATA, force=False, only=None, pause=7.0, batch=8):
    now = now or now_utc()
    spath = os.path.join(data_dir, "mercados-status.json")
    status = read_json(spath, {"attempts": {}, "results": {}})
    status.setdefault("attempts", {})
    status.setdefault("results", {})
    failed = []
    for name, (fname, builder) in SOURCES.items():
        if only and name not in only:
            continue
        if not due(status, name, now, force):
            status["results"][name] = status["results"].get(name, "ok") if not str(status["results"].get(name, "")).startswith("error") else status["results"][name]
            continue
        status["attempts"][name] = iso(now)
        path = os.path.join(data_dir, fname)
        prev = read_json(path, {})
        try:
            kwargs = {"pause": pause, "batch": batch} if name == "crypto_history" else {}
            out = builder(prev, fetch, now, **kwargs)
            write_json(path, out)
            status["results"][name] = "ok"
        except Exception as e:  # noqa: BLE001
            status["results"][name] = f"error: {type(e).__name__}: {e}"
            failed.append(name)
    status["checked"] = iso(now)
    write_json(spath, status)
    return status, failed


def main():
    force = "--force" in sys.argv or os.environ.get("FORCE", "").lower() == "true"
    status, failed = run(force=force)
    for k, v in status["results"].items():
        print(f"{k:15s} {v}")
    if failed:
        print("ATENCIÓN: fallaron:", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
