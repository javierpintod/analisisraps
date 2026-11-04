"""
Servicio de Notificaciones por Correo Electrónico para Aprendices en Estado Crítico SENA.

Implementa:
- Generación de plantillas HTML institucionales SENA de Alerta Temprana y Citación a Plan de Mejoramiento.
- Envío real por protocolo SMTP (TLS/SSL: Gmail, Office365, correo institucional) con librería estándar 'smtplib'.
- Modo Bandeja de Salida Local (SIMULADO_LOCAL) que genera archivos .eml/.html listos para abrir en Outlook/cliente de correo
  y registra la trazabilidad completa en la tabla 'notificaciones_correo'.
- Directorio persistente de correos electrónicos por aprendiz en 'directorio_contactos'.
"""

from datetime import datetime
from email.message import EmailMessage
import html
import os
import re
import smtplib
import sqlite3
import ssl
from typing import Any, Dict, List, Optional

from database import BASE_DIR, DEFAULT_DB_PATH, LiquibaseRunner

OUTBOX_DIR = os.path.join(BASE_DIR, "data", "outbox")


def build_default_sena_email(nombre: str, documento: str) -> str:
    """
    Genera un correo institucional sugerido (@soy.sena.edu.co) a partir del nombre y documento
    cuando el reporte de SofiaPlus no incluye columna de correo electrónico.
    """
    clean = (nombre or "").strip().lower()
    replacements = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}
    for k, v in replacements.items():
        clean = clean.replace(k, v)
    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in clean.split() if t]
    tokens = [t for t in tokens if t]
    doc_digits = re.sub(r"[^0-9]", "", str(documento or ""))[-2:] or "01"

    if len(tokens) >= 2:
        local_part = f"{tokens[0]}.{tokens[-1]}{doc_digits}"
    elif len(tokens) == 1:
        local_part = f"{tokens[0]}.{doc_digits}"
    else:
        local_part = f"aprendiz.{doc_digits}"

    return f"{local_part}@soy.sena.edu.co"


def build_critical_alert_email(
    aprendiz: Dict[str, Any],
    meta: Dict[str, Any],
    remitente_nombre: str = "Comité de Evaluación y Seguimiento SENA",
    custom_note: str = ""
) -> Dict[str, str]:
    """Construye el asunto, texto plano y cuerpo HTML del correo de alerta académica SENA."""
    ficha = str(meta.get("ficha") or "S/N")
    programa = str(meta.get("programa") or "Programa de Formación SENA")
    nombre = str(aprendiz.get("nombre") or "Aprendiz")
    doc = str(aprendiz.get("documento") or "")
    pct = aprendiz.get("porcentaje_avance", 0.0)
    situacion = str(aprendiz.get("situacion") or "🔴 Alto Riesgo Académico")
    n_aprob = int(aprendiz.get("raps_aprobados", 0))
    n_defic = int(aprendiz.get("raps_deficientes", 0))
    n_pend = int(aprendiz.get("raps_pendientes", 0))
    raps_def = aprendiz.get("raps_deficientes_lista") or []
    raps_pend = aprendiz.get("raps_pendientes_lista") or []

    asunto = f"[ALERTA ACADÉMICA SENA - Ficha {ficha}] Estado Crítico de Avance en RAPs ({pct}%) - {nombre}"

    def_items_html = "".join(
        f"<li style='margin-bottom:6px;color:#991B1B;'><strong>{html.escape(str(r))}</strong></li>"
        for r in raps_def[:15]
    ) or "<li style='color:#065F46;'>Ningún RAP calificado como Deficiente (D).</li>"

    pend_items_html = "".join(
        f"<li style='margin-bottom:5px;color:#92400E;'>{html.escape(str(r))}</li>"
        for r in raps_pend[:15]
    )
    if len(raps_pend) > 15:
        pend_items_html += f"<li style='color:#6B7280;'>... y {len(raps_pend) - 15} RAP(s) adicionales pendientes por evaluar.</li>"
    if not pend_items_html:
        pend_items_html = "<li style='color:#065F46;'>Sin RAPs pendientes.</li>"

    note_block = ""
    if custom_note and custom_note.strip():
        note_block = f"""
        <div style="background:#EFF6FF;border-left:4px solid #2563EB;padding:12px 16px;margin:16px 0;border-radius:6px;color:#1E3A8A;">
            <strong>Observación del Instructor / Coordinación:</strong><br>
            {html.escape(custom_note.strip())}
        </div>
        """

    cuerpo_html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>{html.escape(asunto)}</title></head>
<body style="font-family:'Segoe UI',Arial,sans-serif;background:#F3F4F6;margin:0;padding:24px;color:#1F2937;">
  <div style="max-width:680px;margin:0 auto;background:#FFFFFF;border-radius:12px;overflow:hidden;border:1px solid #E5E7EB;box-shadow:0 4px 12px rgba(0,0,0,0.06);">
    <div style="background:#00324D;border-bottom:4px solid #39A900;padding:20px 24px;color:#FFFFFF;">
      <div style="font-size:12px;letter-spacing:1px;color:#39A900;font-weight:700;">SERVICIO NACIONAL DE APRENDIZAJE - SENA</div>
      <h2 style="margin:6px 0 0 0;font-size:20px;">Notificación de Alerta Temprana y Plan de Mejoramiento</h2>
    </div>
    <div style="padding:24px;">
      <p style="margin-top:0;">Estimado(a) aprendiz <strong>{html.escape(nombre)}</strong> (Documento: <strong>{html.escape(doc)}</strong>),</p>
      <p>De manera atenta le informamos que, tras el corte de seguimiento de juicios evaluativos en <strong>SofiaPlus</strong> para la Ficha <strong>{html.escape(ficha)}</strong> del programa <strong>{html.escape(programa)}</strong>, su estado académico registra una alerta de atención prioritaria:</p>

      <table style="width:100%;border-collapse:collapse;margin:16px 0;background:#F9FAFB;border-radius:8px;overflow:hidden;border:1px solid #E5E7EB;">
        <tr>
          <td style="padding:12px;border-bottom:1px solid #E5E7EB;"><strong>Situación Actual:</strong></td>
          <td style="padding:12px;border-bottom:1px solid #E5E7EB;color:#DC2626;font-weight:700;">{html.escape(situacion)}</td>
        </tr>
        <tr>
          <td style="padding:12px;border-bottom:1px solid #E5E7EB;"><strong>Porcentaje de Avance Real:</strong></td>
          <td style="padding:12px;border-bottom:1px solid #E5E7EB;font-weight:700;">{pct}% ({n_aprob} RAPs aprobados)</td>
        </tr>
        <tr>
          <td style="padding:12px;"><strong>RAPs por Subsanar:</strong></td>
          <td style="padding:12px;"><strong style="color:#DC2626;">{n_defic} Deficientes (D)</strong> &nbsp;|&nbsp; <strong style="color:#D97706;">{n_pend} Pendientes (P)</strong></td>
        </tr>
      </table>

      {note_block}

      <h3 style="font-size:15px;color:#991B1B;margin:20px 0 8px 0;">⚠️ Resultados de Aprendizaje Calificados como Deficientes ({n_defic}):</h3>
      <ul style="background:#FEF2F2;padding:12px 16px 12px 32px;border-radius:8px;border:1px solid #FECACA;font-size:13px;">
        {def_items_html}
      </ul>

      <h3 style="font-size:15px;color:#92400E;margin:20px 0 8px 0;">⏳ Resultados de Aprendizaje Pendientes de Evaluación ({n_pend}):</h3>
      <ul style="background:#FFFBEB;padding:12px 16px 12px 32px;border-radius:8px;border:1px solid #FDE68A;font-size:13px;">
        {pend_items_html}
      </ul>

      <p style="font-size:14px;line-height:1.6;margin-top:20px;">
        Le solicitamos comunicarse a la mayor brevedad con su instructor técnico o vocero de ficha para concertar las actividades de su <strong>Plan de Mejoramiento Académico</strong> conforme al Reglamento del Aprendiz SENA.
      </p>

      <div style="margin-top:24px;padding-top:16px;border-top:1px solid #E5E7EB;font-size:12px;color:#6B7280;">
        Atentamente,<br>
        <strong>{html.escape(remitente_nombre)}</strong><br>
        Sistema de Análisis de Avance por RAPs - SENA
      </div>
    </div>
  </div>
</body>
</html>"""

    cuerpo_texto = (
        f"ALERTA ACADÉMICA SENA - Ficha {ficha} ({programa})\n"
        f"Aprendiz: {nombre} (Doc: {doc})\n"
        f"Situación: {situacion} | Avance Real: {pct}%\n"
        f"RAPs Aprobados: {n_aprob} | Deficientes (D): {n_defic} | Pendientes (P): {n_pend}\n\n"
        f"Por favor acérquese a su instructor para concertar su Plan de Mejoramiento Académico.\n"
        f"{remitente_nombre}"
    )

    return {
        "asunto": asunto,
        "cuerpo_html": cuerpo_html,
        "cuerpo_texto": cuerpo_texto
    }


class EmailNotificationService:
    """Gestiona directorio de correos, configuración SMTP y envío individual/masivo a aprendices críticos."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        LiquibaseRunner(db_path=self.db_path).update()
        os.makedirs(OUTBOX_DIR, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    # ------------------------------------------------------------------
    # DIRECTORIO DE CORREOS DE APRENDICES
    # ------------------------------------------------------------------
    def get_contacts_map(self) -> Dict[str, str]:
        conn = self._get_connection()
        try:
            rows = conn.execute("SELECT documento, correo FROM directorio_contactos;").fetchall()
            return {r["documento"]: r["correo"] for r in rows}
        finally:
            conn.close()

    def upsert_contact(self, documento: str, nombre: str, correo: str,
                       ficha: str = "", usuario: str = "sistema") -> Dict[str, str]:
        doc = str(documento or "").strip()
        mail = str(correo or "").strip().lower()
        if not doc or not mail or "@" not in mail:
            raise ValueError(f"Correo electrónico inválido para el documento {doc}: '{correo}'")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO directorio_contactos (documento, nombre, correo, ficha_codigo, actualizado_por, fecha_actualizacion)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(documento) DO UPDATE SET
                    nombre = excluded.nombre,
                    correo = excluded.correo,
                    ficha_codigo = excluded.ficha_codigo,
                    actualizado_por = excluded.actualizado_por,
                    fecha_actualizacion = excluded.fecha_actualizacion;
                """,
                (doc, nombre or doc, mail, ficha, usuario, now_str)
            )
            conn.commit()
            return {"documento": doc, "nombre": nombre, "correo": mail}
        finally:
            conn.close()

    def enrich_analysis_with_emails(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Asigna a cada aprendiz su correo guardado en BD o genera uno institucional sugerido."""
        if not analysis or "aprendices" not in analysis:
            return analysis
        contacts = self.get_contacts_map()
        for apr in analysis.get("aprendices", []):
            doc = str(apr.get("documento", ""))
            existing = apr.get("correo")
            if doc in contacts:
                apr["correo"] = contacts[doc]
            elif not existing:
                apr["correo"] = build_default_sena_email(apr.get("nombre", ""), doc)
        return analysis

    # ------------------------------------------------------------------
    # CONFIGURACIÓN SMTP
    # ------------------------------------------------------------------
    def get_smtp_config(self, include_password: bool = False) -> Dict[str, Any]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM configuracion_smtp WHERE id = 1;").fetchone()
            if not row:
                return {
                    "modo_envio": "SIMULADO_LOCAL",
                    "smtp_host": "smtp.gmail.com",
                    "smtp_port": 587,
                    "smtp_user": "",
                    "remitente_nombre": "Comité de Evaluación y Seguimiento SENA",
                    "remitente_correo": "seguimiento.sena@sena.edu.co",
                    "usar_tls": True,
                    "cc_coordinacion": "",
                    "password_configurada": False
                }
            data = dict(row)
            has_pwd = bool(data.get("smtp_password"))
            if not include_password:
                data.pop("smtp_password", None)
            data["usar_tls"] = bool(data.get("usar_tls", 1))
            data["password_configurada"] = has_pwd
            return data
        finally:
            conn.close()

    def save_smtp_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        modo = str(payload.get("modo_envio") or "SIMULADO_LOCAL").upper()
        if modo not in ("SMTP", "SIMULADO_LOCAL"):
            modo = "SIMULADO_LOCAL"
        host = str(payload.get("smtp_host") or "smtp.gmail.com").strip()
        port = int(payload.get("smtp_port") or 587)
        user = str(payload.get("smtp_user") or "").strip()
        pwd = payload.get("smtp_password")
        rem_nom = str(payload.get("remitente_nombre") or "Comité de Evaluación y Seguimiento SENA").strip()
        rem_cor = str(payload.get("remitente_correo") or user or "seguimiento.sena@sena.edu.co").strip()
        usar_tls = 1 if payload.get("usar_tls", True) else 0
        cc = str(payload.get("cc_coordinacion") or "").strip()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_connection()
        try:
            curr = conn.execute("SELECT smtp_password FROM configuracion_smtp WHERE id = 1;").fetchone()
            final_pwd = pwd if (pwd is not None and str(pwd) != "") else (curr["smtp_password"] if curr else "")

            conn.execute(
                """
                UPDATE configuracion_smtp SET
                    modo_envio = ?, smtp_host = ?, smtp_port = ?, smtp_user = ?,
                    smtp_password = ?, remitente_nombre = ?, remitente_correo = ?,
                    usar_tls = ?, cc_coordinacion = ?, fecha_actualizacion = ?
                WHERE id = 1;
                """,
                (modo, host, port, user, final_pwd, rem_nom, rem_cor, usar_tls, cc, now_str)
            )
            conn.commit()
            return self.get_smtp_config(include_password=False)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # ENVÍO DE CORREOS A APRENDICES CRÍTICOS
    # ------------------------------------------------------------------
    def _deliver_email(
        self,
        cfg: Dict[str, Any],
        destinatario: str,
        asunto: str,
        cuerpo_texto: str,
        cuerpo_html: str,
        ficha: str,
        documento: str
    ) -> Dict[str, str]:
        msg = EmailMessage()
        msg["Subject"] = asunto
        msg["From"] = f"{cfg['remitente_nombre']} <{cfg['remitente_correo']}>"
        msg["To"] = destinatario
        if cfg.get("cc_coordinacion"):
            msg["Cc"] = cfg["cc_coordinacion"]
        msg.set_content(cuerpo_texto)
        msg.add_alternative(cuerpo_html, subtype="html")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_doc = re.sub(r"[^a-zA-Z0-9_-]", "", str(documento))
        eml_filename = f"alerta_ficha_{ficha}_{safe_doc}_{ts}.eml"
        eml_path = os.path.join(OUTBOX_DIR, eml_filename)
        with open(eml_path, "wb") as f:
            f.write(bytes(msg))

        if cfg.get("modo_envio") == "SMTP" and cfg.get("smtp_host") and cfg.get("smtp_user") and cfg.get("smtp_password"):
            host = cfg["smtp_host"]
            port = int(cfg.get("smtp_port", 587))
            context = ssl.create_default_context()
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as server:
                    server.login(cfg["smtp_user"], cfg["smtp_password"])
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=15) as server:
                    if cfg.get("usar_tls"):
                        server.starttls(context=context)
                    server.login(cfg["smtp_user"], cfg["smtp_password"])
                    server.send_message(msg)
            return {
                "estado_envio": "ENVIADO_SMTP",
                "modo_envio": "SMTP",
                "archivo_eml": eml_filename,
                "detalle": f"Entregado vía SMTP ({host}:{port}) a {destinatario}"
            }

        return {
            "estado_envio": "ENVIADO_BANDEJA_LOCAL",
            "modo_envio": "SIMULADO_LOCAL",
            "archivo_eml": eml_filename,
            "detalle": f"Correo generado y archivado en data/outbox/{eml_filename} para {destinatario}"
        }

    def send_alerts_to_critical(
        self,
        analysis: Dict[str, Any],
        documentos: Optional[List[str]] = None,
        criterio: str = "criticos",
        custom_emails: Optional[Dict[str, str]] = None,
        custom_note: str = "",
        usuario: str = "Instructor SENA"
    ) -> Dict[str, Any]:
        """
        Envía correos de alerta académica a los aprendices seleccionados o que cumplan el criterio:
        - 'criticos': situacion_cod == 'riesgo' (< umbral amarillo)
        - 'con_deficientes': raps_deficientes > 0 o situacion_cod == 'riesgo'
        - 'riesgo_y_observacion': situacion_cod in ('riesgo', 'observacion')
        """
        self.enrich_analysis_with_emails(analysis)
        meta = analysis.get("meta", {})
        ficha = str(meta.get("ficha") or "SIN_FICHA")
        programa = str(meta.get("programa") or "Programa de Formación SENA")
        custom_emails = custom_emails or {}

        # Persistir cualquier correo personalizado enviado desde el formulario
        for doc_k, mail_v in custom_emails.items():
            if mail_v and "@" in mail_v:
                apr_match = next((a for a in analysis.get("aprendices", []) if str(a["documento"]) == str(doc_k)), None)
                nom_match = apr_match["nombre"] if apr_match else str(doc_k)
                self.upsert_contact(str(doc_k), nom_match, mail_v, ficha=ficha, usuario=usuario)
                if apr_match:
                    apr_match["correo"] = mail_v.strip().lower()

        doc_set = {str(d).strip() for d in documentos} if documentos else None
        targets: List[Dict[str, Any]] = []

        for apr in analysis.get("aprendices", []):
            doc = str(apr.get("documento", ""))
            if doc_set is not None:
                if doc in doc_set:
                    targets.append(apr)
                continue

            if criterio == "con_deficientes":
                if apr.get("situacion_cod") == "riesgo" or int(apr.get("raps_deficientes", 0)) > 0:
                    targets.append(apr)
            elif criterio == "riesgo_y_observacion":
                if apr.get("situacion_cod") in ("riesgo", "observacion"):
                    targets.append(apr)
            else:
                if apr.get("situacion_cod") == "riesgo":
                    targets.append(apr)

        if not targets:
            raise ValueError("No se encontraron aprendices críticos que coincidan con el criterio seleccionado.")

        cfg = self.get_smtp_config(include_password=True)
        enviados: List[Dict[str, Any]] = []
        errores: List[Dict[str, Any]] = []
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = self._get_connection()
        try:
            for apr in targets:
                doc = str(apr["documento"])
                correo = (custom_emails.get(doc) or apr.get("correo") or build_default_sena_email(apr["nombre"], doc)).strip()
                mail_data = build_critical_alert_email(
                    apr, meta, remitente_nombre=cfg["remitente_nombre"], custom_note=custom_note
                )
                try:
                    delivery = self._deliver_email(
                        cfg,
                        destinatario=correo,
                        asunto=mail_data["asunto"],
                        cuerpo_texto=mail_data["cuerpo_texto"],
                        cuerpo_html=mail_data["cuerpo_html"],
                        ficha=ficha,
                        documento=doc
                    )
                    cur = conn.execute(
                        """
                        INSERT INTO notificaciones_correo (
                            ficha_codigo, programa, documento, nombre_aprendiz, correo_destino,
                            situacion, porcentaje_avance, raps_deficientes, raps_pendientes,
                            asunto, cuerpo_html, estado_envio, modo_envio, archivo_eml,
                            detalle_respuesta, enviado_por, fecha_envio
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            ficha,
                            programa,
                            doc,
                            apr["nombre"],
                            correo,
                            apr["situacion"],
                            float(apr["porcentaje_avance"]),
                            int(apr["raps_deficientes"]),
                            int(apr["raps_pendientes"]),
                            mail_data["asunto"],
                            mail_data["cuerpo_html"],
                            delivery["estado_envio"],
                            delivery["modo_envio"],
                            delivery["archivo_eml"],
                            delivery["detalle"],
                            usuario,
                            now_str
                        )
                    )
                    enviados.append({
                        "notificacion_id": cur.lastrowid,
                        "documento": doc,
                        "nombre": apr["nombre"],
                        "correo": correo,
                        "porcentaje_avance": apr["porcentaje_avance"],
                        "raps_deficientes": apr["raps_deficientes"],
                        "estado_envio": delivery["estado_envio"],
                        "modo_envio": delivery["modo_envio"],
                        "detalle": delivery["detalle"]
                    })
                except Exception as e_send:
                    errores.append({
                        "documento": doc,
                        "nombre": apr["nombre"],
                        "correo": correo,
                        "error": str(e_send)
                    })
            conn.commit()
        finally:
            conn.close()

        return {
            "total_objetivo": len(targets),
            "total_enviados": len(enviados),
            "total_errores": len(errores),
            "modo_envio": cfg["modo_envio"],
            "enviados": enviados,
            "errores": errores
        }

    def list_notifications(self, ficha: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            if ficha:
                rows = conn.execute(
                    """
                    SELECT id, ficha_codigo, documento, nombre_aprendiz, correo_destino,
                           situacion, porcentaje_avance, raps_deficientes, raps_pendientes,
                           asunto, estado_envio, modo_envio, archivo_eml, detalle_respuesta,
                           enviado_por, fecha_envio
                    FROM notificaciones_correo
                    WHERE ficha_codigo = ?
                    ORDER BY id DESC LIMIT ?;
                    """,
                    (ficha, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, ficha_codigo, documento, nombre_aprendiz, correo_destino,
                           situacion, porcentaje_avance, raps_deficientes, raps_pendientes,
                           asunto, estado_envio, modo_envio, archivo_eml, detalle_respuesta,
                           enviado_por, fecha_envio
                    FROM notificaciones_correo
                    ORDER BY id DESC LIMIT ?;
                    """,
                    (limit,)
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_notification(self, notif_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM notificaciones_correo WHERE id = ?;", (int(notif_id),)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
