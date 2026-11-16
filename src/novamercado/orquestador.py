"""Cliente de la API REST de Airflow 3 para disparar y seguir el reentrenamiento (ver D-011).

Usa solo la biblioteca estándar. El token JWT se pide con usuario y clave y se
renueva si Airflow responde 401.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Literal

DAG_REENTRENAMIENTO = "reentrenamiento"
TIEMPO_LIMITE_SEGUNDOS = 5

EstadoDagRun = Literal["en_curso", "exitoso", "fallido"]

# Estados de un dagRun de Airflow 3 y su equivalente en el contrato.
ESTADOS = {"queued": "en_curso", "running": "en_curso", "success": "exitoso", "failed": "fallido"}


class AirflowNoDisponible(RuntimeError):
    """Airflow no respondió o rechazó la solicitud."""


class CredencialesFaltantes(RuntimeError):
    """Faltan el usuario o la clave de Airflow en el entorno."""


class ClienteAirflow:
    def __init__(self, url: str, usuario: str, clave: str, dag_id: str = DAG_REENTRENAMIENTO):
        self.url = url.rstrip("/")
        self.usuario = usuario
        self.clave = clave
        self.dag_id = dag_id
        self._token: str | None = None

    @classmethod
    def desde_entorno(cls) -> ClienteAirflow:
        """Las credenciales vienen del entorno (el .env del compose); no hay valores por defecto."""
        faltantes = [v for v in ("NOVAMERCADO_AIRFLOW_USUARIO", "NOVAMERCADO_AIRFLOW_CLAVE") if not os.environ.get(v)]
        if faltantes:
            raise CredencialesFaltantes(f"Defina {', '.join(faltantes)}")
        return cls(
            os.environ.get("NOVAMERCADO_AIRFLOW_URL", "http://airflow-apiserver:8080"),
            os.environ["NOVAMERCADO_AIRFLOW_USUARIO"],
            os.environ["NOVAMERCADO_AIRFLOW_CLAVE"],
        )

    def disparar(self) -> str:
        """Crea un dagRun del DAG de reentrenamiento y devuelve su id."""
        respuesta = self._llamar("POST", f"/api/v2/dags/{self.dag_id}/dagRuns", {"logical_date": None})
        return respuesta["dag_run_id"]

    def estado(self, id: str) -> EstadoDagRun | None:
        """Estado del dagRun en términos del contrato, o None si no existe."""
        try:
            respuesta = self._llamar("GET", f"/api/v2/dags/{self.dag_id}/dagRuns/{urllib.request.quote(id, safe='')}")
        except _NoEncontrado:
            return None
        # Cualquier estado intermedio (por ejemplo "scheduled") cuenta como en curso.
        return ESTADOS.get(respuesta["state"], "en_curso")

    def verificar(self) -> None:
        """Lanza AirflowNoDisponible si la base de metadatos o el scheduler no están sanos."""
        salud = self._pedir("GET", "/api/v2/monitor/health", None, autenticar=False)
        enfermos = [k for k in ("metadatabase", "scheduler") if salud.get(k, {}).get("status") != "healthy"]
        if enfermos:
            raise AirflowNoDisponible(f"componentes no sanos: {', '.join(enfermos)}")

    def _llamar(self, metodo: str, ruta: str, cuerpo: dict | None = None) -> dict[str, Any]:
        try:
            return self._pedir(metodo, ruta, cuerpo)
        except _NoAutorizado:
            # El token pudo vencer: se pide uno nuevo una sola vez.
            self._token = None
        try:
            return self._pedir(metodo, ruta, cuerpo)
        except _NoAutorizado as error:
            raise AirflowNoDisponible("Airflow rechazó las credenciales") from error

    def _pedir(self, metodo: str, ruta: str, cuerpo: dict | None, autenticar: bool = True) -> dict[str, Any]:
        encabezados = {"Content-Type": "application/json"}
        if autenticar:
            encabezados["Authorization"] = f"Bearer {self._obtener_token()}"
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        solicitud = urllib.request.Request(self.url + ruta, data=datos, headers=encabezados, method=metodo)
        try:
            with urllib.request.urlopen(solicitud, timeout=TIEMPO_LIMITE_SEGUNDOS) as respuesta:
                return json.loads(respuesta.read() or b"{}")
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise _NoAutorizado() from error
            if error.code == 404:
                raise _NoEncontrado() from error
            raise AirflowNoDisponible(f"Airflow respondió {error.code} en {ruta}") from error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise AirflowNoDisponible(f"Airflow no responde: {error}") from error

    def _obtener_token(self) -> str:
        if self._token is None:
            respuesta = self._pedir(
                "POST", "/auth/token", {"username": self.usuario, "password": self.clave}, autenticar=False
            )
            self._token = respuesta["access_token"]
        return self._token


class _NoAutorizado(Exception):
    pass


class _NoEncontrado(Exception):
    pass
