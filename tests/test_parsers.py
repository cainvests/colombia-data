"""Pruebas del lector. Usan frases reales de las páginas del DANE y del Banco (octubre de 2026). No usan internet."""
import os, sys, json, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_colombia as b

IPC_HTML = """<html><body><nav>Estadísticas por tema</nav><table><tr><td>
<p>Información agosto 2026</p><p>Fuente: DANE, IPC.</p>
<p>En agosto de 2026 la variación mensual del IPC fue 0,39%, la variación año corrido fue 5,35% y la anual 6,24%.</p>
<p>En agosto de 2026 la variación anual del IPC fue 6,24%, es decir, 1,14 puntos porcentuales mayor que la reportada en el mismo periodo del año anterior, cuando fue de 5,10%.</p></td></tr></table>
<table><tr><td>Boletín técnico</td><td>07/09/2026</td><td>PDF</td></tr><tr><td>Comunicado de prensa</td><td>07/09/2026</td></tr></table>
<h3>Información técnica</h3><script>var x="la anual 99%";</script></body></html>"""

GEIH_HTML = """<html><body><h2>Empleo y desocupación</h2><h2>Información agosto de 2026</h2>
<p>Para el mes de agosto de 2026, la tasa de desocupación del total nacional fue 9,4%, mientras que en el mismo mes de 2025 fue 8,6%. La tasa global de participación se ubicó en 63,3%.</p>
<p>En agosto de 2026, la tasa de desocupación en el total de las 13 ciudades y áreas metropolitanas fue 9,1%.</p>
<table><tr><td>Boletín técnico</td><td>30/09/2026</td></tr></table></body></html>"""

PIB_HTML = """<html><body><h2>Información segundo trimestre 2026pr</h2>
<p>En el segundo trimestre de 2026pr, el Producto Interno Bruto en su serie original, crece 3,5% respecto al mismo periodo de 2025pr.</p>
<p>Durante el primer semestre de 2026pr, respecto al mismo periodo del año anterior, el Producto Interno Bruto presenta un crecimiento de 2,9%.</p>
<table><tr><td>Boletín técnico</td><td>18/08/2026</td></tr></table></body></html>"""

TPM_HTML = """<html><body><h2>Política monetaria</h2>
<p>Comunicado de prensa: La Junta Directiva del Banco de la República decidió por mayoría mantener inalterada la tasa de interés de política monetaria en 12,0% / Publicado: 31 de julio de 2026</p>
<p>Tasa actual: 12%</p></body></html>"""


class P(unittest.TestCase):
    def test_ipc(self):
        r = b.parse_ipc(b.html_a_texto(IPC_HTML))
        self.assertEqual((r["v"], r["p"], r["pub"], r["prev"]), (6.24, "2026-08", "2026-09-07", 5.10))
        self.assertEqual(r["pl"]["es"], "frente a ago 2025")

    def test_des(self):
        r = b.parse_des(b.html_a_texto(GEIH_HTML))
        self.assertEqual((r["v"], r["p"], r["pub"], r["prev"]), (9.4, "2026-08", "2026-09-30", 8.6))
        self.assertEqual(r["pl"]["en"], "vs Aug 2025")

    def test_pib(self):
        r = b.parse_pib(b.html_a_texto(PIB_HTML))
        self.assertEqual((r["v"], r["p"], r["pub"]), (3.5, "2026-T2", "2026-08-18"))

    def test_pib_negativo(self):
        r = b.parse_pib(b.html_a_texto(PIB_HTML.replace("serie original, crece 3,5%", "serie original, decrece 1,2%")))
        self.assertEqual(r["v"], -1.2)

    def test_tpm_con_decimales(self):
        r = b.parse_tpm(b.html_a_texto(TPM_HTML.replace("Tasa actual: 12%", "Tasa actual: 12,25%")))
        self.assertEqual((r["v"], r["pub"], r["p"]), (12.25, "2026-07-31", "2026-07"))

    def test_tpm(self):
        self.assertEqual(b.parse_tpm(b.html_a_texto(TPM_HTML))["v"], 12.0)

    def test_numeros(self):
        self.assertEqual(b.num("6,24"), 6.24)
        self.assertEqual(b.num("-1,2%"), -1.2)
        self.assertEqual(b.num("12"), 12.0)

    def test_el_script_no_cuenta(self):
        self.assertNotIn("99", b.html_a_texto(IPC_HTML))

    def test_cambio_de_redaccion_falla_con_claridad(self):
        with self.assertRaises(ValueError):
            b.parse_ipc(b.html_a_texto("<p>Información agosto 2026</p><p>Otra redacción totalmente distinta</p>"))


class Flujo(unittest.TestCase):
    PAGES = {b.DANE_IPC: IPC_HTML, b.DANE_GEIH: GEIH_HTML, b.DANE_PIB: PIB_HTML, b.BANREP_TPM: TPM_HTML}

    def run_(self, previo=None, pages=None, robots=lambda u: True):
        pages = pages or self.PAGES
        def fetch(u):
            v = pages[u]
            if isinstance(v, Exception): raise v
            return v
        return b.actualizar(previo or {}, fetch=fetch, robots=robots, pausa=0, ahora="2026-10-02T12:00:00Z")

    def test_todo_bien(self):
        r = self.run_()
        self.assertEqual(set(r["status"].values()), {"ok"})
        self.assertEqual({k: v["v"] for k, v in r["items"].items()}, {"ipc": 6.24, "des": 9.4, "pib": 3.5, "tpm": 12.0})
        self.assertEqual(r["updated"], "2026-10-02T12:00:00Z")
        json.dumps(r)

    def test_si_una_fuente_cae_conserva_el_ultimo_dato(self):
        previo = self.run_()
        pages = dict(self.PAGES); pages[b.DANE_IPC] = OSError("sin red")
        r = self.run_(previo, pages)
        self.assertTrue(r["status"]["ipc"].startswith("error"))
        self.assertEqual(r["items"]["ipc"]["v"], 6.24)
        self.assertEqual(r["status"]["des"], "ok")

    def test_robots_prohibe(self):
        r = self.run_(robots=lambda u: "banrep" not in u)
        self.assertTrue(r["status"]["tpm"].startswith("error: PermissionError"))
        self.assertNotIn("tpm", r["items"])
        self.assertEqual(r["status"]["ipc"], "ok")

    def test_valor_absurdo_se_rechaza(self):
        pages = dict(self.PAGES); pages[b.BANREP_TPM] = TPM_HTML.replace("Tasa actual: 12%", "Tasa actual: 1200%")
        r = self.run_(pages=pages)
        self.assertIn("fuera de rango", r["status"]["tpm"])

    def test_sin_cambios_no_mueve_updated(self):
        a = self.run_()
        c = b.actualizar(a, fetch=lambda u: self.PAGES[u], robots=lambda u: True, pausa=0, ahora="2026-10-03T12:00:00Z")
        self.assertEqual(c["updated"], "2026-10-02T12:00:00Z")
        self.assertEqual(c["checked"], "2026-10-03T12:00:00Z")


if __name__ == "__main__":
    unittest.main(verbosity=2)
