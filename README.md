# Portal interno de archivos · INGESLINGAS S.A.S.

Herramienta interna para preparar y validar el archivo Excel de **declaración de ventas** a partir de una exportación de HELISA (`.xls`) o de un Excel que la plataforma ya rechazó.

- **Frontend** estático (HTML, CSS y JavaScript, sin compilación) publicable en GitHub Pages.
- **Backend** FastAPI (Python 3.12) publicable en Render.

---

## 1. Qué hace

1. Recibe un archivo `.xls`, `.xlsx` o `.csv` (máximo 25 MB) y, opcionalmente, el mensaje de error de la plataforma.
2. Detecta la fila de encabezados y mapea las columnas (por nombre, similitud y, para la fecha de emisión de HELISA, por contenido).
3. Extrae las facturas, aplica las reglas de la declaración y valida los datos.
4. **Construye un libro nuevo** sobre `backend/templates/PlantillaDeclaracionVentas_BASE.xlsx`. Nunca corrige el archivo malo ni usa `DataFrame.to_excel`.
5. Reabre el archivo generado y lo verifica (hojas, encabezados, tipos, formatos, columnas ocultas, total).
6. Muestra vista previa y entrega la descarga. El archivo temporal se elimina al terminar la descarga o a los 30 minutos.

Si algo no se puede corregir con seguridad, **no se genera archivo** y se indica fila y motivo.

## 2. Arquitectura

```
Navegador (GitHub Pages) ──fetch──▶ Backend FastAPI (Render)
   index.html / script.js            POST /api/process   → analiza, corrige, valida, genera
   config.js (API_URL)               GET  /api/download/{jobId} → entrega y borra
                                     GET  /api/health
```

Los archivos temporales viven en `/tmp/ingeslingas-excel-portal/{uuid}/output.xlsx`.

## 3. Estructura

```
index.html  styles.css  script.js  config.js     Frontend
assets/                                          logo-ingeslingas.png, mascota-ingeslingas.png
render.yaml                                      Blueprint de Render
backend/
  app/
    main.py                                      API, CORS, cabeceras de seguridad
    config.py  models.py  profile.py
    profiles/declaracion_ventas.json             Perfil: columnas, alias, constantes, reglas
    services/                                    file_reader, mapping, transformer, validator,
                                                 excel_writer, postprocess, jobs, error_interpreter, pipeline
    utils/                                       nit (DV), parsing (fechas y valores), text
  templates/PlantillaDeclaracionVentas_BASE.xlsx Plantilla base (sin registros)
  scripts/build_base_template.py                 Regenera la plantilla base
  tests/                                         Pruebas (pytest)
  Dockerfile  requirements.txt  requirements-dev.txt  .env.example  docker-compose.yml
```

## 4. Requisitos

- Python 3.12 o superior (el Dockerfile usa 3.12).
- Para el despliegue: cuenta en GitHub y en Render.
- `requirements.txt` declara rangos de versiones. Después de instalar y pasar las pruebas en tu equipo puedes fijar versiones exactas con `pip freeze`.

## 5. Dónde colocar las imágenes

Copia las imágenes oficiales **sin modificarlas** en `assets/` con estos nombres exactos:

```
assets/logo-ingeslingas.png
assets/mascota-ingeslingas.png
```

Las rutas son relativas (`./assets/...`), necesarias para GitHub Pages de proyecto. Si falta el logo se muestra el nombre en texto; si falta la mascota, el bloque se oculta.

## 6. Plantilla base

`backend/templates/PlantillaDeclaracionVentas_BASE.xlsx` se generó desde el archivo de julio **aceptado por la plataforma**: conserva hojas, orden, encabezados, estilos, anchos, columnas ocultas y hojas auxiliares, y solo se eliminaron los registros.

Para regenerarla desde otro archivo aceptado:

```bash
cd backend
python3 -I scripts/build_base_template.py "/ruta/PlantillaDeclaracionVentas JULIO 2026.xlsx"
```

Diferencias observadas entre las plantillas de junio y julio: en junio la columna de plazos aparece oculta y hay un autofiltro sobre «Tipo documento»; en julio no. La base sigue la de julio (la que la plataforma aceptó).

## 7. Ejecutar el backend en local

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

Comprobación: `curl http://localhost:8000/api/health` → `{"status":"ok"}`.

Variables de entorno (ver `backend/.env.example`):

| Variable | Defecto | Uso |
|---|---|---|
| `ALLOWED_ORIGINS` | orígenes locales de desarrollo | Orígenes CORS exactos, separados por coma. `*` se ignora. |
| `JOB_TTL_MINUTES` | `30` | Vida máxima de un archivo no descargado. |
| `MAX_UPLOAD_MB` | `25` | Tamaño máximo de carga. |
| `WORK_DIR` | `<tmp>/ingeslingas-excel-portal` | Carpeta temporal. |
| `LOG_LEVEL` | `INFO` | Nivel de logs. |
| `ENABLE_DOCS` | desactivado | Activa `/docs`. No usar en producción. |

Con Docker: `cd backend && docker compose up --build`.

## 8. Abrir el frontend en local

No abras `index.html` con doble clic (`file://`): el navegador envía origen `null` y CORS lo bloquea. Sirve la carpeta raíz:

```bash
python3 -m http.server 5500
```

Abre `http://localhost:5500`. `config.js` ya apunta a `http://localhost:8000` y el backend acepta `http://localhost:5500` por defecto.

## 9. Pruebas

```bash
cd backend
pytest -q
```

- Las pruebas usan datos sintéticos. Las de regresión con archivos reales se **omiten** si no están en `backend/tests/fixtures/` (ver el README de esa carpeta).
- `test_api.py` se omite si no hay `fastapi`/`httpx`; las de `.xls` reales se omiten sin `xlrd`. Con `requirements-dev.txt` instalado se ejecutan todas.
- Regresión de julio: 57 registros, total `476641448.08`, nombre `PlantillaDeclaracionVentas JULIO 2026.xlsx`.

## 10. Desplegar el backend en Render

1. Sube el repositorio a GitHub.
2. En Render: **New → Blueprint**, elige el repositorio. Lee `render.yaml` (servicio Docker, `healthCheckPath: /api/health`).
3. Cuando lo pida, define `ALLOWED_ORIGINS` con el origen de GitHub Pages, por ejemplo `https://tu-usuario.github.io` (sin ruta ni `/` final).
4. Espera el despliegue y copia la URL pública (`https://xxxxx.onrender.com`).
5. Verifica: `https://xxxxx.onrender.com/api/health`.

En el plan gratuito el servicio se suspende por inactividad: el primer acceso tarda. El portal lo indica con el mensaje «Estamos iniciando el servicio de procesamiento…».

## 11. Configurar `config.js`

Es la única configuración del frontend. Tras desplegar en Render:

```js
window.APP_CONFIG = {
  API_URL: "https://xxxxx.onrender.com",   // sin "/" final
  MAX_UPLOAD_MB: 25
};
```

Si `API_URL` queda vacío o con un marcador, el portal muestra «El portal de procesamiento todavía no tiene configurado el servidor.» y no envía nada.

## 12. Publicar en GitHub Pages

1. Sube los cambios a `main`.
2. En GitHub: **Settings → Pages → Build and deployment → Source: Deploy from a branch**.
3. Branch `main`, carpeta `/ (root)`, **Save**.
4. La URL será `https://tu-usuario.github.io/nombre-del-repositorio/`.

## 13. Actualizar CORS

El valor de `ALLOWED_ORIGINS` es el **origen**, no la URL completa del sitio:

- Correcto: `https://tu-usuario.github.io`
- Incorrecto: `https://tu-usuario.github.io/nombre-del-repositorio/`

En Render: servicio → **Environment** → editar `ALLOWED_ORIGINS` → guardar (reinicia el servicio). Para varios orígenes, sepáralos con coma.

## 14. Probar con el archivo de HELISA

1. Carga `VENTAS HELISA JULIO 2026.xls`.
2. Debe resultar **ARCHIVO VALIDADO**, 57 registros, valor total `$ 476.641.448,08`, periodo Julio 2026.
3. Descarga y compara con el archivo aceptado: nombre `PlantillaDeclaracionVentas JULIO 2026.xlsx`.

## 15. Cuando la plataforma rechaza un archivo nuevo

1. Pega el mensaje exacto en «Error reportado por la plataforma» y vuelve a procesar. El sistema lo interpreta (fechas, vencimiento, fórmulas, NIT, números, estructura, referencias de columna y fila) y muestra qué reglas se reforzaron.
2. Si el motivo no está cubierto, agrega la regla en `backend/app/services/validator.py` (validación) y la palabra clave en `backend/app/services/error_interpreter.py` (explicación), con una prueba en `backend/tests/`.

## 16. Agregar alias de columnas

Edita `backend/app/profiles/declaracion_ventas.json`, en la columna correspondiente, y añade el nombre nuevo a `aliases`. No requiere tocar código. El mapeo acepta alias con coincidencia normalizada (sin tildes ni mayúsculas) y similitud mínima de 0,85. Ejecuta `pytest` después.

## 17. Reglas del archivo final

| Campo | Regla |
|---|---|
| TIPO DOCUMENTO | `nitco` (texto) |
| CÓDIGO DOCUMENTO | NIT limpio + dígito de verificación (texto) |
| NOMBRE / RAZÓN SOCIAL | Solo se recortan espacios al inicio y al final |
| PAÍS | `co` |
| NÚMERO FACTURA | Texto |
| FECHA EMISIÓN | Fecha real de Excel con el formato de la plantilla |
| FECHA VENCIMIENTO | Emisión + 90 días (fecha real) |
| PLAZO DE VENTA | `90` (entero) |
| VALOR DE LA FACTURA | Numérico exacto (se calcula con `Decimal`) |
| COD. SOLUNION / REFERENCIA / CONDICIÓN DE PAGO | Vacías |

Decisiones que conviene conocer:

- **Dígito de verificación (DV):** se calcula con el algoritmo de la DIAN. Si el NIT trae DV explícito con guion (`900123456-7`) y es incorrecto, se corrige. Sin guion, un NIT de 10 dígitos o más cuyo último dígito es un DV válido se conserva; en los demás casos se calcula el DV. Si el archivo de origen ya tiene la columna `CÓDIGO DOCUMENTO` (Excel rechazado), el último dígito se toma como DV y, si es inválido, se recalcula con una advertencia.
- **Valores:** se aceptan `1234567.89`, `1,234,567.89`, `1.234.567,89` y `$ 1.234.567,89`. Un único separador con exactamente 3 dígitos detrás se trata como separador de miles y se avisa.
- **Valores negativos:** error bloqueante. Valor cero: advertencia.
- **Facturas duplicadas:** error bloqueante.
- **Cadenas compartidas:** `openpyxl` escribe texto como `inlineStr`; el archivo final se convierte a `sharedStrings.xml` (la forma habitual de Excel) para máxima compatibilidad con la plataforma.
- **Periodo:** si las fechas abarcan varios meses se usa el dominante en el nombre y se muestra advertencia.

## 18. Privacidad y borrado temporal

- El archivo cargado no se conserva: se lee durante la solicitud (el servidor web puede usar un temporal propio mientras lo recibe, que se descarta al terminar la petición) y solo el Excel generado se guarda, en una carpeta con UUID aleatorio.
- Se elimina al terminar la descarga y, si nadie lo descarga, a los 30 minutos (limpieza periódica cada 60 segundos y al crear cada trabajo).
- Los mensajes de error no incluyen trazas ni rutas internas; los detalles quedan solo en los logs del servidor.
- **Los archivos reales de clientes (`.xls`, `.xlsx`, `.csv`) no deben subirse al repositorio.** `.gitignore` los excluye (incluida la carpeta de fixtures). Un repositorio público también publica el código y la plantilla base.
- El portal **no tiene autenticación**: cualquiera que conozca la URL del frontend y del backend puede usarlo. La página incluye `noindex`, pero eso no es control de acceso. Si necesitas restringirlo, agrega autenticación o limita el acceso por red.

## 19. Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| «Servidor sin configurar» | `API_URL` vacío o sin cambiar | Editar `config.js` |
| «No fue posible comunicarse con el servidor…» | Backend apagado, URL incorrecta o CORS | Abrir `/api/health`; revisar `ALLOWED_ORIGINS` (origen exacto, sin `/` final) |
| Error CORS en consola | El origen de la página no está en `ALLOWED_ORIGINS` | Añadirlo y reiniciar el servicio |
| Primera carga lenta en Render | Servicio suspendido | Esperar; reintentar |
| `.xls` no se puede leer | Falta `xlrd` | `pip install -r requirements.txt` |
| «No se encontró ninguna hoja con encabezados reconocibles» | El archivo no tiene NIT, cliente, factura, fecha y valor | Revisar el archivo; añadir alias si el nombre es nuevo |
| El archivo ya expiró | Pasaron más de 30 minutos o ya se descargó | Procesar de nuevo |
| Funciona en local pero no con `file://` | CORS con origen `null` | Usar `python3 -m http.server 5500` |
| Logo o mascota no aparecen | Nombres o ubicación distintos | Revisar `assets/` (nombres exactos, minúsculas) |
