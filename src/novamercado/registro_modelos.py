"""Experimentos, linaje y Model Registry en MLflow (ver D-009).

Cada reentrenamiento es un run padre con un run hijo por candidato (baseline y
gradient boosting). El alias se mueve al final y solo si el criterio de D-008 lo
permite: un reentrenamiento que falla o no supera el criterio deja intacto al vigente.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import logging
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import joblib
import mlflow
import pandas as pd
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

from novamercado.catalogos import Catalogos
from novamercado.entrenamiento import Candidato, Datos, decidir, entrenar, evaluar_vigente
from novamercado.modelo import ModeloEntrenado

log = logging.getLogger(__name__)

NOMBRE_MODELO = "novamercado-ventas"
ALIAS = "vigente"
EXPERIMENTO = "novamercado-ventas"
ENVOLTURA = Path(__file__).with_name("pyfunc_modelo.py")


@dataclass(frozen=True)
class Resultado:
    promovido: bool
    # Versión del modelo vigente al terminar (la anterior si no hubo reemplazo).
    version: str | None
    motivo: str
    run_id: str


def version_vigente(cliente: MlflowClient | None = None) -> str | None:
    """Versión con el alias vigente, o None si todavía no hay ninguna."""
    cliente = cliente or MlflowClient()
    try:
        # MLflow 3 devuelve la versión como número; el contrato la pide como texto.
        return str(cliente.get_model_version_by_alias(NOMBRE_MODELO, ALIAS).version)
    except MlflowException as error:
        if error.error_code == "RESOURCE_DOES_NOT_EXIST":
            return None
        raise


def cargar_version(version: str) -> ModeloEntrenado:
    envoltura = mlflow.pyfunc.load_model(f"models:/{NOMBRE_MODELO}/{version}")
    return envoltura.unwrap_python_model().modelo


def verificar_servidor(tracking_uri: str, tiempo_limite: float = 3.0) -> None:
    """Lanza una excepción si el servidor de MLflow no responde a /health."""
    with urllib.request.urlopen(f"{tracking_uri.rstrip('/')}/health", timeout=tiempo_limite) as respuesta:
        if respuesta.status != 200:
            raise ConnectionError(f"MLflow respondió {respuesta.status}")


def reentrenar(datos: Datos, catalogos: Catalogos, linaje: dict[str, str]) -> Resultado:
    """Entrena los candidatos, los registra y promueve según el criterio de reemplazo."""
    cliente = MlflowClient()
    anterior = version_vigente(cliente)
    tramos, baseline, gbm = entrenar(datos, catalogos)
    costo_vigente = None
    if anterior is not None:
        costo_vigente = evaluar_vigente(cargar_version(anterior), datos, catalogos, tramos)["costo"]
    decision = decidir(baseline, gbm, costo_vigente)

    mlflow.set_experiment(EXPERIMENTO)
    with mlflow.start_run(run_name=f"reentrenamiento-{tramos.como_texto()['fin_validacion']}") as padre:
        mlflow.log_params({**tramos.como_texto(), **linaje})
        mlflow.set_tags({"vigente_anterior": anterior or "ninguno", "motivo": decision.motivo})
        if costo_vigente is not None:
            mlflow.log_metric("costo_vigente", costo_vigente)
        _registrar_datos(datos)
        versiones = {}
        for candidato in (baseline, gbm):
            # El gradient boosting se registra siempre (evidencia de cada reentrenamiento); el baseline
            # solo si gana como primer modelo.
            registrar = candidato is gbm or candidato is decision.promover
            versiones[candidato.modelo.tipo] = _registrar_candidato(candidato, registrar, candidato is decision.promover)
        mlflow.set_tag("promovido", str(decision.promover is not None).lower())
    for tipo, version in versiones.items():
        if version is not None:
            promovida = decision.promover is not None and decision.promover.modelo.tipo == tipo
            cliente.set_model_version_tag(NOMBRE_MODELO, version, "promovido", str(promovida).lower())
            cliente.set_model_version_tag(NOMBRE_MODELO, version, "motivo", decision.motivo)

    if decision.promover is None:
        return Resultado(False, anterior, decision.motivo, padre.info.run_id)
    nueva = versiones[decision.promover.modelo.tipo]
    cliente.set_registered_model_alias(NOMBRE_MODELO, ALIAS, nueva)
    log.info("Modelo %s v%s promovido: %s", NOMBRE_MODELO, nueva, decision.motivo)
    return Resultado(True, nueva, decision.motivo, padre.info.run_id)


def huella(tabla: pd.DataFrame) -> str:
    """Hash estable del contenido de una tabla, para el linaje."""
    return hashlib.sha256(pd.util.hash_pandas_object(tabla, index=False).to_numpy().tobytes()).hexdigest()[:16]


def huella_archivo(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()[:16]


def huella_codigo() -> str:
    """Hash del código del paquete: identifica la versión de código sin depender de git."""
    resumen = hashlib.sha256()
    for archivo in sorted(Path(__file__).parent.glob("*.py")):
        resumen.update(archivo.name.encode() + archivo.read_bytes())
    return resumen.hexdigest()[:16]


def _registrar_datos(datos: Datos) -> None:
    mlflow.log_input(mlflow.data.from_pandas(datos.objetivos, name="objetivos"), context="entrenamiento")
    with tempfile.TemporaryDirectory() as carpeta:
        for nombre, tabla in (("objetivos", datos.objetivos), ("ventas", datos.ventas)):
            ruta = Path(carpeta) / f"{nombre}.parquet"
            tabla.to_parquet(ruta, index=False)
            mlflow.log_artifact(str(ruta), artifact_path="datos")


def _registrar_candidato(candidato: Candidato, registrar: bool, promovido: bool) -> str | None:
    modelo = candidato.modelo
    with mlflow.start_run(run_name=modelo.tipo, nested=True):
        mlflow.log_param("tipo", modelo.tipo)
        hiperparametros = getattr(modelo.estimador, "hiperparametros", None)
        if hiperparametros is not None:
            mlflow.log_params(vars(hiperparametros))
        mlflow.log_params({f"factor_{familia}": round(f, 4) for familia, f in modelo.factores.items()})
        mlflow.log_metrics(candidato.metricas)
        mlflow.set_tag("promovido", str(promovido).lower())
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "modelo.joblib"
            joblib.dump(modelo, ruta)
            info = mlflow.pyfunc.log_model(
                name="modelo",
                python_model=str(ENVOLTURA),
                artifacts={"modelo": str(ruta)},
                pip_requirements=_requisitos(),
                registered_model_name=NOMBRE_MODELO if registrar else None,
            )
    return str(info.registered_model_version) if registrar else None


def _requisitos() -> list[str]:
    """Las dependencias exactas del paquete, en lugar de que MLflow las infiera."""
    return [r for r in importlib.metadata.requires("novamercado") or [] if "extra ==" not in r]
