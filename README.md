# Datos de Colombia · CA Invests

Este proyecto lee, solo y cada 6 horas, las páginas oficiales del **DANE** y del **Banco de la República**,
y guarda el dato más reciente de cada indicador en `data/colombia.json`. La Terminal de CA Invests lee ese archivo.

| Indicador | Fuente | Qué se lee |
|---|---|---|
| Inflación anual (IPC) | DANE | Página "IPC información técnica" |
| Desempleo (tasa de desocupación) | DANE | Página "Empleo y desempleo" (GEIH) |
| PIB, variación anual | DANE | Página "PIB información técnica" |
| Tasa de política monetaria | Banco de la República | Página "Tasas de interés y sector financiero" |

Los TES todavía no están: el Banco solo los publica en una herramienta que no permite lectura automática.

## Reglas de seguridad y respeto a las fuentes
- Antes de leer cada página se consulta su `robots.txt`. Si no lo permite, ese indicador se omite.
- Solo se leen cifras públicas. No hay claves ni contraseñas en este proyecto (y nunca deben agregarse).
- Cada cifra se valida contra un rango razonable antes de aceptarla.
- Si una fuente falla, se conserva el último dato bueno y **GitHub te envía un correo** con el aviso.
- Atribución obligatoria del DANE (la Terminal la muestra sola): *"Fuente: Departamento Administrativo Nacional de Estadística: www.dane.gov.co"*.

## Si algún día deja de funcionar
Lo más probable es que el DANE o el Banco hayan cambiado la redacción de su página. El correo de aviso lo dirá
(por ejemplo "no encontré la inflación anual"). Avísale a Claude con ese texto y se ajusta la pequeña regla de lectura
en `scripts/build_colombia.py`. Mientras tanto la Terminal sigue mostrando el último dato bueno, con su fecha.

## Pruebas
`python3 tests/test_parsers.py` (14 pruebas, no usan internet).
