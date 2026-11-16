# Respuestas de la API ante los ejemplos publicados

Cada ejemplo de `data/publicados/ejemplos/` enviado al producto levantado. Las políticas están en D-003.

## prediccion_valida.json

`POST /v1/prediccion` → **200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "6",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 995.0,
      "cantidad_sugerida": 1326
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 60.7,
      "cantidad_sugerida": 93
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1000.1,
      "cantidad_sugerida": 1336
    },
    "… 9 familias más"
  ],
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```

## observacion_valida.json

`POST /v1/observaciones` → **200**

```json
{
  "registros_guardados": 12,
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```

## E01_tienda_texto.json

`POST /v1/prediccion` → **200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "6",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 995.0,
      "cantidad_sugerida": 1326
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 60.7,
      "cantidad_sugerida": 93
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1000.1,
      "cantidad_sugerida": 1336
    },
    "… 9 familias más"
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "tienda_id",
        "accion": "reparar",
        "detalle": "'T05' se interpretó como la tienda 5"
      }
    ]
  }
}
```

## E02_familia_otra_forma.json

`POST /v1/prediccion` → **200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "6",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 995.0,
      "cantidad_sugerida": 1326
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 60.7,
      "cantidad_sugerida": 93
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1000.1,
      "cantidad_sugerida": 1336
    },
    "… 9 familias más"
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "familias[5].familia_id",
        "accion": "reparar",
        "detalle": "'Frutas y Verduras' se interpretó como 'frutas_verduras'"
      },
      {
        "campo": "familias[6].familia_id",
        "accion": "reparar",
        "detalle": "'LÁCTEOS' se interpretó como 'lacteos'"
      }
    ]
  }
}
```

## E03_promocion_texto.json

`POST /v1/prediccion` → **200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "6",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 995.0,
      "cantidad_sugerida": 1326
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 60.7,
      "cantidad_sugerida": 93
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1000.1,
      "cantidad_sugerida": 1336
    },
    "… 9 familias más"
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "familias[2].en_promocion",
        "accion": "reparar",
        "detalle": "8.0 se interpretó como 8"
      },
      {
        "campo": "familias[11].en_promocion",
        "accion": "reparar",
        "detalle": "'9' se interpretó como 9"
      }
    ]
  }
}
```

## E04_fecha_formato.json

`POST /v1/prediccion` → **200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "6",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 995.0,
      "cantidad_sugerida": 1326
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 60.7,
      "cantidad_sugerida": 93
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1000.1,
      "cantidad_sugerida": 1336
    },
    "… 9 familias más"
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "fecha",
        "accion": "reparar",
        "detalle": "'17/11/2025' se interpretó como 2025-11-17"
      }
    ]
  }
}
```

## E05_faltan_familias.json

`POST /v1/prediccion` → **200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "6",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 995.0,
      "cantidad_sugerida": 1326
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1000.1,
      "cantidad_sugerida": 1336
    },
    {
      "familia_id": "carnes",
      "venta_esperada": 229.4,
      "cantidad_sugerida": 233
    },
    "… 9 familias más"
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "familias",
        "accion": "advertir",
        "detalle": "no se recibió 'bebe'; se pronosticó con en_promocion = 0"
      },
      {
        "campo": "familias",
        "accion": "advertir",
        "detalle": "no se recibió 'mascotas'; se pronosticó con en_promocion = 0"
      }
    ]
  }
}
```

## E06_familia_repetida.json

`POST /v1/prediccion` → **200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "6",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 1092.6,
      "cantidad_sugerida": 1457
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 60.7,
      "cantidad_sugerida": 93
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1000.1,
      "cantidad_sugerida": 1336
    },
    "… 9 familias más"
  ],
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "familias[0], familias[12]",
        "accion": "advertir",
        "detalle": "'abarrotes' llegó 2 veces con en_promocion distintas (0, 3); se usó la mayor (3)"
      }
    ]
  }
}
```

## E07_campo_renombrado.json

`POST /v1/prediccion` → **200**

```json
{
  "tienda_id": 5,
  "fecha": "2025-11-17",
  "version_modelo": "6",
  "predicciones": [
    {
      "familia_id": "abarrotes",
      "venta_esperada": 995.0,
      "cantidad_sugerida": 1326
    },
    {
      "familia_id": "bebe",
      "venta_esperada": 60.7,
      "cantidad_sugerida": 93
    },
    {
      "familia_id": "bebidas",
      "venta_esperada": 1000.1,
      "cantidad_sugerida": 1336
    },
    "… 9 familias más"
  ],
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "tienda",
        "accion": "reparar",
        "detalle": "'tienda' se interpretó como 'tienda_id'"
      }
    ]
  }
}
```

## E08_ventas_negativas.json

`POST /v1/observaciones` → **200**

```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "ventas[5].ventas",
        "accion": "advertir",
        "detalle": "ventas negativas (-4) para 'frutas_verduras'; no se guardó"
      }
    ]
  }
}
```

## E09_envio_repetido.json

`POST /v1/observaciones` → **200**

```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "ok",
    "observaciones": []
  }
}
```

## E10_numero_formato.json

`POST /v1/observaciones` → **200**

```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "corregido",
    "observaciones": [
      {
        "campo": "ventas[1].ventas",
        "accion": "reparar",
        "detalle": "'50,0' se interpretó como 50"
      },
      {
        "campo": "ventas[2].ventas",
        "accion": "reparar",
        "detalle": "'1,292' se interpretó como 1292"
      }
    ]
  }
}
```

# Problemas fuera del catálogo

## Tienda inexistente

```json
{"tienda_id": 99, "fecha": "2026-03-01", "familias": []}
```

`POST /v1/prediccion` → **422**

```json
{
  "detail": "La tienda 99 no existe"
}
```

## Fecha anterior a la apertura de la tienda 10

```json
{"tienda_id": 10, "fecha": "2025-03-14", "familias": []}
```

`POST /v1/prediccion` → **422**

```json
{
  "detail": "La tienda 10 abrió el 2025-03-15; no opera el 2025-03-14"
}
```

## Campos en conflicto

```json
{"tienda_id": 5, "tienda": 6, "fecha": "2026-03-01", "familias": []}
```

`POST /v1/prediccion` → **422**

```json
{
  "detail": "Los campos 'tienda_id', 'tienda' corresponden a 'tienda_id' y tienen valores distintos"
}
```

## JSON inválido

```json
{"tienda_id": 5,
```

`POST /v1/prediccion` → **422**

```json
{
  "detail": "El cuerpo de la solicitud no es JSON válido"
}
```

## Ventas no enteras y fuera de rango

```json
{"tienda_id": 5, "fecha": "2026-03-01", "ventas": [{"familia_id": "lacteos", "ventas": "12,5"}, {"familia_id": "snacks", "ventas": 99999999999}]}
```

`POST /v1/observaciones` → **200**

```json
{
  "registros_guardados": 0,
  "calidad": {
    "estado": "advertencia",
    "observaciones": [
      {
        "campo": "ventas[0].ventas",
        "accion": "advertir",
        "detalle": "ventas no enteras ('12,5') para 'lacteos'; no se guardó"
      },
      {
        "campo": "ventas[1].ventas",
        "accion": "advertir",
        "detalle": "ventas fuera de rango (99999999999) para 'snacks'; no se guardó"
      },
      {
        "campo": "ventas",
        "accion": "advertir",
        "detalle": "no se recibió 'abarrotes'"
      },
      {
        "campo": "ventas",
        "accion": "advertir",
        "detalle": "no se recibió 'bebe'"
      },
      {
        "campo": "ventas",
        "accion": "advertir",
        "detalle": "no se recibió 'bebidas'"
      },
      {
        "campo": "ventas",
        "accion": "advertir",
        "detalle": "no se recibió 'carnes'"
      },
      {
        "campo": "ventas",
        "accion": "advertir",
        "detalle": "no se recibió 'cuidado_personal'"
      },
      {
        "campo": "ventas",
        "accion": "advertir",
        "detalle": "no se recibió 'frutas_verduras'"
      },
      {
        "campo": "ventas",
        "accion": "advertir",
        "detalle": "no se recibió 'licores'"
      },
      {
        "campo": "ventas",
        "accion": "advertir",
        "detalle": "no se recibió 'limpieza'"
      },
      {
        "campo": "ventas",
        "accion": "advertir",
        "detalle": "no se recibió 'mascotas'"
      },
      {
        "campo": "ventas",
        "accion": "advertir",
        "detalle": "no se recibió 'panaderia'"
      }
    ]
  }
}
```

## GET /modelo

**200**

```json
{"nombre": "novamercado-ventas", "alias": "vigente", "version": "6"}
```

## GET /health

**200**

```json
{"estado": "ok"}
```

