"""
Servidor HTTP y API REST en Python puro para la aplicación SENA Análisis RAPs.
Incluye autenticación JWT (RFC 7519 HS256), autorización RBAC, bitácora de auditoría
encadenada, almacenamiento fila a fila de los archivos Excel, envío de alertas por correo
a aprendices críticos, persistencia histórica en SQLite y migraciones Liquibase.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import base64
import json
import mimetypes
import os
import sys
from typing import Any, Dict, Optional
import urllib.parse

from sena_processor import SenaAnalyzer
from export_utils import create_excel_report
from sample_data import generate_sample_excel
from database import SenaHistoryRepository
from security import SecurityService
from excel_records import ExcelRecordRepository
from email_service import EmailNotificationService
from auth import AuthService

PORT = 8501
HOST = "localhost"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.realpath(os.path.join(BASE_DIR, "static"))
MAX_BODY_BYTES = 25 * 1024 * 1024  # 25 MB (archivo Excel codificado en base64)

# Inicializar Repositorios + Migraciones Liquibase + Seguridad + Correo + JWT
HISTORY_REPO = SenaHistoryRepository()
SECURITY = SecurityService()
RECORDS_REPO = ExcelRecordRepository()
EMAIL_SERVICE = EmailNotificationService()
AUTH_SERVICE = AuthService(security=SECURITY)

SYSTEM_CLAIMS = {"sub": None, "username": "sistema", "rol": "SISTEMA", "nombre": "Proceso automático"}

# Almacén en memoria de la sesión actual
SESSION_DATA = {
    "file_bytes": None,
    "filename": None,
    "last_analysis": None
}


def _user_label(claims: Dict[str, Any]) -> str:
    return f"{claims.get('nombre', 'Instructor')} ({claims.get('username', 'sena')})"


def preload_default_sample():
    """Precarga el archivo de reporte real de juicios para que la aplicación inicie con los datos de SofiaPlus."""
    try:
        real_path = os.path.join(BASE_DIR, "data", "Reporte_de_Juicios_Evaluativos.xls")
        sample_path = os.path.join(BASE_DIR, "data", "muestra_sena_juicios_evaluativos.xlsx")

        target_path = real_path if os.path.exists(real_path) else sample_path
        target_name = os.path.basename(target_path)

        with open(target_path, "rb") as f:
            content = f.read()
        SESSION_DATA["file_bytes"] = content
        SESSION_DATA["filename"] = target_name
        analyzer = SenaAnalyzer(content, target_name)
        analysis = EMAIL_SERVICE.enrich_analysis_with_emails(
            analyzer.run_analysis(filter_estados=["EN FORMACION"])
        )
        SESSION_DATA["last_analysis"] = analysis
        hist = HISTORY_REPO.save_analysis(
            analysis,
            target_name,
            file_bytes=content,
            observaciones="Corte inicial automático (Reporte SofiaPlus)",
            skip_if_unchanged=True
        )
        rec = RECORDS_REPO.store_upload(
            content, target_name, analyzer.headers, analyzer.raw_data, analyzer.column_mapping,
            meta=analysis.get("meta"), analisis_id=hist.get("analisis_id"), claims=SYSTEM_CLAIMS, ip="127.0.0.1"
        )
        print(f"  -> Archivo real SENA '{target_name}' precargado. {rec['mensaje']}")
    except Exception as e:
        print(f"  [Aviso] No se pudo precargar la muestra: {e}")


# Ejecutar precarga al importar/iniciar
preload_default_sample()


class SenaApiHandler(BaseHTTPRequestHandler):

    server_version = "SENA-RAPs"
    sys_version = ""

    def log_message(self, format, *args):
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def _security_headers(self, is_api: bool = True):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if is_api:
            self.send_header("Cache-Control", "no-store")

    def _send_json(self, status_code: int, data: dict):
        response = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self._security_headers(is_api=True)
        self.end_headers()
        self.wfile.write(response)

    def _send_file(self, content_type: str, data: bytes, filename: str = None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self._security_headers(is_api=bool(filename))
        self.end_headers()
        self.wfile.write(data)

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else ""

    def _require_auth(self, query_params: Optional[Dict[str, list]] = None,
                      permiso: Optional[str] = None) -> Optional[Dict[str, Any]]:
        auth_header = self.headers.get("Authorization")
        query_token = None
        if query_params and query_params.get("token"):
            query_token = query_params["token"][0]

        try:
            token = AUTH_SERVICE.extract_token(auth_header, query_token)
            claims = AUTH_SERVICE.verify_token(token)
        except Exception as e:
            self._send_json(401, {"success": False, "authenticated": False, "error": str(e)})
            return None

        if permiso and not SECURITY.has_permission(claims.get("rol"), permiso):
            SECURITY.log_from_claims(claims, "ACCESO_DENEGADO", recurso=self.path.split("?")[0],
                                     resultado="DENEGADO", detalle={"permiso_requerido": permiso},
                                     ip=self._client_ip())
            self._send_json(403, {
                "success": False,
                "authenticated": True,
                "error": f"Acceso denegado: su rol ({claims.get('rol')}) no tiene el permiso '{permiso}'."
            })
            return None
        return claims

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        ip = self._client_ip()

        def q(name: str, default: Any = None) -> Any:
            vals = query.get(name)
            return vals[0] if vals and vals[0] != "" else default

        if path == "/api/health":
            self._send_json(200, {
                "status": "ok",
                "app": "analisisraps-sena",
                "jwt_enabled": True,
                "liquibase": HISTORY_REPO.liquibase.status()
            })
            return

        elif path == "/api/auth/me":
            claims = self._require_auth(query)
            if not claims:
                return
            self._send_json(200, {
                "success": True,
                "authenticated": True,
                "user": {
                    "id": claims.get("sub"),
                    "username": claims.get("username"),
                    "nombre": claims.get("nombre"),
                    "rol": claims.get("rol"),
                    "correo": claims.get("correo")
                },
                "permisos": SECURITY.get_permissions(claims.get("rol")),
                "claims": claims
            })
            return

        elif path == "/api/notificaciones":
            claims = self._require_auth(query, "notificaciones.enviar")
            if not claims:
                return
            ficha_f = q("ficha")
            items = EMAIL_SERVICE.list_notifications(ficha=ficha_f)
            smtp_cfg = EMAIL_SERVICE.get_smtp_config(include_password=False)
            self._send_json(200, {
                "success": True,
                "notificaciones": items,
                "smtp": smtp_cfg
            })
            return

        elif path.startswith("/api/notificaciones/"):
            claims = self._require_auth(query, "notificaciones.enviar")
            if not claims:
                return
            id_part = path.split("/api/notificaciones/")[-1].strip("/")
            if id_part.isdigit():
                notif = EMAIL_SERVICE.get_notification(int(id_part))
                if not notif:
                    self._send_json(404, {"success": False, "error": "Notificación no encontrada."})
                    return
                self._send_json(200, {"success": True, "notificacion": notif})
                return

        elif path == "/api/history":
            claims = self._require_auth(query, "historico.ver")
            if not claims:
                return
            history_data = HISTORY_REPO.list_history(ficha=q("ficha"))
            self._send_json(200, {"success": True, **history_data})
            return

        elif path.startswith("/api/history/"):
            claims = self._require_auth(query, "historico.ver")
            if not claims:
                return
            id_part = path.split("/api/history/")[-1].strip("/")
            if id_part.isdigit():
                snap = HISTORY_REPO.get_snapshot(int(id_part))
                if not snap:
                    self._send_json(404, {"success": False, "error": "Corte histórico no encontrado."})
                    return
                snap["analysis"] = EMAIL_SERVICE.enrich_analysis_with_emails(snap["analysis"])
                SESSION_DATA["last_analysis"] = snap["analysis"]
                SESSION_DATA["filename"] = snap["snapshot"]["archivo_origen"]
                self._send_json(200, {"success": True, **snap})
                return

        elif path == "/api/registros":
            claims = self._require_auth(query, "registros.ver")
            if not claims:
                return
            try:
                filters = {k: q(k) for k in ("carga_id", "ficha", "documento", "rap", "competencia", "estado", "juicio", "q")}
                result = RECORDS_REPO.query(filters, page=int(q("page", 1)), page_size=int(q("page_size", 50)))
                SECURITY.log_from_claims(claims, "CONSULTA_REGISTROS", recurso="/api/registros",
                                         detalle={"filtros": {k: v for k, v in filters.items() if v},
                                                  "pagina": result["page"], "resultados": result["total"]}, ip=ip)
                self._send_json(200, {"success": True, **result})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/registros/cargas":
            claims = self._require_auth(query, "registros.ver")
            if not claims:
                return
            self._send_json(200, {"success": True, **RECORDS_REPO.list_cargas()})
            return

        elif path.startswith("/api/registros/cargas/") and path.endswith("/integridad"):
            claims = self._require_auth(query, "registros.ver")
            if not claims:
                return
            id_part = path[len("/api/registros/cargas/"):-len("/integridad")].strip("/")
            try:
                result = RECORDS_REPO.verify_integrity(int(id_part))
                SECURITY.log_from_claims(claims, "VERIFICAR_INTEGRIDAD", recurso=f"cargas_archivo#{id_part}",
                                         resultado="OK" if result["integro"] else "ALERTA", detalle=result, ip=ip)
                self._send_json(200, {"success": True, **result})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path.startswith("/api/registros/"):
            claims = self._require_auth(query, "registros.ver")
            if not claims:
                return
            id_part = path.split("/api/registros/")[-1].strip("/")
            if id_part.isdigit():
                rec = RECORDS_REPO.get_record(int(id_part))
                if not rec:
                    self._send_json(404, {"success": False, "error": "Registro no encontrado."})
                    return
                self._send_json(200, {"success": True, "registro": rec})
                return

        elif path == "/api/seguridad/auditoria":
            claims = self._require_auth(query, "auditoria.ver")
            if not claims:
                return
            eventos = SECURITY.list_events(limit=int(q("limit", 200)), evento=q("evento"), username=q("username"))
            self._send_json(200, {
                "success": True,
                "eventos": eventos,
                "cadena": SECURITY.verify_chain(),
                "rbac": SECURITY.get_role_matrix()
            })
            return

        elif path == "/api/sample":
            claims = self._require_auth(query, "analisis.ver")
            if not claims:
                return

            real_path = os.path.join(BASE_DIR, "data", "Reporte_de_Juicios_Evaluativos.xls")
            sample_path = os.path.join(BASE_DIR, "data", "muestra_sena_juicios_evaluativos.xlsx")
            target_path = real_path if os.path.exists(real_path) else sample_path
            target_name = os.path.basename(target_path)

            if not os.path.exists(target_path):
                generate_sample_excel(sample_path)
                target_path = sample_path
                target_name = "muestra_sena_juicios_evaluativos.xlsx"

            with open(target_path, "rb") as f:
                content = f.read()

            SESSION_DATA["file_bytes"] = content
            SESSION_DATA["filename"] = target_name

            analyzer = SenaAnalyzer(content, target_name)
            states = analyzer.get_unique_states()
            initial_filters = [s for s in states if "FORMACI" in s] or None
            analysis = EMAIL_SERVICE.enrich_analysis_with_emails(
                analyzer.run_analysis(filter_estados=initial_filters)
            )
            SESSION_DATA["last_analysis"] = analysis

            hist_info = HISTORY_REPO.save_analysis(
                analysis,
                target_name,
                file_bytes=content,
                observaciones="Carga de reporte SofiaPlus",
                usuario=_user_label(claims),
                skip_if_unchanged=True
            )
            rec_info = RECORDS_REPO.store_upload(
                content, target_name, analyzer.headers, analyzer.raw_data, analyzer.column_mapping,
                meta=analysis.get("meta"), analisis_id=hist_info.get("analisis_id"), claims=claims, ip=ip
            )

            self._send_json(200, {
                "success": True,
                "filename": target_name,
                "columns": analyzer.get_available_columns(),
                "mapping": analyzer.get_detected_columns(),
                "states": states,
                "analysis": analysis,
                "history_record": hist_info,
                "records_info": rec_info
            })
            return

        elif path == "/api/export":
            claims = self._require_auth(query, "reportes.exportar")
            if not claims:
                return
            if not SESSION_DATA["last_analysis"]:
                self._send_json(400, {"error": "No hay análisis previo para exportar."})
                return
            excel_bytes = create_excel_report(SESSION_DATA["last_analysis"])
            ficha = SESSION_DATA["last_analysis"]["meta"]["ficha"]
            clean_ficha = "".join(c for c in ficha if c.isalnum() or c in "-_")
            export_name = f"Informe_Avance_RAPs_Ficha_{clean_ficha}.xlsx"
            SECURITY.log_from_claims(claims, "EXPORTAR_EXCEL", recurso=export_name, ip=ip)
            self._send_file("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", excel_bytes, export_name)
            return

        elif path.startswith("/api/"):
            self._send_json(404, {"success": False, "error": "Endpoint no encontrado."})
            return

        # Servir archivos estáticos del frontend
        if path == "/":
            path = "/index.html"

        requested = os.path.realpath(os.path.join(STATIC_DIR, urllib.parse.unquote(path).lstrip("/\\")))
        if requested.startswith(STATIC_DIR + os.sep) and os.path.isfile(requested):
            mime_type, _ = mimetypes.guess_type(requested)
            mime_type = mime_type or "application/octet-stream"
            with open(requested, "rb") as f:
                data = f.read()
            self._send_file(mime_type, data)
        else:
            self.send_response(404)
            self._security_headers()
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        ip = self._client_ip()

        content_length = int(self.headers.get("Content-Length", 0) or 0)
        if content_length > MAX_BODY_BYTES:
            self._send_json(413, {"success": False, "error": "El archivo excede el tamaño máximo permitido (25 MB)."})
            return
        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"

        if path == "/api/auth/login":
            try:
                payload = json.loads(post_data.decode("utf-8"))
                auth_result = AUTH_SERVICE.login(payload.get("username", ""), payload.get("password", ""), ip=ip)
                self._send_json(200, {"success": True, **auth_result})
            except Exception as e:
                self._send_json(401, {"success": False, "error": str(e)})
            return

        elif path == "/api/auth/logout":
            try:
                token = AUTH_SERVICE.extract_token(self.headers.get("Authorization"))
                revoked = AUTH_SERVICE.logout(token, ip=ip)
                self._send_json(200, {"success": True, "revoked": revoked})
            except Exception as e:
                self._send_json(200, {"success": True, "revoked": False, "info": str(e)})
            return

        elif path == "/api/upload":
            claims = self._require_auth(query, "analisis.cargar")
            if not claims:
                return
            try:
                payload = json.loads(post_data.decode("utf-8"))
                file_bytes = base64.b64decode(payload["content_base64"])
                filename = os.path.basename(str(payload["filename"]))[:200]
                if not filename.lower().endswith((".xlsx", ".xlsm", ".xls", ".csv")):
                    raise ValueError("Tipo de archivo no permitido. Use .xlsx, .xls o .csv.")
                observaciones = payload.get("observaciones", "Carga de archivo desde interfaz web")

                SESSION_DATA["file_bytes"] = file_bytes
                SESSION_DATA["filename"] = filename

                analyzer = SenaAnalyzer(file_bytes, filename)
                mapping = analyzer.get_detected_columns()
                states = analyzer.get_unique_states()

                initial_filters = [s for s in states if "FORMACI" in s] or None
                try:
                    analysis = analyzer.run_analysis(filter_estados=initial_filters)
                except Exception as e_filter:
                    sys.stderr.write(f"[Info] Filtro inicial '{initial_filters}' no aplicable: {e_filter}. Analizando todos los estados.\n")
                    analysis = analyzer.run_analysis(filter_estados=None)

                analysis = EMAIL_SERVICE.enrich_analysis_with_emails(analysis)
                SESSION_DATA["last_analysis"] = analysis

                hist_info = HISTORY_REPO.save_analysis(
                    analysis,
                    filename,
                    file_bytes=file_bytes,
                    observaciones=observaciones,
                    usuario=_user_label(claims),
                    skip_if_unchanged=False
                )
                rec_info = RECORDS_REPO.store_upload(
                    file_bytes, filename, analyzer.headers, analyzer.raw_data, analyzer.column_mapping,
                    meta=analysis.get("meta"), analisis_id=hist_info.get("analisis_id"), claims=claims, ip=ip
                )
                SECURITY.log_from_claims(claims, "CARGA_ARCHIVO", recurso=filename, detalle={
                    "carga_id": rec_info["carga_id"],
                    "filas": rec_info["total_filas"],
                    "duplicado": rec_info["duplicado"],
                    "sha256": rec_info["hash_sha256"],
                    "analisis_id": hist_info.get("analisis_id")
                }, ip=ip)

                self._send_json(200, {
                    "success": True,
                    "filename": filename,
                    "columns": analyzer.get_available_columns(),
                    "mapping": mapping,
                    "states": states,
                    "analysis": analysis,
                    "history_record": hist_info,
                    "records_info": rec_info
                })
            except Exception as e:
                import traceback
                traceback.print_exc(file=sys.stderr)
                SECURITY.log_from_claims(claims, "CARGA_ARCHIVO", recurso="/api/upload", resultado="ERROR",
                                         detalle={"error": str(e)}, ip=ip)
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/analyze":
            claims = self._require_auth(query, "analisis.ver")
            if not claims:
                return
            try:
                if not SESSION_DATA["file_bytes"]:
                    raise ValueError("No se ha subido ningún archivo previamente.")

                payload = json.loads(post_data.decode("utf-8"))
                analyzer = SenaAnalyzer(
                    SESSION_DATA["file_bytes"],
                    SESSION_DATA["filename"],
                    custom_mapping=payload.get("mapping")
                )
                analysis = EMAIL_SERVICE.enrich_analysis_with_emails(
                    analyzer.run_analysis(
                        filter_estados=payload.get("filter_estados"),
                        umbral_verde=float(payload.get("umbral_verde", 80.0)),
                        umbral_amarillo=float(payload.get("umbral_amarillo", 50.0))
                    )
                )
                SESSION_DATA["last_analysis"] = analysis
                self._send_json(200, {"success": True, "analysis": analysis})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/notificaciones/enviar":
            claims = self._require_auth(query, "notificaciones.enviar")
            if not claims:
                return
            try:
                if not SESSION_DATA["last_analysis"]:
                    raise ValueError("No hay ningún análisis cargado para enviar alertas.")
                payload = json.loads(post_data.decode("utf-8"))
                documentos = payload.get("documentos")
                criterio = payload.get("criterio", "criticos")
                custom_emails = payload.get("custom_emails") or {}
                custom_note = payload.get("observacion", "")

                res = EMAIL_SERVICE.send_alerts_to_critical(
                    SESSION_DATA["last_analysis"],
                    documentos=documentos,
                    criterio=criterio,
                    custom_emails=custom_emails,
                    custom_note=custom_note,
                    usuario=_user_label(claims)
                )
                SECURITY.log_from_claims(
                    claims,
                    "ENVIO_CORREO_CRITICOS",
                    recurso=f"Ficha {SESSION_DATA['last_analysis']['meta']['ficha']}",
                    resultado="OK" if res["total_errores"] == 0 else "PARCIAL",
                    detalle={
                        "criterio": criterio,
                        "total_enviados": res["total_enviados"],
                        "total_errores": res["total_errores"],
                        "modo_envio": res["modo_envio"]
                    },
                    ip=ip
                )
                self._send_json(200, {"success": True, **res})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/notificaciones/contacto":
            claims = self._require_auth(query, "notificaciones.enviar")
            if not claims:
                return
            try:
                payload = json.loads(post_data.decode("utf-8"))
                ficha = SESSION_DATA["last_analysis"]["meta"]["ficha"] if SESSION_DATA["last_analysis"] else ""
                saved = EMAIL_SERVICE.upsert_contact(
                    documento=payload.get("documento", ""),
                    nombre=payload.get("nombre", ""),
                    correo=payload.get("correo", ""),
                    ficha=ficha,
                    usuario=_user_label(claims)
                )
                if SESSION_DATA["last_analysis"]:
                    EMAIL_SERVICE.enrich_analysis_with_emails(SESSION_DATA["last_analysis"])
                self._send_json(200, {"success": True, "contacto": saved})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/notificaciones/smtp":
            claims = self._require_auth(query, "notificaciones.configurar")
            if not claims:
                return
            try:
                payload = json.loads(post_data.decode("utf-8"))
                cfg = EMAIL_SERVICE.save_smtp_config(payload)
                SECURITY.log_from_claims(claims, "CONFIGURAR_SMTP", recurso="configuracion_smtp",
                                         detalle={"modo_envio": cfg["modo_envio"], "smtp_host": cfg["smtp_host"]}, ip=ip)
                self._send_json(200, {"success": True, "smtp": cfg})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/history/save":
            claims = self._require_auth(query, "historico.guardar")
            if not claims:
                return
            try:
                if not SESSION_DATA["last_analysis"]:
                    raise ValueError("No hay ningún análisis activo para guardar en el histórico.")

                payload = json.loads(post_data.decode("utf-8"))
                hist_info = HISTORY_REPO.save_analysis(
                    SESSION_DATA["last_analysis"],
                    SESSION_DATA["filename"] or "Reporte_SENA.xlsx",
                    file_bytes=SESSION_DATA["file_bytes"],
                    observaciones=payload.get("observaciones", "Corte guardado manualmente"),
                    usuario=_user_label(claims),
                    skip_if_unchanged=False
                )
                SECURITY.log_from_claims(claims, "HISTORICO_GUARDAR",
                                         recurso=f"historial_analisis#{hist_info.get('analisis_id')}", ip=ip)
                self._send_json(200, {"success": True, "history_record": hist_info})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/history/delete":
            claims = self._require_auth(query, "historico.eliminar")
            if not claims:
                return
            try:
                payload = json.loads(post_data.decode("utf-8"))
                analisis_id = int(payload.get("id", 0))
                deleted = HISTORY_REPO.delete_snapshot(analisis_id)
                SECURITY.log_from_claims(claims, "HISTORICO_ELIMINAR", recurso=f"historial_analisis#{analisis_id}",
                                         resultado="OK" if deleted else "NO_ENCONTRADO", ip=ip)
                self._send_json(200, {"success": deleted})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/registros/cargas/delete":
            claims = self._require_auth(query, "registros.eliminar")
            if not claims:
                return
            try:
                payload = json.loads(post_data.decode("utf-8"))
                carga_id = int(payload.get("id", 0))
                deleted = RECORDS_REPO.delete_carga(carga_id)
                SECURITY.log_from_claims(claims, "CARGA_ELIMINAR", recurso=f"cargas_archivo#{carga_id}",
                                         resultado="OK" if deleted else "NO_ENCONTRADO", ip=ip)
                self._send_json(200, {"success": deleted})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        self._send_json(404, {"success": False, "error": "Endpoint no encontrado."})


def start_server(port=PORT):
    sample_path = os.path.join(BASE_DIR, "data", "muestra_sena_juicios_evaluativos.xlsx")
    if not os.path.exists(sample_path):
        generate_sample_excel(sample_path)

    server_address = ("", port)
    httpd = HTTPServer(server_address, SenaApiHandler)
    url = f"http://{HOST}:{port}"
    print(f"\n=======================================================")
    print(f"  SENA - SISTEMA DE ANÁLISIS DE AVANCE POR RAPS")
    print(f"=======================================================")
    print(f"  Aplicación iniciada en: {url}")
    print(f"  JWT (HS256) + RBAC + Auditoría + Notificaciones Correo activos.")
    print(f"  Presiona Ctrl+C para detener el servidor.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido por el usuario.")
        httpd.server_close()


if __name__ == "__main__":
    p = PORT
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        p = int(sys.argv[1])
    start_server(p)
