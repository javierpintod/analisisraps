--liquibase formatted sql

--changeset sena-notificaciones:017-permisos-notificaciones context:prod,dev labels:v1.6.0,notificaciones,rbac
--comment: Permisos RBAC para envio de alertas por correo electronico y configuracion SMTP
INSERT OR IGNORE INTO permisos (codigo, descripcion) VALUES
    ('notificaciones.enviar', 'Enviar alertas y citaciones por correo electronico a aprendices en estado critico'),
    ('notificaciones.configurar', 'Configurar parametros del servidor de correo SMTP');

INSERT OR IGNORE INTO rol_permisos (rol_codigo, permiso_codigo) VALUES
    ('INSTRUCTOR', 'notificaciones.enviar'),
    ('INSTRUCTOR', 'notificaciones.configurar'),
    ('COORDINADOR', 'notificaciones.enviar'),
    ('COORDINADOR', 'notificaciones.configurar'),
    ('AUDITOR', 'notificaciones.enviar');
--rollback DELETE FROM rol_permisos WHERE permiso_codigo IN ('notificaciones.enviar', 'notificaciones.configurar'); DELETE FROM permisos WHERE codigo IN ('notificaciones.enviar', 'notificaciones.configurar');

--changeset sena-notificaciones:018-directorio-contactos-aprendices context:prod,dev labels:v1.6.0,notificaciones
--comment: Directorio persistente de correos electronicos de aprendices para notificaciones de alerta temprana
CREATE TABLE IF NOT EXISTS directorio_contactos (
    documento TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    correo TEXT NOT NULL,
    ficha_codigo TEXT,
    actualizado_por TEXT DEFAULT 'sistema',
    fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_directorio_ficha ON directorio_contactos(ficha_codigo);
--rollback DROP INDEX IF EXISTS idx_directorio_ficha; DROP TABLE IF EXISTS directorio_contactos;

--changeset sena-notificaciones:019-configuracion-smtp context:prod,dev labels:v1.6.0,notificaciones
--comment: Configuracion del servidor de salida SMTP para envio de correos institucionales
CREATE TABLE IF NOT EXISTS configuracion_smtp (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    modo_envio TEXT NOT NULL DEFAULT 'SIMULADO_LOCAL',
    smtp_host TEXT NOT NULL DEFAULT 'smtp.gmail.com',
    smtp_port INTEGER NOT NULL DEFAULT 587,
    smtp_user TEXT NOT NULL DEFAULT '',
    smtp_password TEXT NOT NULL DEFAULT '',
    remitente_nombre TEXT NOT NULL DEFAULT 'Comité de Evaluación y Seguimiento SENA',
    remitente_correo TEXT NOT NULL DEFAULT 'seguimiento.sena@sena.edu.co',
    usar_tls INTEGER NOT NULL DEFAULT 1,
    cc_coordinacion TEXT NOT NULL DEFAULT '',
    fecha_actualizacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

INSERT OR IGNORE INTO configuracion_smtp (
    id, modo_envio, smtp_host, smtp_port, smtp_user, smtp_password,
    remitente_nombre, remitente_correo, usar_tls, cc_coordinacion
) VALUES (
    1, 'SIMULADO_LOCAL', 'smtp.gmail.com', 587, '', '',
    'Comité de Evaluación y Seguimiento SENA', 'seguimiento.sena@sena.edu.co', 1, ''
);
--rollback DROP TABLE IF EXISTS configuracion_smtp;

--changeset sena-notificaciones:020-historial-notificaciones-correo context:prod,dev labels:v1.6.0,notificaciones
--comment: Bitacora historica de correos electronicos enviados a aprendices en riesgo critico
CREATE TABLE IF NOT EXISTS notificaciones_correo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ficha_codigo TEXT NOT NULL,
    programa TEXT NOT NULL,
    documento TEXT NOT NULL,
    nombre_aprendiz TEXT NOT NULL,
    correo_destino TEXT NOT NULL,
    situacion TEXT NOT NULL,
    porcentaje_avance REAL NOT NULL,
    raps_deficientes INTEGER NOT NULL DEFAULT 0,
    raps_pendientes INTEGER NOT NULL DEFAULT 0,
    asunto TEXT NOT NULL,
    cuerpo_html TEXT NOT NULL,
    estado_envio TEXT NOT NULL DEFAULT 'ENVIADO',
    modo_envio TEXT NOT NULL DEFAULT 'SIMULADO_LOCAL',
    archivo_eml TEXT DEFAULT '',
    detalle_respuesta TEXT DEFAULT '',
    enviado_por TEXT NOT NULL DEFAULT 'sistema',
    fecha_envio TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_notif_ficha_fecha ON notificaciones_correo(ficha_codigo, fecha_envio DESC);
CREATE INDEX IF NOT EXISTS idx_notif_documento ON notificaciones_correo(documento);
--rollback DROP INDEX IF EXISTS idx_notif_documento; DROP INDEX IF EXISTS idx_notif_ficha_fecha; DROP TABLE IF EXISTS notificaciones_correo;

