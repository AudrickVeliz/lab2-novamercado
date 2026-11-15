"""Variables con las que el modelo pronostica una fecha (ver D-006).

Para cada fecha solo se usan ventas de días anteriores: la venta del día nunca
entra en sus propias variables. La promoción del día viene de la solicitud.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from novamercado.catalogos import Catalogos

CLAVE = ["fecha", "tienda_id", "familia_id"]
CATEGORICAS = ["tienda_id", "familia_id", "tipo_tienda"]
TIPOS_DE_FECHA = ["feriado", "comercial", "pago", "medio_dia"]
HISTORIA = [
    "venta_ayer",
    "ultima_venta",
    "dias_sin_dato",
    "media_7",
    "media_28",
    "venta_hace_7",
    "media_mismo_dia_4",
    "venta_hace_364",
]
VARIABLES = [
    *CATEGORICAS,
    "en_promocion",
    "dia_semana",
    "dia_mes",
    "mes",
    "dias_desde_apertura",
    *TIPOS_DE_FECHA,
    "vispera_feriado",
    *HISTORIA,
]

# Historia que necesitan las variables: la venta de hace 364 días es la más lejana.
DIAS_DE_HISTORIA = 364


def construir(ventas: pd.DataFrame, objetivos: pd.DataFrame, catalogos: Catalogos) -> pd.DataFrame:
    """Una fila de variables por objetivo, en el mismo orden.

    ventas: ventas conocidas (fecha, tienda_id, familia_id, ventas).
    objetivos: lo que se pronostica (fecha, tienda_id, familia_id, en_promocion).
    """
    objetivos = objetivos.reset_index(drop=True)
    variables = objetivos[CLAVE + ["en_promocion"]].copy()
    variables = variables.merge(_historia(ventas, objetivos), on=CLAVE, how="left")
    variables = variables.merge(_tipos_de_fecha(objetivos, catalogos), on=["fecha", "tienda_id"], how="left")
    variables[TIPOS_DE_FECHA + ["vispera_feriado"]] = variables[TIPOS_DE_FECHA + ["vispera_feriado"]].fillna(0)

    fecha = variables["fecha"]
    variables["dia_semana"] = fecha.dt.dayofweek
    variables["dia_mes"] = fecha.dt.day
    variables["mes"] = fecha.dt.month
    tiendas = catalogos.tiendas
    apertura = variables["tienda_id"].map(tiendas["fecha_apertura"])
    variables["dias_desde_apertura"] = (fecha - apertura).dt.days
    variables["tipo_tienda"] = variables["tienda_id"].map(tiendas["tipo"])

    # Categorías fijas del catálogo: el modelo ve los mismos códigos al entrenar y al predecir.
    variables["tienda_id"] = pd.Categorical(variables["tienda_id"], categories=sorted(catalogos.ids_tiendas))
    variables["familia_id"] = pd.Categorical(variables["familia_id"], categories=sorted(catalogos.ids_familias))
    variables["tipo_tienda"] = pd.Categorical(variables["tipo_tienda"], categories=sorted(tiendas["tipo"].unique()))
    return variables[VARIABLES]


def _historia(ventas: pd.DataFrame, objetivos: pd.DataFrame) -> pd.DataFrame:
    pares = objetivos[["tienda_id", "familia_id"]].drop_duplicates()
    conocidas = ventas.merge(pares, on=["tienda_id", "familia_id"])
    inicio = min(conocidas["fecha"].min(), objetivos["fecha"].min()) if len(conocidas) else objetivos["fecha"].min()
    fechas = pd.date_range(inicio, objetivos["fecha"].max(), freq="D")

    # Una columna por tienda y familia, una fila por día; los días sin dato quedan vacíos.
    panel = conocidas.pivot_table(index="fecha", columns=["tienda_id", "familia_id"], values="ventas", aggfunc="last")
    columnas = pd.MultiIndex.from_frame(pares.sort_values(["tienda_id", "familia_id"]))
    panel = panel.reindex(index=fechas, columns=columnas).astype(float)

    ayer = panel.shift(1)
    posicion = pd.DataFrame(np.arange(len(fechas))[:, None].repeat(panel.shape[1], axis=1), index=fechas, columns=columnas)
    ultima_posicion = posicion.where(panel.notna()).ffill().shift(1)
    hace = {k: panel.shift(k) for k in (7, 14, 21, 28)}
    suma_mismo_dia = sum(h.fillna(0) for h in hace.values())
    datos_mismo_dia = sum(h.notna().astype(int) for h in hace.values())

    tablas = {
        "venta_ayer": ayer,
        "ultima_venta": ayer.ffill(),
        "dias_sin_dato": posicion - ultima_posicion,
        "media_7": ayer.rolling(7, min_periods=1).mean(),
        "media_28": ayer.rolling(28, min_periods=1).mean(),
        "venta_hace_7": hace[7],
        "media_mismo_dia_4": suma_mismo_dia / datos_mismo_dia.where(datos_mismo_dia > 0),
        "venta_hace_364": panel.shift(DIAS_DE_HISTORIA),
    }
    largo = pd.concat(
        {nombre: tabla.stack(["tienda_id", "familia_id"], future_stack=True) for nombre, tabla in tablas.items()},
        axis=1,
    )
    largo.index.names = CLAVE
    return largo.reset_index()


def _tipos_de_fecha(objetivos: pd.DataFrame, catalogos: Catalogos) -> pd.DataFrame:
    """Marca cada tipo de fecha especial que aplica a la tienda: nacional o de su ciudad."""
    tiendas = catalogos.tiendas.reset_index()[["tienda_id", "ciudad"]]
    feriados = catalogos.feriados
    nacionales = feriados[feriados["ambito"] == "nacional"].merge(tiendas, how="cross")
    locales = feriados.merge(tiendas, left_on="ambito", right_on="ciudad")
    aplicables = pd.concat([nacionales, locales], ignore_index=True)[["fecha", "tienda_id", "tipo"]]
    aplicables = aplicables[aplicables["tipo"].isin(TIPOS_DE_FECHA)].assign(marca=1)

    marcas = aplicables.pivot_table(
        index=["fecha", "tienda_id"], columns="tipo", values="marca", aggfunc="max", fill_value=0
    )
    marcas = marcas.reindex(columns=TIPOS_DE_FECHA, fill_value=0).reset_index()
    marcas.columns.name = None

    vispera = marcas.loc[marcas["feriado"] == 1, ["fecha", "tienda_id"]].copy()
    vispera["fecha"] = vispera["fecha"] - pd.Timedelta(days=1)
    vispera["vispera_feriado"] = 1

    claves = objetivos[["fecha", "tienda_id"]].drop_duplicates()
    resultado = claves.merge(marcas, on=["fecha", "tienda_id"], how="left")
    return resultado.merge(vispera, on=["fecha", "tienda_id"], how="left")
