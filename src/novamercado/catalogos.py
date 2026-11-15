"""Lectura y validación de los catálogos publicados.

Los catálogos (tiendas, familias, costos y feriados) son la referencia contra la
que se validan las solicitudes y con la que se entrena el modelo. Un catálogo
inconsistente no se corrige: el servicio no puede operar sobre él, así que la
carga falla con un mensaje que dice qué archivo y qué fila revisar.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

VARIABLE_CARPETA = "NOVAMERCADO_DATOS"
CARPETA_PREDETERMINADA = Path("data/publicados")

FORMATO_FECHA = "%Y-%m-%d"

# Columnas mínimas de cada archivo. Se aceptan columnas adicionales.
COLUMNAS = {
    "tiendas.csv": ["tienda_id", "nombre", "ciudad", "departamento", "tipo", "fecha_apertura"],
    "familias.csv": ["familia_id", "nombre"],
    "costos.csv": ["familia_id", "costo_faltante", "costo_sobrante"],
    "feriados.csv": ["fecha", "nombre", "tipo", "ambito"],
}


class CatalogoInvalido(ValueError):
    """Un catálogo publicado falta o no es consistente."""


@dataclass(frozen=True)
class Catalogos:
    """Catálogos validados. Las tablas no deben modificarse después de cargarlas."""

    tiendas: pd.DataFrame  # índice: tienda_id (int)
    familias: pd.DataFrame  # índice: familia_id (str)
    costos: pd.DataFrame  # índice: familia_id (str)
    feriados: pd.DataFrame  # columna fecha como datetime64

    @property
    def ids_tiendas(self) -> frozenset[int]:
        return frozenset(int(t) for t in self.tiendas.index)

    @property
    def ids_familias(self) -> frozenset[str]:
        return frozenset(self.familias.index)


def carpeta_datos(carpeta: str | Path | None = None) -> Path:
    """Carpeta de los archivos publicados: argumento, variable de entorno o predeterminada."""
    if carpeta is not None:
        return Path(carpeta)
    return Path(os.environ.get(VARIABLE_CARPETA, CARPETA_PREDETERMINADA))


def cargar_catalogos(carpeta: str | Path | None = None) -> Catalogos:
    """Lee y valida los cuatro catálogos de la carpeta de datos publicados."""
    raiz = carpeta_datos(carpeta)
    familias = _familias(_leer(raiz, "familias.csv"))
    return Catalogos(
        tiendas=_tiendas(_leer(raiz, "tiendas.csv")),
        familias=familias,
        costos=_costos(_leer(raiz, "costos.csv"), familias),
        feriados=_feriados(_leer(raiz, "feriados.csv")),
    )


def _leer(raiz: Path, archivo: str) -> pd.DataFrame:
    ruta = raiz / archivo
    if not ruta.is_file():
        raise CatalogoInvalido(f"No se encontró {ruta}")
    # Todo como texto: la conversión de tipos se valida explícitamente.
    tabla = pd.read_csv(ruta, dtype=str, keep_default_na=False, encoding="utf-8")
    tabla.columns = [c.strip() for c in tabla.columns]
    faltantes = [c for c in COLUMNAS[archivo] if c not in tabla.columns]
    if faltantes:
        raise CatalogoInvalido(f"{archivo}: faltan las columnas {faltantes}")
    tabla = tabla.apply(lambda col: col.str.strip())
    vacias = tabla[COLUMNAS[archivo]].eq("").any(axis=1)
    if vacias.any():
        raise CatalogoInvalido(f"{archivo}: hay valores vacíos en las filas {_filas(vacias)}")
    return tabla


def _tiendas(tabla: pd.DataFrame) -> pd.DataFrame:
    tabla["tienda_id"] = _enteros(tabla["tienda_id"], "tiendas.csv", "tienda_id")
    tabla["fecha_apertura"] = _fechas(tabla["fecha_apertura"], "tiendas.csv", "fecha_apertura")
    _sin_repetidos(tabla["tienda_id"], "tiendas.csv")
    return tabla.set_index("tienda_id").sort_index()


def _familias(tabla: pd.DataFrame) -> pd.DataFrame:
    _sin_repetidos(tabla["familia_id"], "familias.csv")
    return tabla.set_index("familia_id").sort_index()


def _costos(tabla: pd.DataFrame, familias: pd.DataFrame) -> pd.DataFrame:
    for columna in ("costo_faltante", "costo_sobrante"):
        valores = pd.to_numeric(tabla[columna], errors="coerce")
        invalidos = valores.isna() | (valores < 0)
        if invalidos.any():
            raise CatalogoInvalido(
                f"costos.csv: {columna} debe ser un número no negativo (filas {_filas(invalidos)})"
            )
        tabla[columna] = valores.astype(float)
    # Con ambos costos en cero la cantidad sugerida no estaría definida.
    ambos_cero = (tabla["costo_faltante"] == 0) & (tabla["costo_sobrante"] == 0)
    if ambos_cero.any():
        raise CatalogoInvalido(f"costos.csv: ambos costos son cero en las filas {_filas(ambos_cero)}")
    _sin_repetidos(tabla["familia_id"], "costos.csv")

    conocidas = set(familias.index)
    con_costo = set(tabla["familia_id"])
    if sin_costo := sorted(conocidas - con_costo):
        raise CatalogoInvalido(f"costos.csv: faltan los costos de {sin_costo}")
    if desconocidas := sorted(con_costo - conocidas):
        raise CatalogoInvalido(f"costos.csv: familias que no están en familias.csv: {desconocidas}")
    return tabla.set_index("familia_id").sort_index()


def _feriados(tabla: pd.DataFrame) -> pd.DataFrame:
    tabla["fecha"] = _fechas(tabla["fecha"], "feriados.csv", "fecha")
    return tabla.sort_values("fecha").reset_index(drop=True)


def _enteros(serie: pd.Series, archivo: str, columna: str) -> pd.Series:
    invalidos = ~serie.str.fullmatch(r"\d+")
    if invalidos.any():
        raise CatalogoInvalido(f"{archivo}: {columna} debe ser un entero (filas {_filas(invalidos)})")
    return serie.astype(int)


def _fechas(serie: pd.Series, archivo: str, columna: str) -> pd.Series:
    fechas = pd.to_datetime(serie, format=FORMATO_FECHA, errors="coerce")
    if fechas.isna().any():
        raise CatalogoInvalido(
            f"{archivo}: {columna} debe tener el formato AAAA-MM-DD (filas {_filas(fechas.isna())})"
        )
    return fechas


def _sin_repetidos(serie: pd.Series, archivo: str) -> None:
    repetidos = sorted(serie[serie.duplicated()].astype(str).unique())
    if repetidos:
        raise CatalogoInvalido(f"{archivo}: {serie.name} repetido: {repetidos}")


def _filas(mascara: pd.Series) -> list[int]:
    # Número de línea en el archivo: el encabezado es la línea 1.
    return [int(i) + 2 for i in mascara[mascara].index]
