# Decisiones técnicas y de producto

Cada decisión registra su contexto, las alternativas consideradas y su justificación.

## D-001: datos publicados en `data/publicados/`, versionados con DVC y un remoto local

**Fecha:** 2026-11-15

**Contexto:** el enunciado prohíbe que los datos y las credenciales formen parte del repositorio o de las imágenes, y pide que el README indique la carpeta donde se colocan los archivos publicados. El equipo docente clonará el tag de entrega, colocará ahí los archivos y levantará el producto sin las credenciales del estudiante.

**Decisión:**

- Todos los archivos publicados (`historico_ventas.csv`, `tiendas.csv`, `familias.csv`, `feriados.csv`, `costos.csv`, `catalogo_errores.md` y `ejemplos/`) viven en `data/publicados/`, con los nombres originales.
- Git ignora `data/`. Solo se versiona el puntero `data/publicados.dvc`.
- El remoto predeterminado de DVC es la carpeta `dvc-remote/` del proyecto, con una ruta relativa e ignorada por Git.

**Alternativas:**

| Alternativa | A favor | En contra |
|---|---|---|
| Carpeta local dentro del proyecto (elegida) | Funciona en cualquier clon, sin cuenta ni credenciales; los datos no salen de la carpeta del proyecto | No hay copia fuera de la máquina, salvo la sincronización de OneDrive |
| DagsHub u otro remoto externo | Copia fuera de la máquina | Requiere cuenta y token; redistribuye los datos del curso |
| Dejar los archivos en la raíz | No hay que moverlos | Mezcla datos y código; es más fácil versionarlos por error |
| Sin DVC | Más simple | No queda registro de qué versión de los datos se usó |

**Justificación:** el producto debe operar sin credenciales personales, y el equipo docente coloca sus propios archivos, por lo que no necesita descargar nada del remoto. DVC deja registrada la versión exacta de los datos con la que se desarrolló y se entrenó el primer modelo.

**Riesgo aceptado:** si se pierde la carpeta del proyecto, también se pierde el historial de versiones de los datos que no esté en otra copia.
