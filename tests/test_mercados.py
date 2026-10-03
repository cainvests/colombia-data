"""Pruebas del proceso de mercados. Usan archivos de ejemplo con el formato documentado de cada fuente; no usan internet."""
import os, sys, json, tempfile, unittest, datetime, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_mercados as m

def tentry(date, **v):
    tags = "".join(f'<d:{k} m:type="Edm.Double">{x}</d:{k}>' for k, x in v.items())
    return f'<entry><content type="application/xml"><m:properties><d:Id m:type="Edm.Int32">1</d:Id><d:NEW_DATE m:type="Edm.DateTime">{date}T00:00:00</d:NEW_DATE>{tags}</m:properties></content></entry>'
TREASURY = ('<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
  'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
  + tentry("2026-10-01", BC_1MONTH=4.2, BC_3MONTH=4.1, BC_1YEAR=3.95, BC_2YEAR=3.9, BC_5YEAR=3.95, BC_7YEAR=4.0, BC_10YEAR=4.1, BC_20YEAR=4.5, BC_30YEAR=4.6)
  + tentry("2026-10-02", BC_1MONTH=4.2, BC_3MONTH=4.12, BC_1YEAR=3.97, BC_2YEAR=3.92, BC_5YEAR=3.99, BC_7YEAR=4.05, BC_10YEAR=4.20, BC_20YEAR=4.55, BC_30YEAR=4.65)
  + tentry("2026-10-03", BC_10YEAR="")
  + '</feed>')

def ecb(days):
    cubes = "".join(f'<Cube time="{d}">' + "".join(f'<Cube currency="{c}" rate="{r}"/>' for c, r in rs.items()) + "</Cube>" for d, rs in days.items())
    return ('<?xml version="1.0" encoding="UTF-8"?><gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
            'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><gesmes:subject>Reference rates</gesmes:subject>'
            '<Cube>' + cubes + '</Cube></gesmes:Envelope>')
R1 = {"USD": 1.17, "JPY": 170.0, "GBP": 0.87, "CHF": 0.94, "AUD": 1.78, "CAD": 1.62, "NZD": 1.95, "MXN": 21.0, "BRL": 6.4, "INR": 98.0, "SGD": 1.5, "ZAR": 21.5, "TRY": 48.0, "CNY": 8.3}
R2 = dict(R1, USD=1.18, MXN=21.2)
ECB_XML = ecb({"2026-10-01": R1, "2026-10-02": R2})

MKT = [
  {"id": "bitcoin", "symbol": "btc", "current_price": 64123.45, "market_cap": 1.27e12, "market_cap_rank": 1, "total_volume": 3.1e10, "price_change_percentage_24h": 1.234, "price_change_percentage_24h_in_currency": 1.234, "price_change_percentage_7d_in_currency": -2.5, "price_change_percentage_30d_in_currency": 8.1, "last_updated": "2026-10-03T14:50:00.000Z"},
  {"id": "ethereum", "symbol": "eth", "current_price": 3100.5, "market_cap": 3.7e11, "market_cap_rank": 2, "total_volume": 1.5e10, "price_change_percentage_24h": None, "last_updated": "2026-10-03T14:50:00.000Z"},
  {"id": "pepe", "symbol": "pepe", "current_price": 0.00000851234, "market_cap": 3.5e9, "market_cap_rank": 40, "total_volume": 5e8, "price_change_percentage_24h": 5.0, "last_updated": "2026-10-03T14:49:00.000Z"},
]
def chart(days, start=100.0):
    t0 = datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc)
    return {"prices": [[int((t0 + datetime.timedelta(days=i)).timestamp() * 1000), start + i] for i in range(days)]}

NOW = datetime.datetime(2026, 10, 3, 15, 0, tzinfo=datetime.timezone.utc)

class Parsers(unittest.TestCase):
    def test_treasury(self):
        d = m.parse_treasury(TREASURY)
        self.assertEqual(sorted(d), ["2026-10-01", "2026-10-02"])        # el día sin cifras se ignora
        self.assertEqual(d["2026-10-02"]["US10Y"], 4.20)
        self.assertEqual(d["2026-10-02"]["US3M"], 4.12)
        self.assertNotIn("US1M", d["2026-10-02"])                         # plazos que la Terminal no usa
    def test_ecb(self):
        d = m.parse_ecb(ECB_XML)
        self.assertEqual(d["2026-10-02"]["USD"], 1.18)
        self.assertEqual(d["2026-10-02"]["EUR"], 1.0)
    def test_pares_derivados(self):
        r = m.parse_ecb(ECB_XML)["2026-10-01"]
        self.assertAlmostEqual(m.pair_value(r, "EUR/USD"), 1.17, 6)
        self.assertAlmostEqual(m.pair_value(r, "USD/JPY"), 170 / 1.17, 6)
        self.assertAlmostEqual(m.pair_value(r, "GBP/USD"), 1.17 / 0.87, 6)
        self.assertAlmostEqual(m.pair_value(r, "EUR/GBP"), 0.87, 6)
        self.assertAlmostEqual(m.pair_value(r, "GBP/JPY"), 170 / 0.87, 6)
        self.assertIsNone(m.pair_value(r, "USD/COP"))
    def test_cripto(self):
        items, missing = m.parse_markets(MKT)
        self.assertEqual(items["BTC"]["p"], 64123.45)
        self.assertEqual(items["BTC"]["c"], 1.23)
        self.assertIsNone(items["ETH"]["c"])                              # dato ausente no rompe nada
        self.assertEqual(items["PEPE"]["p"], 8.51234e-06)
        self.assertIn("SOL", missing)
        self.assertNotIn("BTC", missing)
    def test_historial_cripto(self):
        rows = m.parse_market_chart(chart(5))
        self.assertEqual(rows[0], ["2026-09-30", 100.0]); self.assertEqual(len(rows), 5)
    def test_merge(self):
        h = m.merge_hist([["2026-10-01", 1], ["2026-10-02", 2]], [["2026-10-02", 3], ["2026-10-03", 4]])
        self.assertEqual(h, [["2026-10-01", 1], ["2026-10-02", 3], ["2026-10-03", 4]])

class Flujo(unittest.TestCase):
    def fetch_ok(self, url, headers=None):
        if "treasury.gov" in url: return TREASURY
        if "eurofxref" in url: return ECB_XML
        if "coins/markets" in url: return json.dumps(MKT * 20 and [dict(MKT[0], id=i, current_price=1.0) for i in m.CG_IDS.values()])
        if "market_chart" in url: return json.dumps(chart(10))
        raise AssertionError(url)
    def run_(self, fetch=None, now=NOW, force=True, **kw):
        self.d = getattr(self, "d", None) or tempfile.mkdtemp()
        kw.setdefault("batch", 50)
        return m.run(now=now, fetch=fetch or self.fetch_ok, data_dir=self.d, force=force, pause=0, **kw)
    def read(self, f): return json.load(open(os.path.join(self.d, f), encoding="utf-8"))
    def test_todo_bien(self):
        st, failed = self.run_()
        self.assertEqual(failed, [])
        self.assertEqual(set(st["results"].values()), {"ok"})
        r = self.read("rates.json")
        self.assertEqual(r["items"]["US10Y"]["p"], 4.20)
        self.assertAlmostEqual(r["items"]["US10Y"]["c"], 2.44, 2)          # (4.20/4.10 - 1) en %
        self.assertEqual(r["asof"], "2026-10-02")
        f = self.read("forex.json")
        self.assertEqual(len(f["items"]), 18)
        self.assertNotIn("USD/CNH", f["items"])
        self.assertEqual(f["items"]["EUR/USD"]["p"], 1.18)
        c = self.read("crypto.json"); self.assertEqual(len(c["items"]), 50)
        h = self.read("crypto-history.json"); self.assertEqual(len(h["items"]["BTC"]), 10)
    def test_una_fuente_cae_y_conserva_lo_anterior(self):
        self.run_()
        antes = self.read("forex.json")
        def malo(url, headers=None):
            if "eurofxref" in url: raise OSError("sin red")
            return self.fetch_ok(url, headers)
        st, failed = self.run_(fetch=malo, now=NOW + datetime.timedelta(hours=7))
        self.assertEqual(failed, ["forex"])
        self.assertTrue(st["results"]["forex"].startswith("error"))
        self.assertEqual(self.read("forex.json"), antes)                  # el último dato bueno sigue ahí
        self.assertEqual(st["results"]["rates"], "ok")
    def test_no_se_actualiza_antes_de_tiempo(self):
        self.run_()
        calls = []
        def espia(url, headers=None):
            calls.append(url); return self.fetch_ok(url, headers)
        self.run_(fetch=espia, now=NOW + datetime.timedelta(minutes=10), force=False)
        self.assertEqual(calls, [])                                       # nada "toca" aún
        self.run_(fetch=espia, now=NOW + datetime.timedelta(minutes=30), force=False)
        self.assertTrue(any("coins/markets" in u for u in calls))         # cripto sí (cada 25 min)
        self.assertFalse(any("treasury.gov" in u for u in calls))         # tasas no (cada 6 h)
    def test_historial_se_completa_por_tandas(self):
        d = tempfile.mkdtemp(); self.d = d
        t = NOW
        for k in range(8):                                                # 8 ejecuciones de 8 monedas = 64 >= 50
            m.run(now=t, fetch=self.fetch_ok, data_dir=d, force=True, only=["crypto_history"], pause=0, batch=8)
            n = len(self.read("crypto-history.json")["items"])
            if k == 0: self.assertEqual(n, 8)                             # la primera tanda baja solo 8
            t += datetime.timedelta(minutes=30)
        h = self.read("crypto-history.json")
        self.assertEqual(len(h["items"]), 50); self.assertFalse(h["partial"]); self.assertEqual(h["pending"], [])
    def test_historial_no_repite_lo_fresco(self):
        self.run_(only=["crypto_history"])
        calls = []
        def espia(url, headers=None):
            calls.append(url); return self.fetch_ok(url, headers)
        self.run_(fetch=espia, only=["crypto_history"], now=NOW + datetime.timedelta(hours=2))
        self.assertEqual(calls, [])                                       # todo está fresco: no hace ninguna consulta
        self.run_(fetch=espia, only=["crypto_history"], now=NOW + datetime.timedelta(hours=21))
        self.assertEqual(len(calls), 50)                                  # pasadas 20 h, se refresca
    def test_limite_a_mitad_conserva_lo_bajado(self):
        d = tempfile.mkdtemp(); self.d = d; n = {"i": 0}
        def limite(url, headers=None):
            if "market_chart" in url:
                n["i"] += 1
                if n["i"] > 3: raise urllib.error.HTTPError(url, 429, "too many", {}, None)
            return self.fetch_ok(url, headers)
        st, failed = m.run(now=NOW, fetch=limite, data_dir=d, force=True, only=["crypto_history"], pause=0, batch=8)
        self.assertEqual(failed, [])                                      # lo bajado se guarda y no hay alarma
        h = self.read("crypto-history.json"); self.assertEqual(len(h["items"]), 3); self.assertTrue(h["partial"])
    def test_limite_desde_la_primera_es_error_con_motivo(self):
        def siempre429(url, headers=None):
            if "market_chart" in url: raise urllib.error.HTTPError(url, 429, "too many", {}, None)
            return self.fetch_ok(url, headers)
        st, failed = self.run_(fetch=siempre429, only=["crypto_history"])
        self.assertEqual(failed, ["crypto_history"])
        self.assertIn("HTTP 429", st["results"]["crypto_history"])        # el motivo exacto queda a la vista
    def test_clave_requerida_se_nota(self):
        def sin_clave(url, headers=None):
            if "market_chart" in url: raise urllib.error.HTTPError(url, 401, "no key", {}, None)
            return self.fetch_ok(url, headers)
        st, failed = self.run_(fetch=sin_clave, only=["crypto_history"])
        self.assertIn("HTTP 401", st["results"]["crypto_history"])
    def test_pocas_monedas_es_error(self):
        def pocas(url, headers=None):
            return json.dumps(MKT) if "coins/markets" in url else self.fetch_ok(url, headers)
        st, failed = self.run_(fetch=pocas, only=["crypto"])
        self.assertEqual(failed, ["crypto"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
