"""Pruebas del contrato de la API: sin MLflow, sin servidor y sin base de datos."""

import copy
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from novamercado.api import Dependencias, crear_app
from novamercado.contrato import PrediccionFamilia
from novamercado.orquestador import AirflowNoDisponible


class PredictorFalso:
    nombre = "novamercado-ventas"
    alias = "vigente"
    version = "3"

    def __init__(self, falla=False):
        self.falla = falla

    def predecir(self, solicitud):
        if self.falla:
            raise RuntimeError("modelo roto")
        return [
            PrediccionFamilia(familia_id=f.familia_id, venta_esperada=100.5 + f.en_promocion, cantidad_sugerida=110)
            for f in solicitud.familias
        ]


class RegistroFalso:
    def __init__(self, falla=False):
        self.falla = falla
        self.rechazos, self.predicciones, self.observaciones = [], [], []
        self.vigentes = {}
        self.reentrenamientos = {}

    def _revisar(self):
        if self.falla:
            raise OperationalError("INSERT", {}, Exception("la base no responde"))

    def rechazo(self, endpoint, cuerpo, motivo, estado="rechazada"):
        self._revisar()
        self.rechazos.append((endpoint, cuerpo, motivo, estado))
        return len(self.rechazos)

    def prediccion(self, cuerpo, resultado, respuesta, modelo_nombre):
        self._revisar()
        self.predicciones.append((cuerpo, resultado, respuesta, modelo_nombre))
        return len(self.predicciones)

    def observacion(self, cuerpo, resultado):
        self._revisar()
        self.observaciones.append(cuerpo)
        s = resultado.solicitud
        nuevos = {(s.tienda_id, s.fecha, v.familia_id): v.ventas for v in s.ventas}
        cambiados = sum(self.vigentes.get(k) != v for k, v in nuevos.items())
        self.vigentes.update(nuevos)
        return cambiados

    def reentrenamiento(self, id):
        self._revisar()
        return self.reentrenamientos.get(id)


class OrquestadorFalso:
    def __init__(self, caido=False):
        self.caido = caido
        self.estados = {}

    def disparar(self):
        if self.caido:
            raise AirflowNoDisponible("Airflow no responde")
        id = f"manual__{len(self.estados) + 1}"
        self.estados[id] = "en_curso"
        return id

    def estado(self, id):
        if self.caido:
            raise AirflowNoDisponible("Airflow no responde")
        return self.estados.get(id)


def cliente(referencia, predictor=PredictorFalso(), registro=None, chequeos=None, orquestador=None):
    registro = registro or RegistroFalso()
    app = crear_app(Dependencias(referencia, registro, lambda: predictor, chequeos or {}, orquestador))
    return TestClient(app), registro


# POST /v1/prediccion


def test_prediccion_valida_cumple_el_contrato(referencia, prediccion):
    api, registro = cliente(referencia)
    r = api.post("/v1/prediccion", json=prediccion)

    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) >= {"tienda_id", "fecha", "version_modelo", "predicciones", "calidad"}
    assert (cuerpo["tienda_id"], cuerpo["fecha"]) == (5, "2025-11-17")
    assert cuerpo["version_modelo"] == "3"
    assert cuerpo["calidad"] == {"estado": "ok", "observaciones": []}
    for p in cuerpo["predicciones"]:
        assert set(p) >= {"familia_id", "venta_esperada", "cantidad_sugerida"}
        assert isinstance(p["cantidad_sugerida"], int) and p["cantidad_sugerida"] >= 0
    assert len(registro.predicciones) == 1
    assert registro.predicciones[0][3] == "novamercado-ventas"


def test_prediccion_corregida_informa_que_hizo(referencia, prediccion):
    prediccion["tienda_id"] = "T05"
    api, _ = cliente(referencia)
    calidad = api.post("/v1/prediccion", json=prediccion).json()["calidad"]

    assert calidad["estado"] == "corregido"
    assert calidad["observaciones"] == [
        {"campo": "tienda_id", "accion": "reparar", "detalle": "'T05' se interpretó como la tienda 5"}
    ]


def test_prediccion_con_supuestos_responde_advertencia(referencia, prediccion):
    prediccion["familias"] = prediccion["familias"][:2]
    api, _ = cliente(referencia)
    cuerpo = api.post("/v1/prediccion", json=prediccion).json()

    assert cuerpo["calidad"]["estado"] == "advertencia"
    assert len(cuerpo["predicciones"]) == 4


def test_prediccion_rechazada_responde_422_con_detail_y_se_registra(referencia, prediccion):
    prediccion["tienda_id"] = 99
    api, registro = cliente(referencia)
    r = api.post("/v1/prediccion", json=prediccion)

    assert r.status_code == 422
    assert r.json() == {"detail": "La tienda 99 no existe"}
    assert registro.rechazos == [("prediccion", prediccion, "La tienda 99 no existe", "rechazada")]


@pytest.mark.parametrize("contenido", ["{no es json", "", "[1, 2]", '{"tienda_id": NaN}'])
def test_cuerpo_invalido_responde_422(referencia, contenido):
    api, registro = cliente(referencia)
    r = api.post("/v1/prediccion", content=contenido, headers={"Content-Type": "application/json"})

    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert len(registro.rechazos) == 1


def test_sin_modelo_responde_503_y_registra_la_solicitud(referencia, prediccion):
    api, registro = cliente(referencia, predictor=None)
    r = api.post("/v1/prediccion", json=prediccion)

    assert r.status_code == 503
    assert "detail" in r.json()
    assert registro.rechazos[0][3] == "no_atendida"


def test_si_el_modelo_falla_responde_503(referencia, prediccion):
    api, registro = cliente(referencia, predictor=PredictorFalso(falla=True))

    assert api.post("/v1/prediccion", json=prediccion).status_code == 503
    assert registro.rechazos[0][3] == "no_atendida"


def test_si_no_se_puede_registrar_responde_503(referencia, prediccion):
    api, _ = cliente(referencia, registro=RegistroFalso(falla=True))
    r = api.post("/v1/prediccion", json=prediccion)

    assert r.status_code == 503
    assert "registrar" in r.json()["detail"]


def test_un_rechazo_que_no_se_puede_registrar_responde_503(referencia, prediccion):
    prediccion["tienda_id"] = 99
    api, _ = cliente(referencia, registro=RegistroFalso(falla=True))

    assert api.post("/v1/prediccion", json=prediccion).status_code == 503


def test_la_misma_fecha_se_puede_pedir_dos_veces(referencia, prediccion):
    api, registro = cliente(referencia)

    assert api.post("/v1/prediccion", json=prediccion).status_code == 200
    assert api.post("/v1/prediccion", json=prediccion).status_code == 200
    assert len(registro.predicciones) == 2


# POST /v1/observaciones


def test_observacion_valida_cumple_el_contrato(referencia, observacion):
    api, _ = cliente(referencia)
    r = api.post("/v1/observaciones", json=observacion)

    assert r.status_code == 200
    assert r.json() == {"registros_guardados": 4, "calidad": {"estado": "ok", "observaciones": []}}


def test_e09_reenvio_identico_responde_cero(referencia, observacion):
    api, _ = cliente(referencia)
    api.post("/v1/observaciones", json=observacion)
    r = api.post("/v1/observaciones", json=observacion)

    assert r.status_code == 200
    assert r.json()["registros_guardados"] == 0


def test_observacion_rechazada_responde_422(referencia, observacion):
    del observacion["fecha"]
    api, registro = cliente(referencia)
    r = api.post("/v1/observaciones", json=observacion)

    assert r.status_code == 422
    assert r.json() == {"detail": "Falta el campo obligatorio 'fecha'"}
    assert registro.rechazos[0][0] == "observaciones"


def test_observacion_no_necesita_modelo(referencia, observacion):
    api, _ = cliente(referencia, predictor=None)

    assert api.post("/v1/observaciones", json=observacion).status_code == 200


def test_observacion_que_no_se_puede_registrar_responde_503(referencia, observacion):
    api, _ = cliente(referencia, registro=RegistroFalso(falla=True))

    assert api.post("/v1/observaciones", json=observacion).status_code == 503


# GET /modelo y GET /health


def test_modelo_responde_nombre_alias_y_version_como_texto(referencia):
    api, _ = cliente(referencia)
    cuerpo = api.get("/modelo").json()

    assert cuerpo == {"nombre": "novamercado-ventas", "alias": "vigente", "version": "3"}
    assert all(isinstance(v, str) for v in cuerpo.values())


def test_modelo_sin_modelo_responde_503(referencia):
    api, _ = cliente(referencia, predictor=None)

    assert api.get("/modelo").status_code == 503


def test_health_ok_cuando_todo_funciona(referencia):
    api, _ = cliente(referencia, chequeos={"base de datos": lambda: None})
    r = api.get("/health")

    assert (r.status_code, r.json()) == (200, {"estado": "ok"})


def test_health_degradado_si_una_dependencia_falla(referencia):
    def base_caida():
        raise ConnectionError("connection refused\ndetalle largo")

    api, _ = cliente(referencia, chequeos={"base de datos": base_caida})
    r = api.get("/health")

    assert r.status_code == 200
    assert r.json() == {"estado": "degradado", "motivo": "base de datos no disponible: connection refused"}


def test_health_503_sin_modelo(referencia):
    api, _ = cliente(referencia, predictor=None)
    r = api.get("/health")

    assert r.status_code == 503
    assert r.json()["estado"] == "degradado"
    assert "modelo" in r.json()["motivo"]


def test_el_modelo_vigente_puede_cambiar_sin_reiniciar(referencia, prediccion):
    vigente = {"predictor": None}
    app = crear_app(Dependencias(referencia, RegistroFalso(), lambda: vigente["predictor"]))
    api = TestClient(app)

    assert api.get("/health").status_code == 503
    vigente["predictor"] = PredictorFalso()
    assert api.get("/health").status_code == 200
    assert api.post("/v1/prediccion", json=prediccion).json()["version_modelo"] == "3"


# POST /admin/reentrenar y GET /admin/reentrenar/{id}


def test_reentrenar_responde_202_con_id_de_texto(referencia):
    api, _ = cliente(referencia, orquestador=OrquestadorFalso())
    r = api.post("/admin/reentrenar")

    assert r.status_code == 202
    assert isinstance(r.json()["id"], str) and r.json()["id"]


def test_reentrenar_sin_airflow_responde_503(referencia):
    api, _ = cliente(referencia, orquestador=OrquestadorFalso(caido=True))
    r = api.post("/admin/reentrenar")

    assert r.status_code == 503
    assert "detail" in r.json()


def test_reentrenar_sin_orquestador_responde_503(referencia):
    api, _ = cliente(referencia)

    assert api.post("/admin/reentrenar").status_code == 503


def test_estado_en_curso_no_trae_resultado(referencia):
    orquestador = OrquestadorFalso()
    api, _ = cliente(referencia, orquestador=orquestador)
    id = api.post("/admin/reentrenar").json()["id"]

    assert api.get(f"/admin/reentrenar/{id}").json() == {"estado": "en_curso"}


def test_estado_exitoso_trae_el_resultado_que_dejo_el_dag(referencia):
    orquestador = OrquestadorFalso()
    api, registro = cliente(referencia, orquestador=orquestador)
    id = api.post("/admin/reentrenar").json()["id"]
    registro.reentrenamientos[id] = {
        "estado": "exitoso", "promovido": True, "version": "4",
        "motivo": "Costo en validación 18 210 vs 19 940 del vigente",
    }
    orquestador.estados[id] = "exitoso"

    assert api.get(f"/admin/reentrenar/{id}").json() == {
        "estado": "exitoso", "promovido": True, "version": "4",
        "motivo": "Costo en validación 18 210 vs 19 940 del vigente",
    }


def test_el_resultado_se_informa_aunque_airflow_este_caido(referencia):
    orquestador = OrquestadorFalso()
    api, registro = cliente(referencia, orquestador=orquestador)
    id = api.post("/admin/reentrenar").json()["id"]
    registro.reentrenamientos[id] = {"estado": "exitoso", "promovido": False, "version": "3", "motivo": "No supera"}
    orquestador.caido = True

    assert api.get(f"/admin/reentrenar/{id}").json()["estado"] == "exitoso"


def test_fallo_registrado_sin_version_usa_la_vigente_de_la_api(referencia):
    orquestador = OrquestadorFalso()
    api, registro = cliente(referencia, orquestador=orquestador)
    id = api.post("/admin/reentrenar").json()["id"]
    registro.reentrenamientos[id] = {"estado": "fallido", "promovido": False, "version": None, "motivo": "falló"}

    cuerpo = api.get(f"/admin/reentrenar/{id}").json()
    assert (cuerpo["estado"], cuerpo["promovido"], cuerpo["version"]) == ("fallido", False, "3")


def test_fallido_en_airflow_sin_resultado_informa_que_el_vigente_no_cambio(referencia):
    orquestador = OrquestadorFalso()
    api, _ = cliente(referencia, orquestador=orquestador)
    id = api.post("/admin/reentrenar").json()["id"]
    orquestador.estados[id] = "fallido"

    cuerpo = api.get(f"/admin/reentrenar/{id}").json()
    assert cuerpo["estado"] == "fallido" and cuerpo["promovido"] is False
    assert cuerpo["version"] == "3"
    assert "no cambió" in cuerpo["motivo"]


def test_id_desconocido_responde_404(referencia):
    api, _ = cliente(referencia, orquestador=OrquestadorFalso())

    assert api.get("/admin/reentrenar/no-existe").status_code == 404


def test_estado_con_airflow_caido_y_sin_resultado_responde_503(referencia):
    api, _ = cliente(referencia, orquestador=OrquestadorFalso(caido=True))

    assert api.get("/admin/reentrenar/manual__1").status_code == 503


# Con la base de datos real

URL_PRUEBAS = os.environ.get("NOVAMERCADO_BD_PRUEBAS_URL")


@pytest.mark.skipif(not URL_PRUEBAS, reason="sin NOVAMERCADO_BD_PRUEBAS_URL")
def test_api_con_postgres_guarda_y_es_idempotente(referencia, observacion, prediccion):
    from novamercado.persistencia import RegistroPostgres, crear_esquema, crear_motor, metadata

    motor = crear_motor(URL_PRUEBAS)
    metadata.drop_all(motor)
    crear_esquema(motor)
    registro = RegistroPostgres(motor)
    api, _ = cliente(referencia, registro=registro, chequeos={"base de datos": registro.verificar})

    assert api.post("/v1/observaciones", json=observacion).json()["registros_guardados"] == 4
    assert api.post("/v1/observaciones", json=copy.deepcopy(observacion)).json()["registros_guardados"] == 0
    assert api.post("/v1/prediccion", json=prediccion).status_code == 200
    assert api.post("/v1/prediccion", content="{roto", headers={"Content-Type": "application/json"}).status_code == 422
    assert api.get("/health").json() == {"estado": "ok"}
    motor.dispose()
