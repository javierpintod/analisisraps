"""
Módulo de Autenticación y Seguridad JWT (JSON Web Token - RFC 7519 HS256)
para el Analizador de Avance por RAPs SENA.

Implementa:
- Firma y validación de tokens JWT (HS256) en Python puro (sin dependencias binarias externas).
- Cifrado de contraseñas con PBKDF2-HMAC-SHA256 y sal criptográfica.
- Gestión de usuarios, auditoría de sesiones y revocación de tokens (JTI) en SQLite.
"""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

from database import DEFAULT_DB_PATH, LiquibaseRunner

JWT_SECRET_KEY = os.environ.get(
    "SENA_JWT_SECRET",
    "sena-sofia-plus-raps-jwt-secret-key-2026-hs256-seguridad"
)
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "sena-analisisraps"
JWT_EXPIRATION_SECONDS = 8 * 3600  # 8 horas de jornada académica


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode((segment + padding).encode("ascii"))


def encode_jwt(payload: Dict[str, Any], secret: str = JWT_SECRET_KEY) -> str:
    """Genera un JSON Web Token (JWT) estándar RFC 7519 firmado con HMAC-SHA256 (HS256)."""
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_jwt(token: str, secret: str = JWT_SECRET_KEY) -> Dict[str, Any]:
    """
    Decodifica y verifica criptográficamente un token JWT (HS256).
    Lanza ValueError si la firma es inválida o si el token ha expirado.
    """
    if not token or not isinstance(token, str):
        raise ValueError("Token JWT vacío o inválido.")

    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ValueError("Formato de token JWT inválido (se requieren 3 segmentos: header.payload.signature).")

    header_b64, payload_b64, sig_b64 = parts

    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
    except Exception:
        raise ValueError("Encabezado (header) del JWT corrupto.")

    if header.get("alg") != JWT_ALGORITHM:
        raise ValueError(f"Algoritmo JWT no soportado: {header.get('alg')}")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Firma del token JWT inválida (no autorizada).")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        raise ValueError("Cuerpo (payload) del JWT corrupto.")

    now_ts = int(time.time())
    exp = payload.get("exp")
    if exp is not None and int(exp) < now_ts:
        raise ValueError("El token JWT ha expirado. Por favor inicie sesión nuevamente.")

    return payload


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Genera hash seguro PBKDF2-HMAC-SHA256 con 100,000 iteraciones."""
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return dk.hex(), salt


def verify_password(password: str, expected_hash: str, salt: str) -> bool:
    calculated_hash, _ = hash_password(password, salt=salt)
    return hmac.compare_digest(calculated_hash, expected_hash)


class AuthService:
    """Servicio de autenticación de usuarios y control de sesiones JWT respaldado en SQLite."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        LiquibaseRunner(db_path=self.db_path).update()
        self._seed_default_users()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _seed_default_users(self) -> None:
        """Crea las cuentas por defecto del SENA si aún no existen en la tabla 'usuarios'."""
        default_accounts = [
            ("instructor", "sena2026", "Instructor Evaluador SENA", "INSTRUCTOR", "instructor@sena.edu.co"),
            ("coordinador", "admin2026", "Coordinador Académico SENA", "COORDINADOR", "coordinacion@sena.edu.co"),
        ]
        conn = self._get_connection()
        try:
            for username, raw_pass, nombre, rol, correo in default_accounts:
                exists = conn.execute(
                    "SELECT id FROM usuarios WHERE username = ?;", (username,)
                ).fetchone()
                if not exists:
                    pwd_hash, salt = hash_password(raw_pass)
                    conn.execute(
                        """
                        INSERT INTO usuarios (username, password_hash, salt, nombre_completo, rol, correo, activo)
                        VALUES (?, ?, ?, ?, ?, ?, 1);
                        """,
                        (username, pwd_hash, salt, nombre, rol, correo)
                    )
            conn.commit()
        finally:
            conn.close()

    def login(self, username: str, password: str, ip: str = "127.0.0.1") -> Dict[str, Any]:
        """Autentica las credenciales del usuario y emite un token JWT firmado (HS256)."""
        clean_user = (username or "").strip().lower()
        if not clean_user or not password:
            raise ValueError("Debe ingresar usuario y contraseña.")

        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM usuarios WHERE lower(username) = ? AND activo = 1;",
                (clean_user,)
            ).fetchone()

            if not row or not verify_password(password, row["password_hash"], row["salt"]):
                raise ValueError("Usuario o contraseña incorrectos.")

            now_ts = int(time.time())
            exp_ts = now_ts + JWT_EXPIRATION_SECONDS
            jti = secrets.token_hex(12)

            payload = {
                "iss": JWT_ISSUER,
                "sub": str(row["id"]),
                "username": row["username"],
                "nombre": row["nombre_completo"],
                "rol": row["rol"],
                "correo": row["correo"],
                "iat": now_ts,
                "exp": exp_ts,
                "jti": jti
            }
            token = encode_jwt(payload)

            now_str = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S")
            exp_str = datetime.fromtimestamp(exp_ts).strftime("%Y-%m-%d %H:%M:%S")

            conn.execute(
                "UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?;",
                (now_str, row["id"])
            )
            conn.execute(
                """
                INSERT INTO sesiones_jwt_audit (
                    usuario_id, username, jti, fecha_emision, fecha_expiracion, revocado, ip_origen
                ) VALUES (?, ?, ?, ?, ?, 0, ?);
                """,
                (row["id"], row["username"], jti, now_str, exp_str, ip)
            )
            conn.commit()

            return {
                "token": token,
                "token_type": "Bearer",
                "expires_in": JWT_EXPIRATION_SECONDS,
                "expires_at": exp_str,
                "user": {
                    "id": row["id"],
                    "username": row["username"],
                    "nombre": row["nombre_completo"],
                    "rol": row["rol"],
                    "correo": row["correo"]
                },
                "claims": payload
            }
        finally:
            conn.close()

    def extract_token(self, auth_header: Optional[str], query_token: Optional[str] = None) -> str:
        """Extrae el token desde el encabezado 'Authorization: Bearer <token>' o desde parámetro URL."""
        if auth_header and auth_header.strip().lower().startswith("bearer "):
            return auth_header.strip()[7:].strip()
        if query_token:
            return query_token.strip()
        raise ValueError("No se proporcionó token de autenticación JWT (Authorization: Bearer <token>).")

    def verify_token(self, token: str) -> Dict[str, Any]:
        """Verifica la firma, expiración y que el token no haya sido revocado en base de datos."""
        payload = decode_jwt(token)
        jti = payload.get("jti")
        if jti:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT revocado FROM sesiones_jwt_audit WHERE jti = ?;",
                    (jti,)
                ).fetchone()
                if row and int(row["revocado"]) == 1:
                    raise ValueError("El token JWT fue revocado (sesión cerrada).")
            finally:
                conn.close()
        return payload

    def logout(self, token: str) -> bool:
        """Revoca el token JWT marcando su identificador único (jti) en la tabla de auditoría."""
        try:
            payload = decode_jwt(token)
            jti = payload.get("jti")
            if not jti:
                return False
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "UPDATE sesiones_jwt_audit SET revocado = 1 WHERE jti = ?;",
                    (jti,)
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()
        except Exception:
            return False

