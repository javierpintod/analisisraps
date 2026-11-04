--liquibase formatted sql

--changeset sena-arquitectura:005-create-historical-indexes context:prod,dev labels:v1.1.0,rendimiento
--comment: Índices de optimización para consultas históricas por ficha, fecha y aprendiz
CREATE INDEX IF NOT EXISTS idx_historial_analisis_ficha_fecha
    ON historial_analisis(ficha_codigo, fecha_analisis DESC);

CREATE INDEX IF NOT EXISTS idx_historial_raps_analisis
    ON historial_raps(analisis_id, categoria_cod);

CREATE INDEX IF NOT EXISTS idx_historial_aprendices_analisis_doc
    ON historial_aprendices(analisis_id, documento);
--rollback DROP INDEX IF EXISTS idx_historial_aprendices_analisis_doc; DROP INDEX IF EXISTS idx_historial_raps_analisis; DROP INDEX IF EXISTS idx_historial_analisis_ficha_fecha;

--changeset sena-arquitectura:006-create-view-evolucion-ficha context:prod,dev labels:v1.1.0,analitica
--comment: Vista analítica para consultar la evolución cronológica de KPIs por Ficha SENA
CREATE VIEW IF NOT EXISTS vw_evolucion_ficha AS
SELECT
    ha.id AS analisis_id,
    ha.ficha_codigo,
    ha.programa,
    ha.archivo_origen,
    ha.fecha_analisis,
    ha.total_aprendices_analizados,
    ha.total_raps,
    ha.pct_avance_real,
    ha.pct_aprobacion_evaluados,
    ha.pct_cobertura_evaluativa,
    ha.total_aprobados,
    ha.total_deficientes,
    ha.total_por_evaluar,
    ha.raps_criticos,
    ha.raps_en_avance,
    ha.raps_optimos,
    ha.aprendices_al_dia,
    ha.aprendices_observacion,
    ha.aprendices_riesgo
FROM historial_analisis ha
ORDER BY ha.ficha_codigo ASC, ha.id ASC;
--rollback DROP VIEW IF EXISTS vw_evolucion_ficha;

