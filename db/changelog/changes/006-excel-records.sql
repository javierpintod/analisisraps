--liquibase formatted sql

--changeset sena-datos:014-cargas-archivo context:prod,dev labels:v1.5.0,registros
--comment: Registro de cada archivo Excel/CSV cargado con huella SHA-256, encabezados, mapeo de columnas y usuario responsable
CREATE TABLE IF NOT EXISTS cargas_archivo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_archivo TEXT NOT NULL,
    hash_sha256 TEXT NOT NULL UNIQUE,
    tamano_bytes INTEGER NOT NULL DEFAULT 0,
    total_filas INTEGER NOT NULL DEFAULT 0,
    total_columnas INTEGER NOT NULL DEFAULT 0,
    encabezados_json TEXT NOT NULL DEFAULT '[]',
    mapeo_json TEXT NOT NULL DEFAULT '{}',
    ficha_codigo TEXT,
    programa TEXT,
    analisis_id INTEGER,
    usuario_id INTEGER,
    username TEXT NOT NULL DEFAULT 'sistema',
    ip_origen TEXT DEFAULT '',
    fecha_carga TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (analisis_id) REFERENCES historial_analisis(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_cargas_ficha_fecha ON cargas_archivo(ficha_codigo, fecha_carga DESC);

CREATE TRIGGER IF NOT EXISTS trg_cargas_huella_inmutable
BEFORE UPDATE OF hash_sha256, nombre_archivo, total_filas, encabezados_json ON cargas_archivo
BEGIN
    SELECT RAISE(ABORT, 'SEGURIDAD: la huella y metadatos originales de la carga son inmutables');
END;
--rollback DROP TRIGGER IF EXISTS trg_cargas_huella_inmutable; DROP INDEX IF EXISTS idx_cargas_ficha_fecha; DROP TABLE IF EXISTS cargas_archivo;

--changeset sena-datos:015-registros-excel context:prod,dev labels:v1.5.0,registros
--comment: Almacenamiento fila a fila de cada registro del Excel (campos normalizados + fila original en JSON + hash de integridad)
CREATE TABLE IF NOT EXISTS registros_excel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    carga_id INTEGER NOT NULL,
    fila_numero INTEGER NOT NULL,
    ficha_codigo TEXT,
    programa TEXT,
    documento TEXT,
    nombre_aprendiz TEXT,
    estado_aprendiz TEXT,
    competencia TEXT,
    rap TEXT,
    juicio_original TEXT,
    juicio_normalizado TEXT NOT NULL DEFAULT 'P' CHECK (juicio_normalizado IN ('A', 'D', 'P')),
    fecha_juicio TEXT,
    instructor TEXT,
    datos_json TEXT NOT NULL,
    hash_fila TEXT NOT NULL,
    fecha_registro TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (carga_id, fila_numero),
    FOREIGN KEY (carga_id) REFERENCES cargas_archivo(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_registros_carga ON registros_excel(carga_id, fila_numero);
CREATE INDEX IF NOT EXISTS idx_registros_documento ON registros_excel(documento);
CREATE INDEX IF NOT EXISTS idx_registros_ficha_juicio ON registros_excel(ficha_codigo, juicio_normalizado);
CREATE INDEX IF NOT EXISTS idx_registros_rap ON registros_excel(rap);

CREATE TRIGGER IF NOT EXISTS trg_registros_no_update
BEFORE UPDATE ON registros_excel
BEGIN
    SELECT RAISE(ABORT, 'SEGURIDAD: los registros originales del Excel son inmutables (UPDATE no permitido)');
END;
--rollback DROP TRIGGER IF EXISTS trg_registros_no_update; DROP INDEX IF EXISTS idx_registros_rap; DROP INDEX IF EXISTS idx_registros_ficha_juicio; DROP INDEX IF EXISTS idx_registros_documento; DROP INDEX IF EXISTS idx_registros_carga; DROP TABLE IF EXISTS registros_excel;

--changeset sena-datos:016-vista-consulta-registros context:prod,dev labels:v1.5.0,registros,analitica
--comment: Vista de consulta de registros con los metadatos de la carga de origen
CREATE VIEW IF NOT EXISTS vw_registros_consulta AS
SELECT
    r.id,
    r.carga_id,
    r.fila_numero,
    r.ficha_codigo,
    r.programa,
    r.documento,
    r.nombre_aprendiz,
    r.estado_aprendiz,
    r.competencia,
    r.rap,
    r.juicio_original,
    r.juicio_normalizado,
    r.fecha_juicio,
    r.instructor,
    c.nombre_archivo,
    c.fecha_carga,
    c.username AS cargado_por
FROM registros_excel r
JOIN cargas_archivo c ON c.id = r.carga_id;
--rollback DROP VIEW IF EXISTS vw_registros_consulta;

