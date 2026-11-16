"""Cliente de Airflow contra un servidor HTTP falso: no necesita Airflow."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from novamercado.orquestador import AirflowNoDisponible, ClienteAirflow


class AirflowFalso(BaseHTTPRequestHandler):
    estado_scheduler = "healthy"
    corridas: dict = {}
    tokens_emitidos = 0
    token_vigente = "token-1"
    peticiones: list = []

    def log_message(self, *args):
        pass

    def _responder(self, codigo, cuerpo):
        datos = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _cuerpo(self):
        largo = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(largo) or b"{}")

    def _autorizado(self):
        return self.headers.get("Authorization") == f"Bearer {type(self).token_vigente}"

    def do_POST(self):
        cuerpo = self._cuerpo()
        type(self).peticiones.append(("POST", self.path, cuerpo))
        if self.path == "/auth/token":
            if cuerpo != {"username": "airflow", "password": "airflow"}:
                return self._responder(401, {"detail": "credenciales inválidas"})
            type(self).tokens_emitidos += 1
            return self._responder(201, {"access_token": type(self).token_vigente})
        if not self._autorizado():
            return self._responder(401, {"detail": "token vencido"})
        if self.path == "/api/v2/dags/reentrenamiento/dagRuns":
            id = f"manual__2026-11-16T00:00:0{len(type(self).corridas)}"
            type(self).corridas[id] = "queued"
            return self._responder(200, {"dag_run_id": id, "state": "queued"})
        self._responder(404, {})

    def do_GET(self):
        if self.path == "/api/v2/monitor/health":
            return self._responder(200, {"metadatabase": {"status": "healthy"},
                                         "scheduler": {"status": type(self).estado_scheduler}})
        if not self._autorizado():
            return self._responder(401, {"detail": "token vencido"})
        prefijo = "/api/v2/dags/reentrenamiento/dagRuns/"
        if self.path.startswith(prefijo):
            from urllib.parse import unquote

            id = unquote(self.path[len(prefijo):])
            if id in type(self).corridas:
                return self._responder(200, {"dag_run_id": id, "state": type(self).corridas[id]})
        self._responder(404, {"detail": "no existe"})


@pytest.fixture
def airflow():
    AirflowFalso.corridas, AirflowFalso.peticiones = {}, []
    AirflowFalso.tokens_emitidos, AirflowFalso.token_vigente, AirflowFalso.estado_scheduler = 0, "token-1", "healthy"
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), AirflowFalso)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    yield ClienteAirflow(f"http://127.0.0.1:{servidor.server_address[1]}", "airflow", "airflow")
    servidor.shutdown()


def test_dispara_el_dag_con_logical_date_nulo(airflow):
    id = airflow.disparar()

    assert id.startswith("manual__")
    assert ("POST", "/api/v2/dags/reentrenamiento/dagRuns", {"logical_date": None}) in AirflowFalso.peticiones


@pytest.mark.parametrize(
    ("estado_airflow", "esperado"),
    [("queued", "en_curso"), ("running", "en_curso"), ("scheduled", "en_curso"), ("success", "exitoso"), ("failed", "fallido")],
)
def test_traduce_el_estado_del_dag_run(airflow, estado_airflow, esperado):
    id = airflow.disparar()
    AirflowFalso.corridas[id] = estado_airflow

    assert airflow.estado(id) == esperado


def test_id_desconocido_devuelve_none(airflow):
    assert airflow.estado("no-existe") is None


def test_reutiliza_el_token_y_lo_renueva_si_vence(airflow):
    airflow.disparar()
    airflow.disparar()
    assert AirflowFalso.tokens_emitidos == 1

    AirflowFalso.token_vigente = "token-2"
    airflow.disparar()
    assert AirflowFalso.tokens_emitidos == 2


def test_credenciales_invalidas_responden_airflow_no_disponible(airflow):
    airflow.clave = "otra"

    with pytest.raises(AirflowNoDisponible, match="credenciales"):
        airflow.disparar()
    assert AirflowFalso.tokens_emitidos == 0


def test_verificar_detecta_un_scheduler_caido(airflow):
    airflow.verificar()
    AirflowFalso.estado_scheduler = "unhealthy"

    with pytest.raises(AirflowNoDisponible, match="scheduler"):
        airflow.verificar()


def test_airflow_que_no_responde():
    cliente = ClienteAirflow("http://127.0.0.1:9", "airflow", "airflow")

    with pytest.raises(AirflowNoDisponible):
        cliente.disparar()
    with pytest.raises(AirflowNoDisponible):
        cliente.verificar()
