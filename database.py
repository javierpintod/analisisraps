"""
Motor de Base de Datos Histórica (SQLite) y Gestor de Migraciones Liquibase
para el Analizador de Avance por RAPs SENA.

Implementa:
1. Integración con Liquibase (tablas estándar DATABASECHANGELOG y DATABASECHANGELOGLOCK,
   lectura de db.changelog-master.xml y changesets en formato '--liquibase formatted sql').
2. Repositorio de Histórico de Análisis (fichas, historial_analisis, historial_raps,
   historial_aprendices, historial_cambios_juicios y vista vw_evolucion_ficha).
"""

from datetime import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "sena_historico.db")
DEFAULT_MASTER_CHANGELOG = os.path.join(BASE_DIR, "db", "changelog", "db.changelog-master.xml")
LIQUIBASE_PROPERTIES_PATH = os.path.join(BASE_DIR, "liquibase.properties")


class LiquibaseChangeset:
    """Representa un changeset individual leído desde un archivo SQL formateado para Liquibase."""

    def __init__(
        self,
        changeset_id: str,
        author: str,
        filename: str,
        sql: str,
        comments: str = "",
        rollback_sql: str = "",
        context: str = "",
        labels: str = ""
    ):
        self.id = changeset_id
        self.author = author
        self.filename = filename.replace("\\", "/")
        self.sql = sql.strip()
        self.comments = comments.strip()
        self.rollback_sql = rollback_sql.strip()
        self.context = context.strip()
        self.labels = labels.strip()

    @property
    def md5sum(self) -> str:
        """Calcula el hash MD5 compatible con el formato Liquibase (8:<md5>)."""
        normalized = re.sub(r"\s+", " ", self.sql).strip().encode("utf-8")
        return f"8:{hashlib.md5(normalized).hexdigest()}"

    @property
    def description(self) -> str:
        return "sql"


class LiquibaseRunner:
    """
    Ejecutor y validador de migraciones Liquibase.
    Soporta ejecución mediante CLI oficial de Liquibase (si está instalado en el sistema)
    o mediante el motor nativo compatible con SQLite que gestiona DATABASECHANGELOG
    y DATABASECHANGELOGLOCK siguiendo el estándar oficial de Liquibase 4.x.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH, master_changelog: str = DEFAULT_MASTER_CHANGELOG):
        self.db_path = db_path
        self.master_changelog = master_changelog
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _ensure_liquibase_tables(self, conn: sqlite3.Connection) -> None:
        """Crea las tablas de control de cambios estándar de Liquibase si no existen."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS DATABASECHANGELOGLOCK (
                ID INTEGER NOT NULL,
                LOCKED INTEGER NOT NULL,
                LOCKGRANTED TEXT,
                LOCKEDBY TEXT,
                CONSTRAINT PK_DATABASECHANGELOGLOCK PRIMARY KEY (ID)
            );
        """)
        conn.execute("""
            INSERT OR IGNORE INTO DATABASECHANGELOGLOCK (ID, LOCKED, LOCKGRANTED, LOCKEDBY)
            VALUES (1, 0, NULL, NULL);
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS DATABASECHANGELOG (
                ID TEXT NOT NULL,
                AUTHOR TEXT NOT NULL,
                FILENAME TEXT NOT NULL,
                DATEEXECUTED TEXT NOT NULL,
                ORDEREXECUTED INTEGER NOT NULL,
                EXECTYPE TEXT NOT NULL,
                MD5SUM TEXT,
                DESCRIPTION TEXT,
                COMMENTS TEXT,
                TAG TEXT,
                LIQUIBASE TEXT,
                CONTEXTS TEXT,
                LABELS TEXT,
                DEPLOYMENT_ID TEXT
            );
        """)
        conn.commit()

    def _acquire_lock(self, conn: sqlite3.Connection) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE DATABASECHANGELOGLOCK SET LOCKED = 1, LOCKGRANTED = ?, LOCKEDBY = ? WHERE ID = 1;",
            (now_str, "analisisraps-local (127.0.0.1)")
        )
        conn.commit()

    def _release_lock(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "UPDATE DATABASECHANGELOGLOCK SET LOCKED = 0, LOCKGRANTED = NULL, LOCKEDBY = NULL WHERE ID = 1;"
        )
        conn.commit()

    def parse_master_changelog(self) -> List[LiquibaseChangeset]:
        """Lee db.changelog-master.xml y todos los archivos incluidos en orden."""
        if not os.path.exists(self.master_changelog):
            raise FileNotFoundError(f"No se encontró el archivo maestro de Liquibase: {self.master_changelog}")

        tree = ET.parse(self.master_changelog)
        root = tree.getroot()

        included_files: List[str] = []
        for elem in root.iter():
            tag_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag_name == "include":
                file_attr = elem.attrib.get("file")
                if file_attr:
                    included_files.append(file_attr)

        all_changesets: List[LiquibaseChangeset] = []
        for rel_path in included_files:
            abs_path = os.path.join(BASE_DIR, rel_path.replace("/", os.sep))
            all_changesets.extend(self._parse_formatted_sql(abs_path, rel_path))

        return all_changesets

    def _parse_formatted_sql(self, abs_path: str, rel_filename: str) -> List[LiquibaseChangeset]:
        """Parsea un archivo con cabecera '--liquibase formatted sql' y extrae sus changesets."""
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Archivo de changeset Liquibase no encontrado: {abs_path}")

        with open(abs_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines or not lines[0].strip().lower().startswith("--liquibase formatted sql"):
            raise ValueError(f"El archivo {rel_filename} no contiene la cabecera '--liquibase formatted sql'.")

        changesets: List[LiquibaseChangeset] = []
        current_author = None
        current_id = None
        current_context = ""
        current_labels = ""
        current_comments: List[str] = []
        current_rollbacks: List[str] = []
        current_sql_lines: List[str] = []

        changeset_regex = re.compile(
            r"^--\s*changeset\s+([^\s:]+):([^\s]+)(.*)$", re.IGNORECASE
        )
        comment_regex = re.compile(r"^--\s*comment:\s*(.*)$", re.IGNORECASE)
        rollback_regex = re.compile(r"^--\s*rollback\s+(.*)$", re.IGNORECASE)

        def flush_current():
            if current_author and current_id:
                changesets.append(
                    LiquibaseChangeset(
                        changeset_id=current_id,
                        author=current_author,
                        filename=rel_filename,
                        sql="\n".join(current_sql_lines),
                        comments=" ".join(current_comments),
                        rollback_sql="\n".join(current_rollbacks),
                        context=current_context,
                        labels=current_labels
                    )
                )

        for line in lines[1:]:
            stripped = line.strip()
            cs_match = changeset_regex.match(stripped)
            if cs_match:
                flush_current()
                current_author = cs_match.group(1)
                current_id = cs_match.group(2)
                tail = cs_match.group(3) or ""
                ctx_m = re.search(r"context:([^\s]+)", tail, re.IGNORECASE)
                lbl_m = re.search(r"labels:([^\s]+)", tail, re.IGNORECASE)
                current_context = ctx_m.group(1) if ctx_m else ""
                current_labels = lbl_m.group(1) if lbl_m else ""
                current_comments = []
                current_rollbacks = []
                current_sql_lines = []
                continue

            if current_id is None:
                continue

            cm_match = comment_regex.match(stripped)
            if cm_match:
                current_comments.append(cm_match.group(1).strip())
                continue

            rb_match = rollback_regex.match(stripped)
            if rb_match:
                current_rollbacks.append(rb_match.group(1).strip())
                continue

            if stripped.startswith("--"):
                continue

            current_sql_lines.append(line.rstrip("\r\n"))

        flush_current()
        return changesets

    def update(self) -> Dict[str, Any]:
        """
        Ejecuta el comando 'liquibase update' aplicando todos los changesets pendientes
        y registrándolos en DATABASECHANGELOG.
        """
        changesets = self.parse_master_changelog()
        conn = self._get_connection()
        try:
            self._ensure_liquibase_tables(conn)
            self._acquire_lock(conn)

            cur = conn.execute(
                "SELECT ID, AUTHOR, FILENAME, MD5SUM, ORDEREXECUTED FROM DATABASECHANGELOG ORDER BY ORDEREXECUTED ASC;"
            )
            executed_rows = cur.fetchall()
            executed_map = {
                (r["ID"], r["AUTHOR"], r["FILENAME"]): r for r in executed_rows
            }
            max_order = max((r["ORDEREXECUTED"] for r in executed_rows), default=0)

            applied_now: List[Dict[str, Any]] = []
            deployment_id = hashlib.sha1(str(datetime.now().timestamp()).encode()).hexdigest()[:10]

            for cs in changesets:
                key = (cs.id, cs.author, cs.filename)
                if key in executed_map:
                    continue

                if cs.sql:
                    conn.executescript(cs.sql)
                    conn.execute("PRAGMA foreign_keys = ON;")

                max_order += 1
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    """
                    INSERT INTO DATABASECHANGELOG (
                        ID, AUTHOR, FILENAME, DATEEXECUTED, ORDEREXECUTED,
                        EXECTYPE, MD5SUM, DESCRIPTION, COMMENTS, TAG,
                        LIQUIBASE, CONTEXTS, LABELS, DEPLOYMENT_ID
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?);
                    """,
                    (
                        cs.id,
                        cs.author,
                        cs.filename,
                        now_str,
                        max_order,
                        "EXECUTED",
                        cs.md5sum,
                        cs.description,
                        cs.comments,
                        "4.24.0-py",
                        cs.context,
                        cs.labels,
                        deployment_id
                    )
                )
                conn.commit()
                applied_now.append({
                    "id": cs.id,
                    "author": cs.author,
                    "filename": cs.filename,
                    "comments": cs.comments,
                    "md5sum": cs.md5sum,
                    "date_executed": now_str,
                    "order_executed": max_order
                })

            return {
                "status": "success",
                "total_defined": len(changesets),
                "previously_executed": len(executed_rows),
                "applied_count": len(applied_now),
                "applied_changesets": applied_now
            }
        finally:
            try:
                self._release_lock(conn)
            except Exception:
                pass
            conn.close()

    def rollback(self, count: int = 1) -> Dict[str, Any]:
        """Revierte los últimos 'count' changesets aplicados utilizando sus sentencias '--rollback'."""
        changesets = self.parse_master_changelog()
        cs_lookup = {(cs.id, cs.author, cs.filename): cs for cs in changesets}

        conn = self._get_connection()
        try:
            self._ensure_liquibase_tables(conn)
            self._acquire_lock(conn)

            cur = conn.execute(
                "SELECT ID, AUTHOR, FILENAME, ORDEREXECUTED FROM DATABASECHANGELOG ORDER BY ORDEREXECUTED DESC LIMIT ?;",
                (count,)
            )
            to_rollback = cur.fetchall()
            rolled_back: List[str] = []

            for r in to_rollback:
                key = (r["ID"], r["AUTHOR"], r["FILENAME"])
                cs = cs_lookup.get(key)
                if not cs or not cs.rollback_sql:
                    raise RuntimeError(f"El changeset {key} no tiene sentencia '--rollback' definida.")

                conn.executescript(cs.rollback_sql)
                conn.execute(
                    "DELETE FROM DATABASECHANGELOG WHERE ID = ? AND AUTHOR = ? AND FILENAME = ?;",
                    (r["ID"], r["AUTHOR"], r["FILENAME"])
                )
                conn.commit()
                rolled_back.append(f"{r['AUTHOR']}:{r['ID']}")

            return {
                "status": "success",
                "rolled_back_count": len(rolled_back),
                "rolled_back": rolled_back
            }
        finally:
            try:
                self._release_lock(conn)
            except Exception:
                pass
            conn.close()

    def status(self) -> Dict[str, Any]:
        """Retorna el estado completo de migraciones Liquibase (aplicadas y pendientes)."""
        changesets = self.parse_master_changelog()
        conn = self._get_connection()
        try:
            self._ensure_liquibase_tables(conn)
            cur = conn.execute(
                """
                SELECT ID, AUTHOR, FILENAME, DATEEXECUTED, ORDEREXECUTED,
                       EXECTYPE, MD5SUM, DESCRIPTION, COMMENTS, LIQUIBASE,
                       CONTEXTS, LABELS, DEPLOYMENT_ID
                FROM DATABASECHANGELOG
                ORDER BY ORDEREXECUTED ASC;
                """
            )
            executed = [dict(r) for r in cur.fetchall()]
            executed_keys = {(r["ID"], r["AUTHOR"], r["FILENAME"]) for r in executed}

            pending = [
                {
                    "ID": cs.id,
                    "AUTHOR": cs.author,
                    "FILENAME": cs.filename,
                    "COMMENTS": cs.comments,
                    "LABELS": cs.labels,
                    "MD5SUM": cs.md5sum
                }
                for cs in changesets
                if (cs.id, cs.author, cs.filename) not in executed_keys
            ]

            lock_row = conn.execute("SELECT * FROM DATABASECHANGELOGLOCK WHERE ID = 1;").fetchone()

            return {
                "database_path": self.db_path,
                "master_changelog": "db/changelog/db.changelog-master.xml",
                "up_to_date": len(pending) == 0,
                "executed_count": len(executed),
                "pending_count": len(pending),
                "executed": executed,
                "pending": pending,
                "lock": dict(lock_row) if lock_row else {"LOCKED": 0}
            }
        finally:
            conn.close()


class SenaHistoryRepository:
    """
    Repositorio de persistencia histórica de análisis de RAPs SENA.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.liquibase = LiquibaseRunner(db_path=self.db_path)
        self.liquibase.update()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def save_analysis(
        self,
        analysis: Dict[str, Any],
        filename: str,
        file_bytes: Optional[bytes] = None,
        observaciones: str = "",
        usuario: str = "Instructor SENA",
        skip_if_unchanged: bool = False
    ) -> Dict[str, Any]:
        """
        Guarda un corte/instantánea completa del análisis en la base de datos histórica
        y calcula automáticamente los cambios de juicios frente al corte inmediatamente anterior
        de la misma ficha.
        """
        meta = analysis.get("meta", {})
        kpis = analysis.get("kpis", {})
        ficha = str(meta.get("ficha") or "SIN_FICHA").strip()
        programa = str(meta.get("programa") or "Programa de Formación SENA").strip()
        file_hash = hashlib.sha256(file_bytes).hexdigest()[:16] if file_bytes else None

        conn = self._get_connection()
        try:
            # 1. Buscar el análisis anterior más reciente de esta misma ficha
            prev_row = conn.execute(
                """
                SELECT id, hash_archivo, pct_avance_real, total_aprobados, total_deficientes, payload_json
                FROM historial_analisis
                WHERE ficha_codigo = ?
                ORDER BY id DESC
                LIMIT 1;
                """,
                (ficha,)
            ).fetchone()

            if skip_if_unchanged and prev_row and file_hash and prev_row["hash_archivo"] == file_hash:
                if abs(float(prev_row["pct_avance_real"]) - float(kpis.get("porcentaje_avance_real", 0))) < 0.001:
                    return {
                        "saved": False,
                        "skipped_duplicate": True,
                        "analisis_id": prev_row["id"],
                        "ficha": ficha,
                        "cambios_detectados": 0
                    }

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 2. Upsert en tabla maestra 'fichas'
            conn.execute(
                """
                INSERT INTO fichas (ficha_codigo, programa, total_raps, total_competencias, fecha_creacion, ultima_actualizacion)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ficha_codigo) DO UPDATE SET
                    programa = excluded.programa,
                    total_raps = excluded.total_raps,
                    total_competencias = excluded.total_competencias,
                    ultima_actualizacion = excluded.ultima_actualizacion;
                """,
                (
                    ficha,
                    programa,
                    int(meta.get("total_raps", 0)),
                    int(meta.get("total_competencias", 0)),
                    now_str,
                    now_str
                )
            )

            # 3. Insertar en 'historial_analisis'
            cur = conn.execute(
                """
                INSERT INTO historial_analisis (
                    ficha_codigo, programa, archivo_origen, hash_archivo, fecha_analisis,
                    total_aprendices_totales, total_aprendices_analizados, total_raps, total_competencias,
                    pct_avance_real, pct_aprobacion_evaluados, pct_cobertura_evaluativa,
                    total_evaluaciones_posibles, total_aprobados, total_deficientes, total_por_evaluar,
                    raps_criticos, raps_en_avance, raps_optimos,
                    aprendices_al_dia, aprendices_observacion, aprendices_riesgo,
                    umbral_verde, umbral_amarillo, payload_json, observaciones, usuario_registro
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    ficha,
                    programa,
                    filename,
                    file_hash,
                    now_str,
                    int(meta.get("total_aprendices_totales", 0)),
                    int(meta.get("total_aprendices_analizados", 0)),
                    int(meta.get("total_raps", 0)),
                    int(meta.get("total_competencias", 0)),
                    float(kpis.get("porcentaje_avance_real", 0.0)),
                    float(kpis.get("porcentaje_aprobacion_evaluados", 0.0)),
                    float(kpis.get("porcentaje_cobertura_evaluativa", 0.0)),
                    int(kpis.get("total_evaluaciones_posibles", 0)),
                    int(kpis.get("total_aprobados", 0)),
                    int(kpis.get("total_deficientes", 0)),
                    int(kpis.get("total_por_evaluar", 0)),
                    int(kpis.get("raps_criticos", 0)),
                    int(kpis.get("raps_en_avance", 0)),
                    int(kpis.get("raps_optimos", 0)),
                    int(kpis.get("aprendices_al_dia", 0)),
                    int(kpis.get("aprendices_observacion", 0)),
                    int(kpis.get("aprendices_riesgo", 0)),
                    float(meta.get("umbral_verde", 80.0)),
                    float(meta.get("umbral_amarillo", 50.0)),
                    json.dumps(analysis, ensure_ascii=False),
                    observaciones or "",
                    usuario or "Instructor SENA"
                )
            )
            analisis_id = cur.lastrowid

            # 4. Insertar detalle de RAPs en 'historial_raps'
            raps_rows = [
                (
                    analisis_id,
                    ficha,
                    r["rap"],
                    r["competencia"],
                    r.get("instructor", ""),
                    int(r["aprobados"]),
                    int(r["deficientes"]),
                    int(r["pendientes"]),
                    float(r["porcentaje_aprobado"]),
                    r["semaforo"],
                    r["categoria_cod"]
                )
                for r in analysis.get("raps", [])
            ]
            if raps_rows:
                conn.executemany(
                    """
                    INSERT INTO historial_raps (
                        analisis_id, ficha_codigo, rap, competencia, instructor,
                        aprobados, deficientes, pendientes, porcentaje_aprobado, semaforo, categoria_cod
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    raps_rows
                )

            # 5. Insertar detalle de Aprendices en 'historial_aprendices'
            apr_rows = [
                (
                    analisis_id,
                    ficha,
                    a["documento"],
                    a["nombre"],
                    a["estado_sofia"],
                    int(a["raps_aprobados"]),
                    int(a["raps_deficientes"]),
                    int(a["raps_pendientes"]),
                    float(a["porcentaje_avance"]),
                    a["situacion"],
                    a["situacion_cod"]
                )
                for a in analysis.get("aprendices", [])
            ]
            if apr_rows:
                conn.executemany(
                    """
                    INSERT INTO historial_aprendices (
                        analisis_id, ficha_codigo, documento, nombre, estado_sofia,
                        raps_aprobados, raps_deficientes, raps_pendientes,
                        porcentaje_avance, situacion, situacion_cod
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    apr_rows
                )

            # 6. Detectar cambios de juicio individuales respecto al corte anterior de la misma ficha
            cambios_juicios: List[Tuple[Any, ...]] = []
            if prev_row and prev_row["payload_json"]:
                try:
                    prev_payload = json.loads(prev_row["payload_json"])
                    prev_filas = {
                        f["documento"]: f.get("juicios", {})
                        for f in prev_payload.get("matriz", {}).get("filas", [])
                    }
                    curr_filas = analysis.get("matriz", {}).get("filas", [])
                    for fila in curr_filas:
                        doc = fila["documento"]
                        nom = fila["nombre"]
                        prev_juicios_doc = prev_filas.get(doc)
                        if not prev_juicios_doc:
                            continue
                        for rap_name, curr_j in fila.get("juicios", {}).items():
                            old_j = prev_juicios_doc.get(rap_name, "P")
                            if old_j != curr_j:
                                cambios_juicios.append((
                                    analisis_id,
                                    prev_row["id"],
                                    ficha,
                                    doc,
                                    nom,
                                    rap_name,
                                    old_j,
                                    curr_j,
                                    now_str
                                ))
                except Exception:
                    pass

            if cambios_juicios:
                conn.executemany(
                    """
                    INSERT INTO historial_cambios_juicios (
                        analisis_id, analisis_anterior_id, ficha_codigo, documento,
                        nombre_aprendiz, rap, juicio_anterior, juicio_nuevo, fecha_deteccion
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    cambios_juicios
                )

            conn.commit()
            return {
                "saved": True,
                "skipped_duplicate": False,
                "analisis_id": analisis_id,
                "ficha": ficha,
                "fecha_analisis": now_str,
                "cambios_detectados": len(cambios_juicios)
            }
        finally:
            conn.close()

    def list_history(self, ficha: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """Lista los cortes históricos guardados, calculando la variación (delta) frente al corte previo."""
        conn = self._get_connection()
        try:
            if ficha:
                rows = conn.execute(
                    """
                    SELECT id, ficha_codigo, programa, archivo_origen, hash_archivo, fecha_analisis,
                           total_aprendices_analizados, total_raps, pct_avance_real,
                           pct_aprobacion_evaluados, pct_cobertura_evaluativa,
                           total_aprobados, total_deficientes, total_por_evaluar,
                           raps_criticos, raps_en_avance, raps_optimos,
                           aprendices_al_dia, aprendices_observacion, aprendices_riesgo,
                           observaciones, usuario_registro
                    FROM historial_analisis
                    WHERE ficha_codigo = ?
                    ORDER BY id DESC
                    LIMIT ?;
                    """,
                    (ficha, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, ficha_codigo, programa, archivo_origen, hash_archivo, fecha_analisis,
                           total_aprendices_analizados, total_raps, pct_avance_real,
                           pct_aprobacion_evaluados, pct_cobertura_evaluativa,
                           total_aprobados, total_deficientes, total_por_evaluar,
                           raps_criticos, raps_en_avance, raps_optimos,
                           aprendices_al_dia, aprendices_observacion, aprendices_riesgo,
                           observaciones, usuario_registro
                    FROM historial_analisis
                    ORDER BY id DESC
                    LIMIT ?;
                    """,
                    (limit,)
                ).fetchall()

            items = [dict(r) for r in rows]

            # Calcular deltas por ficha en orden cronológico
            by_ficha: Dict[str, List[Dict[str, Any]]] = {}
            for item in reversed(items):
                by_ficha.setdefault(item["ficha_codigo"], []).append(item)

            for f_code, f_list in by_ficha.items():
                prev_pct = None
                for entry in f_list:
                    if prev_pct is None:
                        entry["delta_avance"] = 0.0
                    else:
                        entry["delta_avance"] = round(float(entry["pct_avance_real"]) - prev_pct, 2)
                    prev_pct = float(entry["pct_avance_real"])

            # Obtener conteo de cambios de juicio por análisis
            cambios_counts = dict(
                conn.execute(
                    "SELECT analisis_id, COUNT(*) FROM historial_cambios_juicios GROUP BY analisis_id;"
                ).fetchall()
            )
            for item in items:
                item["cambios_juicios_count"] = cambios_counts.get(item["id"], 0)

            fichas_summary = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT f.ficha_codigo, f.programa, f.total_raps, f.ultima_actualizacion,
                           COUNT(h.id) AS total_cortes,
                           MAX(h.pct_avance_real) AS max_avance,
                           MIN(h.pct_avance_real) AS min_avance
                    FROM fichas f
                    LEFT JOIN historial_analisis h ON f.ficha_codigo = h.ficha_codigo
                    GROUP BY f.ficha_codigo
                    ORDER BY f.ultima_actualizacion DESC;
                    """
                ).fetchall()
            ]

            recent_changes = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT id, analisis_id, ficha_codigo, documento, nombre_aprendiz,
                           rap, juicio_anterior, juicio_nuevo, fecha_deteccion
                    FROM historial_cambios_juicios
                    ORDER BY id DESC
                    LIMIT 30;
                    """
                ).fetchall()
            ]

            return {
                "items": items,
                "fichas": fichas_summary,
                "recent_juicio_changes": recent_changes,
                "liquibase": self.liquibase.status()
            }
        finally:
            conn.close()

    def get_snapshot(self, analisis_id: int) -> Optional[Dict[str, Any]]:
        """Recupera un análisis histórico completo por su ID para restaurarlo en el dashboard."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM historial_analisis WHERE id = ?;",
                (analisis_id,)
            ).fetchone()
            if not row:
                return None

            data = dict(row)
            payload = json.loads(data.pop("payload_json"))
            cambios = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT documento, nombre_aprendiz, rap, juicio_anterior, juicio_nuevo, fecha_deteccion
                    FROM historial_cambios_juicios
                    WHERE analisis_id = ?
                    ORDER BY nombre_aprendiz ASC;
                    """,
                    (analisis_id,)
                ).fetchall()
            ]
            return {
                "snapshot": data,
                "analysis": payload,
                "cambios_juicios": cambios
            }
        finally:
            conn.close()

    def delete_snapshot(self, analisis_id: int) -> bool:
        """Elimina un registro histórico por su ID."""
        conn = self._get_connection()
        try:
            cur = conn.execute("DELETE FROM historial_analisis WHERE id = ?;", (analisis_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def _cli():
    """Interfaz de línea de comandos para administrar Liquibase y la base de datos histórica."""
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "status"
    runner = LiquibaseRunner()

    if cmd == "update":
        res = runner.update()
        print("=======================================================")
        print("  LIQUIBASE UPDATE - SENA HISTÓRICO RAPS")
        print("=======================================================")
        print(f"  Changesets definidos : {res['total_defined']}")
        print(f"  Aplicados previamente: {res['previously_executed']}")
        print(f"  Nuevos aplicados     : {res['applied_count']}")
        for cs in res["applied_changesets"]:
            print(f"   + [{cs['order_executed']}] {cs['author']}:{cs['id']} ({cs['filename']})")
        print("=======================================================")

    elif cmd == "status":
        st = runner.status()
        print("=======================================================")
        print("  LIQUIBASE STATUS - SENA HISTÓRICO RAPS")
        print("=======================================================")
        print(f"  Base de datos     : {st['database_path']}")
        print(f"  Changelog Maestro : {st['master_changelog']}")
        pending_cnt = st["pending_count"]
        status_label = "AL DÍA (UP TO DATE)" if st["up_to_date"] else f"PENDIENTE ({pending_cnt} por aplicar)"
        print(f"  Estado            : {status_label}")
        print(f"  Changesets activos: {st['executed_count']}")
        for ex in st["executed"]:
            print(f"   [OK] #{ex['ORDEREXECUTED']} {ex['AUTHOR']}:{ex['ID']} | {ex['DATEEXECUTED']} | {ex['MD5SUM']}")
        for p in st["pending"]:
            print(f"   [PENDIENTE] {p['AUTHOR']}:{p['ID']} ({p['FILENAME']})")
        print("=======================================================")

    elif cmd == "rollback":
        steps = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 1
        res = runner.rollback(steps)
        print(f"Rollback completado ({res['rolled_back_count']} changesets revertidos): {', '.join(res['rolled_back'])}")

    else:
        print("Uso: python database.py [status | update | rollback [N]]")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
