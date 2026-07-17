# Precios Locales OCR API

Backend FastAPI para recibir una imagen de lista de precios, extraer datos por OCR, guardar la imagen comprimida en `uploads/storage` y persistir en MariaDB los datos crudos y los datos aprobados para gráficas.

## Flujo principal

1. `POST /api/ocr/process`: recibe `id_personal` + imagen.
2. Ejecuta OCR con Tesseract local.
3. Comprime la imagen a WebP y guarda solo la ruta en DB.
4. Guarda el JSON completo en `ocr_documents.raw_ocr_json`.
5. Valida materiales/precios:
   - Material nuevo: siempre `pending_review`.
   - Variación solo por espacios/símbolos: puede autocorregirse.
   - Cambio de letras/palabras: revisión humana.
   - Precio fuera de rango: revisión humana.
6. Si requiere revisión, no entra a `price_history`.
7. `POST /api/ocr/{document_id}/review`: aprueba/corrige y continúa el flujo.

Si el primer documento queda con todos los materiales como nuevos, es normal: no existe catálogo inicial. El front debe pedir aprobación humana. Si el usuario aprueba todo tal como lo leyó el OCR, puede enviar:

```json
{
  "approved": true,
  "rows": [],
  "notes": "Aprobado completo"
}
```

Con `rows: []`, el backend aprueba todas las filas pendientes usando los valores OCR, crea `materials`, crea `material_aliases` y llena `price_history`.

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edita `.env` con tu usuario real de MariaDB. Ejemplo:

```env
DATABASE_URL=mysql+pymysql://root:TU_PASSWORD@localhost:3306/precios_locales?charset=utf8mb4
```

Crea la base con:

```sql
SOURCE sql/precios_locales.sql;
```

Ejecuta:

```bash
uvicorn app.main:app --reload
```

Docs:

```text
http://localhost:8000/docs
```

Chequeo de conexión a base:

```text
http://localhost:8000/health/db
```
