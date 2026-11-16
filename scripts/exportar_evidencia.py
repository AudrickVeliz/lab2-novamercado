"""Exporta la evidencia de funcionamiento desde el producto levantado (ver D-012).

- respuestas.md: la API ante los ejemplos publicados, válidos y defectuosos.
- mlflow.md: versiones del modelo, alias y reentrenamientos con sus métricas y linaje.
- airflow.md: ejecuciones del DAG de reentrenamiento.

Las credenciales de Airflow se leen del .env (no se escriben en el repositorio).

    python scripts/exportar_evidencia.py --datos data/publicados --salida docs/evidencia
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

NOMBRE_MODELO = "novamercado-ventas"


def pedir(url: str, metodo: str = "GET", cuerpo=None, token: str | None = None, crudo: bool = False):
    datos = None if cuerpo is None else (cuerpo.encode() if crudo else json.dumps(cuerpo).encode())
    encabezados = {"Content-Type": "application/json"}
    if token:
        encabezados["Authorization"] = f"Bearer {token}"
    solicitud = urllib.request.Request(url, data=datos, method=metodo, headers=encabezados)
    try:
        with urllib.request.urlopen(solicitud, timeout=60) as respuesta:
            return respuesta.status, json.loads(respuesta.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def leer_env(ruta: Path) -> dict[str, str]:
    valores = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if "=" in linea and not linea.lstrip().startswith("#"):
            clave, valor = linea.split("=", 1)
            valores[clave.strip()] = valor.strip()
    return valores


def respuestas(api: str, ejemplos: Path) -> list[str]:
    lineas = ["# Respuestas de la API ante los ejemplos publicados", "",
              "Cada ejemplo de `data/publicados/ejemplos/` enviado al producto levantado. Las políticas están en D-003.", ""]
    archivos = [ejemplos / "prediccion_valida.json", ejemplos / "observacion_valida.json", *sorted((ejemplos / "errores").glob("*.json"))]
    for archivo in archivos:
        texto = archivo.read_text(encoding="utf-8")
        ruta = "/v1/observaciones" if '"ventas"' in texto else "/v1/prediccion"
        codigo, cuerpo = pedir(api + ruta, "POST", texto, crudo=True)
        if "predicciones" in cuerpo:
            cuerpo = {**cuerpo, "predicciones": cuerpo["predicciones"][:3] + [f"… {len(cuerpo['predicciones']) - 3} familias más"]}
        lineas += [f"## {archivo.name}", "", f"`POST {ruta}` → **{codigo}**", "", "```json",
                   json.dumps(cuerpo, ensure_ascii=False, indent=2), "```", ""]
    # Problemas que no están en el catálogo.
    extra = [
        ("Tienda inexistente", "/v1/prediccion", '{"tienda_id": 99, "fecha": "2026-03-01", "familias": []}'),
        ("Fecha anterior a la apertura de la tienda 10", "/v1/prediccion", '{"tienda_id": 10, "fecha": "2025-03-14", "familias": []}'),
        ("Campos en conflicto", "/v1/prediccion", '{"tienda_id": 5, "tienda": 6, "fecha": "2026-03-01", "familias": []}'),
        ("JSON inválido", "/v1/prediccion", '{"tienda_id": 5,'),
        ("Ventas no enteras y fuera de rango", "/v1/observaciones",
         '{"tienda_id": 5, "fecha": "2026-03-01", "ventas": [{"familia_id": "lacteos", "ventas": "12,5"}, {"familia_id": "snacks", "ventas": 99999999999}]}'),
    ]
    lineas += ["# Problemas fuera del catálogo", ""]
    for titulo, ruta, texto in extra:
        codigo, cuerpo = pedir(api + ruta, "POST", texto, crudo=True)
        lineas += [f"## {titulo}", "", "```json", texto, "```", "", f"`POST {ruta}` → **{codigo}**", "", "```json",
                   json.dumps(cuerpo, ensure_ascii=False, indent=2), "```", ""]
    for ruta in ("/modelo", "/health"):
        codigo, cuerpo = pedir(api + ruta)
        lineas += [f"## GET {ruta}", "", f"**{codigo}**", "", "```json", json.dumps(cuerpo, ensure_ascii=False), "```", ""]
    return lineas


def mlflow(url: str) -> list[str]:
    _, versiones = pedir(f"{url}/api/2.0/mlflow/model-versions/search?" + urllib.parse.urlencode({"filter": f"name='{NOMBRE_MODELO}'", "max_results": 200}))
    _, modelo = pedir(f"{url}/api/2.0/mlflow/registered-models/get?name={NOMBRE_MODELO}")
    alias = {a["version"]: a["alias"] for a in modelo.get("registered_model", {}).get("aliases", [])}
    lineas = ["# MLflow", "", f"Model Registry: `{NOMBRE_MODELO}`, experimento `novamercado-ventas`. Interfaz: http://localhost:5000", "",
              "## Versiones del modelo", "", "| Versión | Alias | Promovida | Motivo | Creada | Run |", "|---|---|---|---|---|---|"]
    for v in sorted(versiones.get("model_versions", []), key=lambda v: int(v["version"])):
        etiquetas = {t["key"]: t["value"] for t in v.get("tags", [])}
        creada = datetime.fromtimestamp(int(v["creation_timestamp"]) / 1000).strftime("%Y-%m-%d %H:%M")
        lineas.append(f"| {v['version']} | {alias.get(v['version'], '')} | {etiquetas.get('promovido', '')} | {etiquetas.get('motivo', '')} | {creada} | `{v['run_id'][:8]}` |")

    _, experimento = pedir(f"{url}/api/2.0/mlflow/experiments/get-by-name?experiment_name=novamercado-ventas")
    id_experimento = experimento["experiment"]["experiment_id"]
    _, busqueda = pedir(f"{url}/api/2.0/mlflow/runs/search", "POST", {"experiment_ids": [id_experimento], "max_results": 500,
                                                                       "order_by": ["attributes.start_time ASC"]})
    corridas = busqueda.get("runs", [])
    hijos = {}
    for corrida in corridas:
        etiquetas = {t["key"]: t["value"] for t in corrida["data"].get("tags", [])}
        if "mlflow.parentRunId" in etiquetas:
            metricas = {m["key"]: m["value"] for m in corrida["data"].get("metrics", [])}
            parametros = {p["key"]: p["value"] for p in corrida["data"].get("params", [])}
            hijos.setdefault(etiquetas["mlflow.parentRunId"], {})[parametros.get("tipo")] = metricas
    lineas += ["", "## Reentrenamientos (runs padre)", "",
               "| Run | Validación | Observaciones de la BD | Costo baseline | Costo gradient boosting | Costo vigente | Promovido | Motivo |",
               "|---|---|---|---|---|---|---|---|"]
    for corrida in corridas:
        etiquetas = {t["key"]: t["value"] for t in corrida["data"].get("tags", [])}
        if "mlflow.parentRunId" in etiquetas:
            continue
        parametros = {p["key"]: p["value"] for p in corrida["data"].get("params", [])}
        metricas = {m["key"]: m["value"] for m in corrida["data"].get("metrics", [])}
        h = hijos.get(corrida["info"]["run_id"], {})
        costo = lambda t: f"{h.get(t, {}).get('costo', float('nan')):,.0f}".replace(",", " ")
        vigente = f"{metricas['costo_vigente']:,.0f}".replace(",", " ") if "costo_vigente" in metricas else "—"
        lineas.append(
            f"| `{corrida['info']['run_id'][:8]}` | {parametros.get('inicio_validacion')} a {parametros.get('fin_validacion')} | "
            f"{parametros.get('observaciones_registradas', '')} | {costo('baseline')} | {costo('gradient_boosting')} | {vigente} | "
            f"{etiquetas.get('promovido', '')} | {etiquetas.get('motivo', '')} |"
        )
    if corridas:
        ultimo = next(c for c in reversed(corridas) if "mlflow.parentRunId" not in {t["key"] for t in c["data"].get("tags", [])})
        parametros = {p["key"]: p["value"] for p in ultimo["data"].get("params", [])}
        lineas += ["", "## Linaje del último reentrenamiento", "", "| Parámetro | Valor |", "|---|---|"]
        lineas += [f"| `{k}` | {v} |" for k, v in sorted(parametros.items())]
    return lineas


def airflow(url: str, usuario: str, clave: str) -> list[str]:
    _, token = pedir(f"{url}/auth/token", "POST", {"username": usuario, "password": clave})
    _, corridas = pedir(f"{url}/api/v2/dags/reentrenamiento/dagRuns?limit=100&order_by=start_date", token=token["access_token"])
    lineas = ["# Airflow", "", "DAG `reentrenamiento`, disparado por `POST /admin/reentrenar`. Interfaz: http://localhost:8080", "",
              "| dag_run_id | Estado | Inicio | Fin | Duración |", "|---|---|---|---|---|"]
    for c in corridas.get("dag_runs", []):
        inicio, fin = c.get("start_date"), c.get("end_date")
        duracion = "—"
        if inicio and fin:
            duracion = f"{(datetime.fromisoformat(fin) - datetime.fromisoformat(inicio)).total_seconds():.0f} s"
        lineas.append(f"| `{c['dag_run_id']}` | {c['state']} | {(inicio or '')[:19]} | {(fin or '')[:19]} | {duracion} |")
    lineas += ["", f"Total: {corridas.get('total_entries', 0)} ejecuciones."]
    return lineas


def principal() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--api", default="http://127.0.0.1:8000")
    argumentos.add_argument("--mlflow", default="http://127.0.0.1:5000")
    argumentos.add_argument("--airflow", default="http://127.0.0.1:8080")
    argumentos.add_argument("--datos", default="data/publicados")
    argumentos.add_argument("--salida", default="docs/evidencia")
    argumentos.add_argument("--env", default=".env")
    a = argumentos.parse_args()
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    credenciales = leer_env(Path(a.env))
    _escribir(salida / "mlflow.md", mlflow(a.mlflow))
    _escribir(salida / "airflow.md", airflow(a.airflow, credenciales["AIRFLOW_USUARIO"], credenciales["AIRFLOW_CLAVE"]))
    _escribir(salida / "respuestas.md", respuestas(a.api, Path(a.datos) / "ejemplos"))
    print(f"Evidencia en {salida}")


def _escribir(ruta: Path, lineas: list[str]) -> None:
    # LF también en Windows, como el resto del repositorio.
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    principal()
