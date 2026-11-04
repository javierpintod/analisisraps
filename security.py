"""
Marco de Seguridad de Base de Datos - SENA Analizador de RAPs.

Implementa:
1. RBAC (Role-Based Access Control): roles, permisos y matriz rol-permiso en SQLite.
2. Bitácora de auditoría append-only con cadena de hashes SHA-256 (tamper-evident):
   cada evento incluye el hash del evento anterior, de modo que cualquier alteración
   rompe la cadena y es detectable mediante verify_chain().
   La inmutabilidad se refuerza con triggers SQL que bloquean UPDATE/DELETE.
"""

from datetime import datetime
import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional

from database import DEFAULT_DB_PATH, LiquibaseRunner

GENESIS_HASH = "0" * 64


def _compute_event_hash(prev_hash: str, fecha: str, evento: str, username: str,
                        recurso: str, resultado: str, detalle_json: str, ip: str) -> str:
    material = "|".join([prev_hash, fecha, evento, username, recurso, resultado, detalle_json, ip])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class SecurityService:
    """Servicio central de autorización (RBAC) y auditoría de seguridad."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        LiquibaseRunner(db_path=self.db_path).update()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA secure_delete = ON;")
        return conn

    # ------------------------------------------------------------------
    # RBAC
    # ------------------------------------------------------------------
    def get_permissions(self, rol: Optional[str]) -> List[str]:
        if not rol:
            return []
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT permiso_codigo FROM rol_permisos WHERE rol_codigo = ? ORDER BY permiso_codigo;",
                (rol.upper(),)
            ).fetchall()
            return [r["permiso_codigo"] for r in rows]
        finally:
            conn.close()

    def has_permission(self, rol: Optional[str], permiso: str) -> bool:
        if not rol:
            return False
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT 1 FROM rol_permisos WHERE rol_codigo = ? AND permiso_codigo = ?;",
                (rol.upper(), permiso)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_role_matrix(self) -> Dict[str, Any]:
        conn = self._get_connection()
        try:
            roles = [dict(r) for r in conn.execute("SELECT codigo, descripcion FROM roles ORDER BY codigo;")]
            permisos = [dict(r) for r in conn.execute("SELECT codigo, descripcion FROM permisos ORDER BY codigo;")]
            matriz: Dict[str, List[str]] = {}
            for r in conn.execute("SELECT rol_codigo, permiso_codigo FROM rol_permisos;"):
                matriz.setdefault(r["rol_codigo"], []).append(r["permiso_codigo"])
            return {"roles": roles, "permisos": permisos, "matriz": matriz}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # AUDITORÍA CON CADENA DE HASHES
    # ------------------------------------------------------------------
    def log_event(
        self,
        evento: str,
        username: str = "anonimo",
        usuario_id: Optional[int] = None,
        rol: Optional[str] = None,
        recurso: str = "",
        resultado: str = "OK",
        detalle: Optional[Dict[str, Any]] = None,
        ip: str = ""
    ) -> str:
        """Registra un evento de seguridad encadenado al hash del evento anterior."""
        detalle_json = json.dumps(detalle or {}, ensure_ascii=False, sort_keys=True, default=str)
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        username = username or "anonimo"
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            last = conn.execute(
                "SELECT hash_evento FROM auditoria_eventos ORDER BY id DESC LIMIT 1;"
            ).fetchone()
            prev_hash = last["hash_evento"] if last else GENESIS_HASH
            event_hash = _compute_event_hash(prev_hash, fecha, evento, username, recurso, resultado, detalle_json, ip)
            conn.execute(
                """
                INSERT INTO auditoria_eventos (
                    fecha, evento, usuario_id, username, rol, recurso, resultado,
                    detalle_json, ip_origen, hash_anterior, hash_evento
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (fecha, evento, usuario_id, username, rol, recurso, resultado, detalle_json, ip, prev_hash, event_hash)
            )
            conn.commit()
            return event_hash
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def log_from_claims(self, claims: Optional[Dict[str, Any]], evento: str, recurso: str = "",
                        resultado: str = "OK", detalle: Optional[Dict[str, Any]] = None, ip: str = "") -> None:
        claims = claims or {}
        try:
            uid = int(claims["sub"]) if claims.get("sub") else None
        except (TypeError, ValueError):
            uid = None
        self.log_event(
            evento,
            username=claims.get("username", "anonimo"),
            usuario_id=uid,
            rol=claims.get("rol"),
            recurso=recurso,
            resultado=resultado,
            detalle=detalle,
            ip=ip
        )

    def list_events(self, limit: int = 200, evento: Optional[str] = None,
                    username: Optional[str] = None) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 200), 1000))
        sql = """
            SELECT id, fecha, evento, usuario_id, username, rol, recurso, resultado,
                   detalle_json, ip_origen, hash_anterior, hash_evento
            FROM auditoria_eventos WHERE 1 = 1
        """
        params: List[Any] = []
        if evento:
            sql += " AND evento = ?"
            params.append(evento)
        if username:
            sql += " AND username = ?"
            params.append(username)
        sql += " ORDER BY id DESC LIMIT ?;"
        params.append(limit)
        conn = self._get_connection()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def verify_chain(self) -> Dict[str, Any]:
        """Recalcula toda la cadena de hashes y detecta el primer evento alterado o fuera de secuencia."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, fecha, evento, username, recurso, resultado, detalle_json,
                       ip_origen, hash_anterior, hash_evento
                FROM auditoria_eventos ORDER BY id ASC;
                """
            ).fetchall()
        finally:
            conn.close()

        prev_hash = GENESIS_HASH
        for r in rows:
            if r["hash_anterior"] != prev_hash:
                return {"valid": False, "total_eventos": len(rows), "evento_roto_id": r["id"],
                        "motivo": "El enlace con el evento anterior no coincide (evento eliminado o insertado)."}
            expected = _compute_event_hash(
                r["hash_anterior"], r["fecha"], r["evento"], r["username"], r["recurso"] or "",
                r["resultado"], r["detalle_json"] or "{}", r["ip_origen"] or ""
            )
            if expected != r["hash_evento"]:
                return {"valid": False, "total_eventos": len(rows), "evento_roto_id": r["id"],
                        "motivo": "El contenido del evento fue alterado (hash no coincide)."}
            prev_hash = r["hash_evento"]

        return {"valid": True, "total_eventos": len(rows), "evento_roto_id": None,
                "ultimo_hash": prev_hash, "motivo": "Cadena de auditoría íntegra."}

