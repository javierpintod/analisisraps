--liquibase formatted sql

--changeset sena-seguridad:009-create-usuarios-table context:prod,dev labels:v1.3.0,seguridad,jwt
--comment: Tabla de usuarios del sistema SENA con contraseñas cifradas mediante PBKDF2-HMAC-SHA256
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    nombre_completo TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'INSTRUCTOR',
    correo TEXT DEFAULT '',
    activo INTEGER NOT NULL DEFAULT 1,
    fecha_creacion TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    ultimo_acceso TEXT
);
--rollback DROP TABLE IF EXISTS usuarios;

--changeset sena-seguridad:010-create-sesiones-jwt-audit context:prod,dev labels:v1.3.0,seguridad,jwt
--comment: Tabla de auditoría y control de revocación (blacklist/jti) de tokens JWT emitidos
CREATE TABLE IF NOT EXISTS sesiones_jwt_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    jti TEXT NOT NULL UNIQUE,
    fecha_emision TEXT NOT NULL,
    fecha_expiracion TEXT NOT NULL,
    revocado INTEGER NOT NULL DEFAULT 0,
    ip_origen TEXT DEFAULT '127.0.0.1',
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sesiones_jwt_jti
    ON sesiones_jwt_audit(jti, revocado);
--rollback DROP INDEX IF EXISTS idx_sesiones_jwt_jti; DROP TABLE IF EXISTS sesiones_jwt_audit;

