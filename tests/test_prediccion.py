import datetime as dt
import threading

import pandas as pd
import pytest

from novamercado.contrato import FamiliaPromocion, SolicitudPrediccion
from novamercado.prediccion import ModeloVigente, PredictorVentas

from datos_sinteticos import FAMILIAS


def solicitud(fecha=dt.date(2025, 8, 28), tienda=5):
    familias = tuple(FamiliaPromocion(familia_id=f, en_promocion=0) for f in FAMILIAS)
    return SolicitudPrediccion(tienda_id=tienda, fecha=fecha, familias=familias)


@pytest.fixture
def gbm(entrenado):
    return entrenado[2].modelo


def test_predice_cada_familia_con_sugerida_entera(gbm, catalogos, historico):
    predictor = PredictorVentas(gbm, "3", catalogos, historico, lambda *_: pd.DataFrame(columns=["fecha", "tienda_id", "familia_id", "ventas"]))
    predicciones = predictor.predecir(solicitud())

    assert [p.familia_id for p in predicciones] == FAMILIAS
    assert all(p.venta_esperada > 0 and isinstance(p.cantidad_sugerida, int) for p in predicciones)


def test_solo_pide_observaciones_anteriores_a_la_fecha(gbm, catalogos, historico):
    pedidos = []

    def leer(tienda, desde, antes_de):
        pedidos.append((tienda, desde, antes_de))
        return pd.DataFrame(columns=["fecha", "tienda_id", "familia_id", "ventas"])

    PredictorVentas(gbm, "3", catalogos, historico, leer).predecir(solicitud())

    [(tienda, desde, antes_de)] = pedidos
    assert tienda == 5 and antes_de == pd.Timestamp("2025-08-28") and desde < antes_de


def test_usa_las_observaciones_registradas_mas_alla_del_historico(gbm, catalogos, historico):
    fin = historico["fecha"].max()
    nuevas = pd.DataFrame(
        {"fecha": fin + pd.Timedelta(days=1), "tienda_id": 5, "familia_id": FAMILIAS, "ventas": 5000}
    )
    sin = PredictorVentas(gbm, "3", catalogos, historico, lambda *_: nuevas.iloc[0:0])
    con = PredictorVentas(gbm, "3", catalogos, historico, lambda *_: nuevas)
    fecha = (fin + pd.Timedelta(days=2)).date()

    esperada_sin = sum(p.venta_esperada for p in sin.predecir(solicitud(fecha)))
    esperada_con = sum(p.venta_esperada for p in con.predecir(solicitud(fecha)))
    assert esperada_con > esperada_sin


class FuenteFalsa:
    def __init__(self, gbm):
        self.gbm = gbm
        self.version = None
        self.caida = False
        self.descargas = 0

    def consultar(self):
        if self.caida:
            raise ConnectionError("MLflow no responde")
        return self.version

    def descargar(self, version):
        self.descargas += 1
        return self.gbm


def crear(gbm, catalogos, historico):
    return lambda modelo, version: PredictorVentas(modelo, version, catalogos, historico, lambda *_: None)


def test_carga_el_modelo_cuando_aparece_el_alias(gbm, catalogos, historico, tmp_path):
    fuente = FuenteFalsa(gbm)
    vigente = ModeloVigente(fuente.consultar, fuente.descargar, crear(gbm, catalogos, historico), tmp_path / "v.joblib")

    vigente.iniciar()
    assert vigente() is None
    fuente.version = "1"
    vigente.actualizar()
    assert vigente().version == "1"


def test_no_descarga_de_nuevo_la_misma_version(gbm, catalogos, historico):
    fuente = FuenteFalsa(gbm)
    fuente.version = "1"
    vigente = ModeloVigente(fuente.consultar, fuente.descargar, crear(gbm, catalogos, historico))

    vigente.actualizar()
    vigente.actualizar()
    assert fuente.descargas == 1


def test_cambia_de_version_sin_reiniciar(gbm, catalogos, historico):
    fuente = FuenteFalsa(gbm)
    fuente.version = "1"
    vigente = ModeloVigente(fuente.consultar, fuente.descargar, crear(gbm, catalogos, historico))
    vigente.actualizar()
    fuente.version = "2"
    vigente.actualizar()

    assert vigente().version == "2"


def test_si_mlflow_cae_sigue_con_el_modelo_cargado(gbm, catalogos, historico):
    fuente = FuenteFalsa(gbm)
    fuente.version = "1"
    vigente = ModeloVigente(fuente.consultar, fuente.descargar, crear(gbm, catalogos, historico))
    vigente.actualizar()
    fuente.caida = True

    with pytest.raises(ConnectionError):
        vigente.actualizar()
    assert vigente().version == "1"


def test_vigilar_no_se_detiene_si_mlflow_cae(gbm, catalogos, historico):
    fuente = FuenteFalsa(gbm)
    fuente.caida = True
    vigente = ModeloVigente(fuente.consultar, fuente.descargar, crear(gbm, catalogos, historico))
    detener = threading.Event()
    hilo = threading.Thread(target=vigente.vigilar, args=(detener, 0.01))
    hilo.start()
    threading.Event().wait(0.05)
    fuente.caida, fuente.version = False, "4"
    threading.Event().wait(0.1)
    detener.set()
    hilo.join(1)

    assert vigente().version == "4"


def test_arranca_con_la_copia_local_si_mlflow_no_responde(gbm, catalogos, historico, tmp_path):
    copia = tmp_path / "modelo" / "vigente.joblib"
    fuente = FuenteFalsa(gbm)
    fuente.version = "7"
    ModeloVigente(fuente.consultar, fuente.descargar, crear(gbm, catalogos, historico), copia).actualizar()

    fuente.caida = True
    reinicio = ModeloVigente(fuente.consultar, fuente.descargar, crear(gbm, catalogos, historico), copia)
    reinicio.iniciar()

    assert reinicio().version == "7"
    assert fuente.descargas == 1
