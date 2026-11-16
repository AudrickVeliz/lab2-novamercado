"""DAG de reentrenamiento (ver D-011). Solo orquesta: la lógica vive en novamercado.reentrenamiento.

Se dispara con POST /admin/reentrenar. No tiene calendario: las fechas del servicio
son simuladas y el reloj real no dice cuándo conviene reentrenar.
"""

from datetime import timedelta

from airflow.sdk import dag, get_current_context, task


@dag(
    dag_id="reentrenamiento",
    schedule=None,
    catchup=False,
    # Un reentrenamiento a la vez: dos simultáneos competirían por mover el alias.
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=10),
    default_args={"retries": 0},
    tags=["novamercado"],
)
def reentrenamiento():
    @task(execution_timeout=timedelta(minutes=9))
    def reentrenar() -> dict:
        # Importar dentro de la tarea mantiene liviano el análisis del archivo del DAG.
        from novamercado.reentrenamiento import ejecutar_y_registrar

        resultado = ejecutar_y_registrar(get_current_context()["dag_run"].run_id)
        return {"promovido": resultado.promovido, "version": resultado.version, "motivo": resultado.motivo}

    reentrenar()


reentrenamiento()
