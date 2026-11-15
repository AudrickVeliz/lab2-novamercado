"""Envoltura pyfunc del modelo, registrada en MLflow como "model from code".

MLflow guarda este archivo junto al modelo; el modelo entrenado viaja como
artefacto (modelo.joblib) y se carga al abrir el modelo registrado.
"""

import joblib
import mlflow
import pandas as pd
from mlflow.models import set_model


class ModeloNovaMercado(mlflow.pyfunc.PythonModel):
    def load_context(self, context) -> None:
        self.modelo = joblib.load(context.artifacts["modelo"])

    def predict(self, context, model_input: pd.DataFrame) -> pd.DataFrame:
        """Recibe las variables de novamercado.caracteristicas; devuelve venta esperada y cantidad sugerida."""
        esperada, sugerida = self.modelo.predecir(model_input)
        return pd.DataFrame({"venta_esperada": esperada, "cantidad_sugerida": sugerida})


set_model(ModeloNovaMercado())
