"""
Repositorio de Registros Excel - SENA Analizador de RAPs.

Almacena cada fila de los archivos Excel/CSV cargados (campos normalizados + fila original
completa en JSON) con un hash SHA-256 por fila para verificar su integridad, y permite
consultarlos posteriormente con filtros y paginación (consultas siempre parametrizadas).
"""

import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional

from database import DEFAULT_DB_PATH, LiquibaseRunner
from sena_processor import normalize_juicio

MAX_PAGE_SIZE = 200


def _to_text(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _row_hash(carga_id: int, fila_numero: int, datos_json: str) -> str:
    return hashlib.sha256(f"{carga_id}|{fila_numero}|{datos_json}".encode("utf-8")).hexdigest()


class ExcelRecordRepository:
    """Persistencia y consulta de los registros originales de cada archivo cargado."""

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
    # ALMACENAMIENTO
    # ------------------------------------------------------------------
    def store_upload(
        self,
        file_bytes: bytes,
        filename: str,
        headers: List[str],
        raw_rows: List[Dict[str, Any]],
        mapping: Dict[str, Optional[str]],
        meta: Optional[Dict[str, Any]] = None,
        analisis_id: Optional[int] = None,
        claims: Optional[Dict[str, Any]] = None,
        ip: str = ""
    ) -> Dict[str, Any]:
        """
        Guarda la carga y todas sus filas en una única transacción.
        Si el mismo archivo (mismo SHA-256) ya fue almacenado, no se duplica.
        """
        meta = meta or {}
        claims = claims or {}
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        def col(row: Dict[str, Any], key: str) -> Optional[str]:
            c = mapping.get(key)
            return _to_text(row.get(c)) if c else None

        conn = self._get_connection()
        try:
            existing = conn.execute(
                "SELECT id, total_filas, fecha_carga FROM cargas_archivo WHERE hash_sha256 = ?;",
                (file_hash,)
            ).fetchone()
            if existing:
                return {
                    "stored": False,
                    "duplicado": True,
                    "carga_id": existing["id"],
                    "total_filas": existing["total_filas"],
                    "hash_sha256": file_hash,
                    "mensaje": f"El archivo ya estaba registrado (carga #{existing['id']} del {existing['fecha_carga']})."
                }

            try:
                uid = int(claims["sub"]) if claims.get("sub") else None
            except (TypeError, ValueError):
                uid = None

            conn.execute("BEGIN;")
            cur = conn.execute(
                """
                INSERT INTO cargas_archivo (
                    nombre_archivo, hash_sha256, tamano_bytes, total_filas, total_columnas,
                    encabezados_json, mapeo_json, ficha_codigo, programa, analisis_id,
                    usuario_id, username, ip_origen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    filename,
                    file_hash,
                    len(file_bytes),
                    len(raw_rows),
                    len(headers),
                    json.dumps(headers, ensure_ascii=False),
                    json.dumps(mapping, ensure_ascii=False),
                    _to_text(meta.get("ficha")),
                    _to_text(meta.get("programa")),
                    analisis_id,
                    uid,
                    claims.get("username", "sistema"),
                    ip
                )
            )
            carga_id = cur.lastrowid

            default_ficha = _to_text(meta.get("ficha"))
            default_prog = _to_text(meta.get("programa"))
            batch = []
            for idx, row in enumerate(raw_rows, start=1):
                datos_json = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                doc = col(row, "documento")
                if doc and doc.endswith(".0"):
                    doc = doc[:-2]
                juicio_raw = col(row, "juicio")
                batch.append((
                    carga_id,
                    idx,
                    col(row, "ficha") or default_ficha,
                    col(row, "programa") or default_prog,
                    doc,
                    (col(row, "aprendiz") or "").upper() or None,
                    (col(row, "estado_aprendiz") or "").upper() or None,
                    col(row, "competencia"),
                    col(row, "rap"),
                    juicio_raw,
                    normalize_juicio(juicio_raw),
                    col(row, "fecha_juicio"),
                    col(row, "instructor"),
                    datos_json,
                    _row_hash(carga_id, idx, datos_json)
                ))

            conn.executemany(
                """
                INSERT INTO registros_excel (
                    carga_id, fila_numero, ficha_codigo, programa, documento, nombre_aprendiz,
                    estado_aprendiz, competencia, rap, juicio_original, juicio_normalizado,
                    fecha_juicio, instructor, datos_json, hash_fila
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                batch
            )
            conn.commit()
            return {
                "stored": True,
                "duplicado": False,
                "carga_id": carga_id,
                "total_filas": len(batch),
                "hash_sha256": file_hash,
                "mensaje": f"{len(batch)} registros almacenados en la carga #{carga_id}."
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # CONSULTA
    # ------------------------------------------------------------------
    def list_cargas(self, limit: int = 100) -> Dict[str, Any]:
        limit = max(1, min(int(limit or 100), 500))
        conn = self._get_connection()
        try:
            cargas = [
                dict(r) for r in conn.execute(
                    """
                    SELECT id, nombre_archivo, hash_sha256, tamano_bytes, total_filas, total_columnas,
                           ficha_codigo, programa, analisis_id, username, ip_origen, fecha_carga
                    FROM cargas_archivo ORDER BY id DESC LIMIT ?;
                    """,
                    (limit,)
                ).fetchall()
            ]
            fichas = [r[0] for r in conn.execute(
                "SELECT DISTINCT ficha_codigo FROM registros_excel WHERE ficha_codigo IS NOT NULL ORDER BY 1;"
            ).fetchall()]
            estados = [r[0] for r in conn.execute(
                "SELECT DISTINCT estado_aprendiz FROM registros_excel WHERE estado_aprendiz IS NOT NULL ORDER BY 1;"
            ).fetchall()]
            total_registros = conn.execute("SELECT COUNT(*) FROM registros_excel;").fetchone()[0]
            return {"cargas": cargas, "fichas": fichas, "estados": estados, "total_registros": total_registros}
        finally:
            conn.close()

    def query(self, filters: Optional[Dict[str, Any]] = None, page: int = 1,
              page_size: int = 50) -> Dict[str, Any]:
        """Consulta paginada de registros con filtros combinables (todas las entradas parametrizadas)."""
        f = filters or {}
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 50), MAX_PAGE_SIZE))

        where = ["1 = 1"]
        params: List[Any] = []

        if f.get("carga_id"):
            where.append("r.carga_id = ?")
            params.append(int(f["carga_id"]))
        if f.get("ficha"):
            where.append("r.ficha_codigo = ?")
            params.append(str(f["ficha"]).strip())
        if f.get("documento"):
            where.append("r.documento LIKE ?")
            params.append(f"{str(f['documento']).strip()}%")
        if f.get("rap"):
            where.append("r.rap LIKE ?")
            params.append(f"%{str(f['rap']).strip()}%")
        if f.get("competencia"):
            where.append("r.competencia LIKE ?")
            params.append(f"%{str(f['competencia']).strip()}%")
        if f.get("estado"):
            where.append("r.estado_aprendiz = ?")
            params.append(str(f["estado"]).strip().upper())
        if f.get("juicio") and str(f["juicio"]).upper() in ("A", "D", "P"):
            where.append("r.juicio_normalizado = ?")
            params.append(str(f["juicio"]).upper())
        if f.get("q"):
            term = f"%{str(f['q']).strip()}%"
            where.append(
                "(r.nombre_aprendiz LIKE ? OR r.documento LIKE ? OR r.rap LIKE ? "
                "OR r.competencia LIKE ? OR r.instructor LIKE ?)"
            )
            params.extend([term] * 5)

        where_sql = " AND ".join(where)
        conn = self._get_connection()
        try:
            total = conn.execute(
                f"SELECT COUNT(*) FROM registros_excel r WHERE {where_sql};", params
            ).fetchone()[0]

            resumen = {"A": 0, "D": 0, "P": 0}
            for r in conn.execute(
                f"SELECT r.juicio_normalizado AS j, COUNT(*) AS n FROM registros_excel r "
                f"WHERE {where_sql} GROUP BY r.juicio_normalizado;", params
            ).fetchall():
                resumen[r["j"]] = r["n"]

            aprendices = conn.execute(
                f"SELECT COUNT(DISTINCT r.documento) FROM registros_excel r WHERE {where_sql};", params
            ).fetchone()[0]

            offset = (page - 1) * page_size
            items = [
                dict(r) for r in conn.execute(
                    f"""
                    SELECT r.id, r.carga_id, r.fila_numero, r.ficha_codigo, r.documento, r.nombre_aprendiz,
                           r.estado_aprendiz, r.competencia, r.rap, r.juicio_original, r.juicio_normalizado,
                           r.fecha_juicio, r.instructor, c.nombre_archivo, c.fecha_carga
                    FROM registros_excel r
                    JOIN cargas_archivo c ON c.id = r.carga_id
                    WHERE {where_sql}
                    ORDER BY r.carga_id DESC, r.fila_numero ASC
                    LIMIT ? OFFSET ?;
                    """,
                    params + [page_size, offset]
                ).fetchall()
            ]

            pages = max(1, (total + page_size - 1) // page_size)
            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": pages,
                "resumen_juicios": resumen,
                "aprendices_distintos": aprendices
            }
        finally:
            conn.close()

    def get_record(self, record_id: int) -> Optional[Dict[str, Any]]:
        """Devuelve un registro con su fila original completa (datos_json)."""
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM registros_excel WHERE id = ?;", (int(record_id),)).fetchone()
            if not row:
                return None
            data = dict(row)
            data["datos_originales"] = json.loads(data.pop("datos_json"))
            data["integridad_ok"] = _row_hash(
                row["carga_id"], row["fila_numero"], row["datos_json"]
            ) == row["hash_fila"]
            return data
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # INTEGRIDAD Y ELIMINACIÓN
    # ------------------------------------------------------------------
    def verify_integrity(self, carga_id: int) -> Dict[str, Any]:
        """Recalcula el hash SHA-256 de cada fila y reporta las que hayan sido alteradas."""
        conn = self._get_connection()
        try:
            carga = conn.execute(
                "SELECT id, total_filas FROM cargas_archivo WHERE id = ?;", (int(carga_id),)
            ).fetchone()
            if not carga:
                raise ValueError(f"La carga #{carga_id} no existe.")
            rows = conn.execute(
                "SELECT id, carga_id, fila_numero, datos_json, hash_fila FROM registros_excel WHERE carga_id = ?;",
                (int(carga_id),)
            ).fetchall()
        finally:
            conn.close()

        alterados = [
            r["id"] for r in rows
            if _row_hash(r["carga_id"], r["fila_numero"], r["datos_json"]) != r["hash_fila"]
        ]
        faltantes = int(carga["total_filas"]) - len(rows)
        return {
            "carga_id": int(carga_id),
            "total_esperado": int(carga["total_filas"]),
            "total_encontrado": len(rows),
            "filas_faltantes": max(0, faltantes),
            "registros_alterados": alterados,
            "integro": not alterados and faltantes == 0
        }

    def delete_carga(self, carga_id: int) -> bool:
        conn = self._get_connection()
        try:
            cur = conn.execute("DELETE FROM cargas_archivo WHERE id = ?;", (int(carga_id),))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

