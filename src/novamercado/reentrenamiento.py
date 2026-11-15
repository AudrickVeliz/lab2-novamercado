"""Reentrenamiento con el histórico publicado y la operación registrada (ver D-009).

Lo usan el servicio de arranque y el DAG de reentrenamiento. Arranque:

    python -m novamercado.reentrenamiento --inicial
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from sqlalchemy import Engine

from novamercado.catalogos import Catalogos, cargar_catalogos, cargar_historico, carpeta_datos
from novamercado.entrenamiento import Datos, preparar_datos
from novamercado.persistencia import crear_esquema, crear_motor, leer_observaciones, leer_promociones
from novamercado.registro_modelos import (
    Resultado,
    huella,
    huella_archivo,
    huella_codigo,
    reentrenar,
    version_vigente,
)

log = logging.getLogger(__name__)

ARCHIVOS_PUBLICADOS = ["historico_ventas.csv", "tiendas.csv", "familias.csv", "feriados.csv", "costos.csv"]
ESPERA_MLFLOW_SEGUNDOS = 600


def cargar(carpeta: str | Path | None, motor: Engine) -> tuple[Catalogos, Datos, dict[str, str]]:
    raiz = carpeta_datos(carpeta)
    catalogos = cargar_catalogos(raiz)
    observaciones = leer_observaciones(motor)
    promociones = leer_promociones(motor)
    datos = preparar_datos(cargar_historico(catalogos, raiz), observaciones, promociones)
    linaje = {f"huella_{archivo.removesuffix('.csv')}": huella_archivo(raiz / archivo) for archivo in ARCHIVOS_PUBLICADOS}
    linaje |= {
        "observaciones_registradas": str(len(observaciones)),
        "huella_observaciones": huella(observaciones),
        "promociones_registradas": str(len(promociones)),
        "filas_objetivo": str(len(datos.objetivos)),
        "huella_codigo": huella_codigo(),
    }
    return catalogos, datos, linaje


def ejecutar(carpeta: str | Path | None = None, motor: Engine | None = None) -> Resultado:
    motor = motor or crear_motor()
    crear_esquema(motor)
    catalogos, datos, linaje = cargar(carpeta, motor)
    return reentrenar(datos, catalogos, linaje)


def inicial(espera_maxima: float = ESPERA_MLFLOW_SEGUNDOS) -> Resultado | None:
    """Entrena y registra el primer modelo solo si todavía no hay uno vigente."""
    limite = time.monotonic() + espera_maxima
    while True:
        try:
            vigente = version_vigente()
            break
        except Exception as error:
            if time.monotonic() > limite:
                raise
            log.info("Esperando a MLflow: %s", error)
            time.sleep(5)
    if vigente is not None:
        log.info("Ya hay un modelo vigente (v%s): no se repite el entrenamiento inicial", vigente)
        return None
    resultado = ejecutar()
    log.info("Entrenamiento inicial: %s", resultado.motivo)
    return resultado


def _principal() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--inicial", action="store_true", help="solo si todavía no hay modelo vigente")
    if argumentos.parse_args().inicial:
        inicial()
    else:
        log.info("Reentrenamiento: %s", ejecutar().motivo)


if __name__ == "__main__":
    _principal()
