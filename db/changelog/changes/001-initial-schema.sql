--liquibase formatted sql

--changeset sena-arquitectura:001-create-fichas-table context:prod,dev labels:v1.0.0,schema-inicial
--comment: Creación de tabla maestra de Fichas de Caracterización SENA
CREATE TABLE IF NOT EXISTS fichas (
    ficha_codigo TEXT PRIMARY KEY,
    programa TEXT NOT NULL,
    total_raps INTEGER DEFAULT 0,
    total_competencias INTEGER DEFAULT 0,
    fecha_creacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    ultima_actualizacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
--rollback DROP TABLE IF EXISTS fichas;

--changeset sena-arquitectura:002-create-historial-analisis-table context:prod,dev labels:v1.0.0,schema-inicial
--comment: Tabla principal de instantáneas (snapshots) históricas de análisis por ficha
CREATE TABLE IF NOT EXISTS historial_analisis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ficha_codigo TEXT NOT NULL,
    programa TEXT NOT NULL,
    archivo_origen TEXT NOT NULL,
    hash_archivo TEXT,
    fecha_analisis TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    total_aprendices_totales INTEGER NOT NULL,
    total_aprendices_analizados INTEGER NOT NULL,
    total_raps INTEGER NOT NULL,
    total_competencias INTEGER NOT NULL,
    pct_avance_real REAL NOT NULL,
    pct_aprobacion_evaluados REAL NOT NULL,
    pct_cobertura_evaluativa REAL NOT NULL,
    total_evaluaciones_posibles INTEGER NOT NULL,
    total_aprobados INTEGER NOT NULL,
    total_deficientes INTEGER NOT NULL,
    total_por_evaluar INTEGER NOT NULL,
    raps_criticos INTEGER NOT NULL,
    raps_en_avance INTEGER NOT NULL,
    raps_optimos INTEGER NOT NULL,
    aprendices_al_dia INTEGER NOT NULL,
    aprendices_observacion INTEGER NOT NULL,
    aprendices_riesgo INTEGER NOT NULL,
    umbral_verde REAL NOT NULL DEFAULT 80.0,
    umbral_amarillo REAL NOT NULL DEFAULT 50.0,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (ficha_codigo) REFERENCES fichas(ficha_codigo) ON DELETE CASCADE
);
--rollback DROP TABLE IF EXISTS historial_analisis;

--changeset sena-arquitectura:003-create-historial-raps-table context:prod,dev labels:v1.0.0,schema-inicial
--comment: Detalle histórico de evaluación por cada Resultado de Aprendizaje (RAP) en un corte
CREATE TABLE IF NOT EXISTS historial_raps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analisis_id INTEGER NOT NULL,
    ficha_codigo TEXT NOT NULL,
    rap TEXT NOT NULL,
    competencia TEXT NOT NULL,
    instructor TEXT,
    aprobados INTEGER NOT NULL,
    deficientes INTEGER NOT NULL,
    pendientes INTEGER NOT NULL,
    porcentaje_aprobado REAL NOT NULL,
    semaforo TEXT NOT NULL,
    categoria_cod TEXT NOT NULL,
    FOREIGN KEY (analisis_id) REFERENCES historial_analisis(id) ON DELETE CASCADE
);
--rollback DROP TABLE IF EXISTS historial_raps;

--changeset sena-arquitectura:004-create-historial-aprendices-table context:prod,dev labels:v1.0.0,schema-inicial
--comment: Detalle histórico de avance individual por aprendiz en cada corte evaluativo
CREATE TABLE IF NOT EXISTS historial_aprendices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analisis_id INTEGER NOT NULL,
    ficha_codigo TEXT NOT NULL,
    documento TEXT NOT NULL,
    nombre TEXT NOT NULL,
    estado_sofia TEXT NOT NULL,
    raps_aprobados INTEGER NOT NULL,
    raps_deficientes INTEGER NOT NULL,
    raps_pendientes INTEGER NOT NULL,
    porcentaje_avance REAL NOT NULL,
    situacion TEXT NOT NULL,
    situacion_cod TEXT NOT NULL,
    FOREIGN KEY (analisis_id) REFERENCES historial_analisis(id) ON DELETE CASCADE
);
--rollback DROP TABLE IF EXISTS historial_aprendices;

