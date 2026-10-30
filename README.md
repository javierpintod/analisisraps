# 🌿 SENA - Analizador de Avance Real de Grupos frente a RAPs

Aplicación en Python diseñada para instructores, coordinadores académicos y comités de evaluación del **SENA (Servicio Nacional de Aprendizaje)**. Permite cargar el reporte de seguimiento o juicios evaluativos de una ficha de formación (exportado desde SofiaPlus o ZAJUNA en formato **Excel `.xlsx`, `.xls` o `.csv`**) y calcular de forma automática el **nivel de avance real del grupo frente a los Resultados de Aprendizaje (RAPs)** asociados al programa.

---

## 🚀 Características Principales

1. **Cálculo Matemático del Avance Real del Grupo**:
   - $\text{Avance Real} = \frac{\text{Total Juicios Aprobados (A)}}{\text{Total Aprendices Activos} \times \text{Total RAPs Asociados}} \times 100\%$
   - Eficacia sobre Evaluados: Porcentaje de aprobación frente a las evaluaciones ya emitidas ($A$ vs $D$).
   - Cobertura Evaluativa: Porcentaje de juicios registrados frente a los que faltan por emitir ($P$).

2. **Semáforo Pedagógico de RAPs**:
   - 🟢 **Óptimo** ($\ge 80\%$ de aprobación en el grupo).
   - 🟡 **En Avance** ($50\% - 79.9\%$).
   - 🔴 **Crítico / Rezago** ($< 50\%$ de aprobación).

3. **Diagnóstico Individual y Alerta Temprana de Aprendices**:
   - Clasificación por situación académica: **Al Día**, **En Observación** o **Alto Riesgo**.
   - Identificación exacta de los RAPs que cada aprendiz tiene calificados como **Deficientes ($D$)** o **Pendientes ($P$)**, facilitando la citación a comités de evaluación y formulación de **Planes de Mejoramiento**.

4. **Matriz de Seguimiento Aprendiz vs RAP**:
   - Tablero visual tipo mapa de calor donde se visualiza el estado de cada aprendiz en cada uno de los RAPs.

5. **Desglose por Competencia**:
   - Agrupación por competencias técnicas, transversales y clave del programa de formación.

6. **Filtros Dinámicos**:
   - Filtro inteligente por estado en SofiaPlus (e.g. incluir solo aprendices en estado `EN FORMACIÓN` para evitar sesgos por retiros o cancelaciones).
   - Umbrales de semáforo configurables en tiempo real.

7. **Exportación de Informes Oficiales en Excel**:
   - Descarga directa de un archivo `.xlsx` estilizado con 4 hojas:
     1. *Resumen Ejecutivo y Diagnóstico*.
     2. *Semáforo de RAPs*.
     3. *Seguimiento de Aprendices y Planes de Mejoramiento*.
     4. *Matriz Aprendiz vs RAP*.

8. **Conjunto de Datos de Prueba Incluido (Demo ADSO)**:
   - Viene con un botón para cargar inmediatamente un grupo de prueba realista del programa **Tecnólogo en Análisis y Desarrollo de Software (ADSO - Ficha 2714589)** con 25 aprendices y 10 RAPs auténticos.

---

## 📂 Estructura del Proyecto

```text
analisisraps/
├── data/
│   └── muestra_sena_juicios_evaluativos.xlsx  # Archivo de prueba SENA ADSO
├── static/
│   ├── index.html                             # Interfaz web moderna
│   ├── styles.css                             # Estilos glassmorphism y paleta SENA
│   └── app.js                                 # Lógica reactiva e interactiva
├── sena_processor.py                          # Motor de normalización y análisis
├── export_utils.py                            # Generador de reportes Excel
├── sample_data.py                             # Generador de datos sintéticos SENA
├── server.py                                  # Servidor HTTP y API REST (Python puro)
├── iniciar.bat                                # Lanzador automático de 1 clic (Windows)
├── requirements.txt                           # Requisitos de Python
└── README.md                                  # Documentación
```

---

## 💻 Requisitos y Ejecución

### 1. Requisitos Previos
- Python 3.9 o superior instalado en Windows.

### 2. Inicio Rápido (1 Clic)
Haz doble clic sobre el archivo:
```text
iniciar.bat
```
El navegador se abrirá automáticamente en:
👉 `http://localhost:8501`

### 3. Ejecución desde Terminal
Si prefieres iniciar manualmente desde PowerShell o CMD:
```powershell
# En la carpeta del proyecto:
python server.py
```
O usando el entorno virtual:
```powershell
.\.venv\Scripts\python.exe server.py
```

---

## 📋 Formato de Archivos Aceptados

El motor detecta automáticamente columnas aunque varíen según el centro o el reporte descargado de SofiaPlus/ZAJUNA:
- **Documento:** `Documento`, `Número de Documento`, `Identificación`, `Cédula`.
- **Aprendiz:** `Nombre Aprendiz`, `Aprendiz`, `Nombres y Apellidos`.
- **Estado Aprendiz:** `Estado del Aprendiz`, `Estado`, `Estado Matrícula`.
- **Competencia:** `Competencia`, `Nombre Competencia`.
- **Resultado de Aprendizaje (RAP):** `Resultado de Aprendizaje`, `RAP`, `Resultado`.
- **Juicio Evaluativo:** `Juicio Evaluativo`, `Juicio`, `Calificación` (`A` = Aprobado, `D` = Deficiente, `Por Evaluar` / vacíos = Pendiente).
- **Ficha y Programa:** `Número Ficha`, `Programa de Formación`.
