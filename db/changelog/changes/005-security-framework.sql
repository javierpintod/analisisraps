--liquibase formatted sql

--changeset sena-seguridad:011-rbac-roles-permisos context:prod,dev labels:v1.4.0,seguridad,rbac
--comment: Control de acceso basado en roles (RBAC) - roles, permisos y matriz rol-permiso
CREATE TABLE IF NOT EXISTS roles (
    codigo TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS permisos (
    codigo TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rol_permisos (
    rol_codigo TEXT NOT NULL,
    permiso_codigo TEXT NOT NULL,
    PRIMARY KEY (rol_codigo, permiso_codigo),
    FOREIGN KEY (rol_codigo) REFERENCES roles(codigo) ON DELETE CASCADE,
    FOREIGN KEY (permiso_codigo) REFERENCES permisos(codigo) ON DELETE CASCADE
);

INSERT OR IGNORE INTO roles (codigo, descripcion) VALUES
    ('INSTRUCTOR', 'Instructor evaluador: carga reportes y consulta su informacion'),
    ('COORDINADOR', 'Coordinador academico: control total, eliminacion y auditoria'),
    ('AUDITOR', 'Auditor: solo lectura de registros y bitacora de seguridad');

INSERT OR IGNORE INTO permisos (codigo, descripcion) VALUES
    ('analisis.ver', 'Ver dashboard de analisis de RAPs'),
    ('analisis.cargar', 'Cargar archivos Excel/CSV de juicios evaluativos'),
    ('reportes.exportar', 'Exportar informes oficiales en Excel'),
    ('historico.ver', 'Consultar cortes historicos'),
    ('historico.guardar', 'Guardar cortes historicos'),
    ('historico.eliminar', 'Eliminar cortes historicos'),
    ('registros.ver', 'Consultar registros fila a fila de los archivos Excel'),
    ('registros.eliminar', 'Eliminar cargas de archivos y sus registros'),
    ('auditoria.ver', 'Consultar bitacora de seguridad y verificar integridad');

INSERT OR IGNORE INTO rol_permisos (rol_codigo, permiso_codigo) VALUES
    ('INSTRUCTOR', 'analisis.ver'),
    ('INSTRUCTOR', 'analisis.cargar'),
    ('INSTRUCTOR', 'reportes.exportar'),
    ('INSTRUCTOR', 'historico.ver'),
    ('INSTRUCTOR', 'historico.guardar'),
    ('INSTRUCTOR', 'registros.ver'),
    ('COORDINADOR', 'analisis.ver'),
    ('COORDINADOR', 'analisis.cargar'),
    ('COORDINADOR', 'reportes.exportar'),
    ('COORDINADOR', 'historico.ver'),
    ('COORDINADOR', 'historico.guardar'),
    ('COORDINADOR', 'historico.eliminar'),
    ('COORDINADOR', 'registros.ver'),
    ('COORDINADOR', 'registros.eliminar'),
    ('COORDINADOR', 'auditoria.ver'),
    ('AUDITOR', 'analisis.ver'),
    ('AUDITOR', 'historico.ver'),
    ('AUDITOR', 'registros.ver'),
    ('AUDITOR', 'auditoria.ver');
--rollback DROP TABLE IF EXISTS rol_permisos; DROP TABLE IF EXISTS permisos; DROP TABLE IF EXISTS roles;

--changeset sena-seguridad:012-usuarios-bloqueo-fuerza-bruta context:prod,dev labels:v1.4.0,seguridad
--comment: Proteccion contra fuerza bruta - contador de intentos fallidos y bloqueo temporal de cuenta
ALTER TABLE usuarios ADD COLUMN intentos_fallidos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE usuarios ADD COLUMN bloqueado_hasta TEXT;
--rollback ALTER TABLE usuarios DROP COLUMN bloqueado_hasta; ALTER TABLE usuarios DROP COLUMN intentos_fallidos;

--changeset sena-seguridad:013-auditoria-eventos-inmutable context:prod,dev labels:v1.4.0,seguridad,auditoria
--comment: Bitacora de seguridad append-only con cadena de hashes SHA-256 (evidencia de manipulacion) y triggers de inmutabilidad
CREATE TABLE IF NOT EXISTS auditoria_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    evento TEXT NOT NULL,
    usuario_id INTEGER,
    username TEXT NOT NULL DEFAULT 'anonimo',
    rol TEXT,
    recurso TEXT DEFAULT '',
    resultado TEXT NOT NULL DEFAULT 'OK',
    detalle_json TEXT DEFAULT '{}',
    ip_origen TEXT DEFAULT '',
    hash_anterior TEXT NOT NULL,
    hash_evento TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_auditoria_fecha ON auditoria_eventos(fecha DESC);
CREATE INDEX IF NOT EXISTS idx_auditoria_evento_usuario ON auditoria_eventos(evento, username);

CREATE TRIGGER IF NOT EXISTS trg_auditoria_no_update
BEFORE UPDATE ON auditoria_eventos
BEGIN
    SELECT RAISE(ABORT, 'SEGURIDAD: la bitacora de auditoria es inmutable (UPDATE no permitido)');
END;

CREATE TRIGGER IF NOT EXISTS trg_auditoria_no_delete
BEFORE DELETE ON auditoria_eventos
BEGIN
    SELECT RAISE(ABORT, 'SEGURIDAD: la bitacora de auditoria es inmutable (DELETE no permitido)');
END;
--rollback DROP TRIGGER IF EXISTS trg_auditoria_no_delete; DROP TRIGGER IF EXISTS trg_auditoria_no_update; DROP INDEX IF EXISTS idx_auditoria_evento_usuario; DROP INDEX IF EXISTS idx_auditoria_fecha; DROP TABLE IF EXISTS auditoria_eventos;

