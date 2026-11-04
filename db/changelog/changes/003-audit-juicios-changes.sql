--liquibase formatted sql

--changeset sena-arquitectura:007-add-audit-metadata-columns context:prod,dev labels:v1.2.0,auditoria
--comment: Agrega columnas de observaciones pedagógicas y usuario evaluador en historial_analisis
ALTER TABLE historial_analisis ADD COLUMN observaciones TEXT DEFAULT '';
ALTER TABLE historial_analisis ADD COLUMN usuario_registro TEXT DEFAULT 'Instructor SENA';
--rollback SELECT 1;

--changeset sena-arquitectura:008-create-historial-cambios-juicios context:prod,dev labels:v1.2.0,auditoria
--comment: Tabla de trazabilidad de cambios de juicio (ej. P -> A, D -> A) entre cortes de una misma ficha
CREATE TABLE IF NOT EXISTS historial_cambios_juicios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analisis_id INTEGER NOT NULL,
    analisis_anterior_id INTEGER,
    ficha_codigo TEXT NOT NULL,
    documento TEXT NOT NULL,
    nombre_aprendiz TEXT NOT NULL,
    rap TEXT NOT NULL,
    juicio_anterior TEXT NOT NULL,
    juicio_nuevo TEXT NOT NULL,
    fecha_deteccion TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (analisis_id) REFERENCES historial_analisis(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cambios_juicios_analisis
    ON historial_cambios_juicios(analisis_id, ficha_codigo);
--rollback DROP INDEX IF EXISTS idx_cambios_juicios_analisis; DROP TABLE IF EXISTS historial_cambios_juicios;

