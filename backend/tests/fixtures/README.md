# Fixtures reales (NO se suben a GitHub)

Coloca aquí, solo en tu equipo, los archivos reales para la prueba de regresión:

- `VENTAS HELISA JULIO 2026.xls` — exportación mensual de HELISA.
- `PlantillaDeclaracionVentas JULIO 2026.xlsx` — resultado aceptado por la plataforma (golden file).

Contienen información financiera de clientes, por eso `.gitignore` excluye `*.xls`, `*.xlsx` y `*.csv`
de esta carpeta. Si faltan, los tests de regresión se omiten (`skipped`) y el resto de la suite
usa datos sintéticos.
