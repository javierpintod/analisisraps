"""
Servidor HTTP y API REST en Python puro para la aplicación SENA Análisis RAPs.
Incluye autenticación JWT (RFC 7519 HS256), persistencia histórica en SQLite
y control de migraciones de esquema con Liquibase.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import mimetypes
import os
import sys
from typing import Any, Dict, Optional
import urllib.parse
import webbrowser

from sena_processor import SenaAnalyzer, SenaReader, auto_detect_columns
from export_utils import create_excel_report
from sample_data import generate_sample_excel
from database import SenaHistoryRepository
from auth import AuthService

PORT = 8501
HOST = "localhost"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Inicializar Repositorio Histórico + Migraciones Liquibase + Servicio JWT
HISTORY_REPO = SenaHistoryRepository()
AUTH_SERVICE = AuthService()

# Almacén en memoria de la sesión actual
SESSION_DATA = {
    "file_bytes": None,
    "filename": None,
    "last_analysis": None
}


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
        analysis = analyzer.run_analysis(filter_estados=["EN FORMACION"])
        SESSION_DATA["last_analysis"] = analysis
        HISTORY_REPO.save_analysis(
            analysis,
            target_name,
            file_bytes=content,
            observaciones="Corte inicial automático (Reporte SofiaPlus)",
            skip_if_unchanged=True
        )
        print(f"  -> Archivo real SENA '{target_name}' precargado y sincronizado en BD histórica.")
    except Exception as e:
        print(f"  [Aviso] No se pudo precargar la muestra: {e}")


# Ejecutar precarga al importar/iniciar
preload_default_sample()


class SenaApiHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def _send_json(self, status_code: int, data: dict):
        response = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response)

    def _send_file(self, content_type: str, data: bytes, filename: str = None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _require_auth(self, query_params: Optional[Dict[str, list]] = None) -> Optional[Dict[str, Any]]:
        """
        Valida el token JWT en el header 'Authorization: Bearer <token>' o en '?token=<jwt>'.
        Si falla, responde con HTTP 401 Unauthorized y retorna None.
        """
        auth_header = self.headers.get("Authorization")
        query_token = None
        if query_params and "token" in query_params and query_params["token"]:
            query_token = query_params["token"][0]

        try:
            token = AUTH_SERVICE.extract_token(auth_header, query_token)
            claims = AUTH_SERVICE.verify_token(token)
            return claims
        except Exception as e:
            self._send_json(401, {
                "success": False,
                "authenticated": False,
                "error": str(e)
            })
            return None

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

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
                "claims": claims
            })
            return

        elif path == "/api/history":
            claims = self._require_auth(query)
            if not claims:
                return
            ficha_filter = query.get("ficha", [None])[0]
            history_data = HISTORY_REPO.list_history(ficha=ficha_filter)
            self._send_json(200, {"success": True, **history_data})
            return

        elif path.startswith("/api/history/"):
            claims = self._require_auth(query)
            if not claims:
                return
            id_part = path.split("/api/history/")[-1].strip("/")
            if id_part.isdigit():
                snap = HISTORY_REPO.get_snapshot(int(id_part))
                if not snap:
                    self._send_json(404, {"success": False, "error": "Corte histórico no encontrado."})
                    return
                SESSION_DATA["last_analysis"] = snap["analysis"]
                SESSION_DATA["filename"] = snap["snapshot"]["archivo_origen"]
                self._send_json(200, {"success": True, **snap})
                return

        elif path == "/api/sample":
            claims = self._require_auth(query)
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
            analysis = analyzer.run_analysis(filter_estados=initial_filters)
            SESSION_DATA["last_analysis"] = analysis

            user_label = f"{claims.get('nombre', 'Instructor')} ({claims.get('username', 'sena')})"
            hist_info = HISTORY_REPO.save_analysis(
                analysis,
                target_name,
                file_bytes=content,
                observaciones="Carga de reporte SofiaPlus",
                usuario=user_label,
                skip_if_unchanged=True
            )

            self._send_json(200, {
                "success": True,
                "filename": target_name,
                "columns": analyzer.get_available_columns(),
                "mapping": analyzer.get_detected_columns(),
                "states": states,
                "analysis": analysis,
                "history_record": hist_info
            })
            return

        elif path == "/api/export":
            claims = self._require_auth(query)
            if not claims:
                return
            if not SESSION_DATA["last_analysis"]:
                self._send_json(400, {"error": "No hay análisis previo para exportar."})
                return
            excel_bytes = create_excel_report(SESSION_DATA["last_analysis"])
            ficha = SESSION_DATA["last_analysis"]["meta"]["ficha"]
            clean_ficha = "".join(c for c in ficha if c.isalnum() or c in "-_")
            export_name = f"Informe_Avance_RAPs_Ficha_{clean_ficha}.xlsx"
            self._send_file("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", excel_bytes, export_name)
            return

        # Servir archivos estáticos del frontend
        if path == "/":
            path = "/index.html"

        file_path = os.path.join(BASE_DIR, "static", path.lstrip("/"))
        if os.path.isfile(file_path):
            mime_type, _ = mimetypes.guess_type(file_path)
            mime_type = mime_type or "application/octet-stream"
            with open(file_path, "rb") as f:
                data = f.read()
            self._send_file(mime_type, data)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"

        if path == "/api/auth/login":
            try:
                payload = json.loads(post_data.decode("utf-8"))
                username = payload.get("username", "")
                password = payload.get("password", "")
                client_ip = self.client_address[0] if self.client_address else "127.0.0.1"

                auth_result = AUTH_SERVICE.login(username, password, ip=client_ip)
                self._send_json(200, {"success": True, **auth_result})
            except Exception as e:
                self._send_json(401, {"success": False, "error": str(e)})
            return

        elif path == "/api/auth/logout":
            auth_header = self.headers.get("Authorization")
            try:
                token = AUTH_SERVICE.extract_token(auth_header)
                revoked = AUTH_SERVICE.logout(token)
                self._send_json(200, {"success": True, "revoked": revoked})
            except Exception as e:
                self._send_json(200, {"success": True, "revoked": False, "info": str(e)})
            return

        elif path == "/api/upload":
            claims = self._require_auth(query)
            if not claims:
                return
            try:
                payload = json.loads(post_data.decode("utf-8"))
                import base64
                file_bytes = base64.b64decode(payload["content_base64"])
                filename = payload["filename"]
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

                SESSION_DATA["last_analysis"] = analysis

                user_label = f"{claims.get('nombre', 'Instructor')} ({claims.get('username', 'sena')})"
                hist_info = HISTORY_REPO.save_analysis(
                    analysis,
                    filename,
                    file_bytes=file_bytes,
                    observaciones=observaciones,
                    usuario=user_label,
                    skip_if_unchanged=False
                )

                self._send_json(200, {
                    "success": True,
                    "filename": filename,
                    "columns": analyzer.get_available_columns(),
                    "mapping": mapping,
                    "states": states,
                    "analysis": analysis,
                    "history_record": hist_info
                })
            except Exception as e:
                import traceback
                traceback.print_exc(file=sys.stderr)
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/analyze":
            claims = self._require_auth(query)
            if not claims:
                return
            try:
                if not SESSION_DATA["file_bytes"]:
                    raise ValueError("No se ha subido ningún archivo previamente.")

                payload = json.loads(post_data.decode("utf-8"))
                custom_mapping = payload.get("mapping")
                filter_estados = payload.get("filter_estados")
                umbral_verde = float(payload.get("umbral_verde", 80.0))
                umbral_amarillo = float(payload.get("umbral_amarillo", 50.0))

                analyzer = SenaAnalyzer(
                    SESSION_DATA["file_bytes"],
                    SESSION_DATA["filename"],
                    custom_mapping=custom_mapping
                )
                analysis = analyzer.run_analysis(
                    filter_estados=filter_estados,
                    umbral_verde=umbral_verde,
                    umbral_amarillo=umbral_amarillo
                )
                SESSION_DATA["last_analysis"] = analysis

                self._send_json(200, {
                    "success": True,
                    "analysis": analysis
                })
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/history/save":
            claims = self._require_auth(query)
            if not claims:
                return
            try:
                if not SESSION_DATA["last_analysis"]:
                    raise ValueError("No hay ningún análisis activo para guardar en el histórico.")

                payload = json.loads(post_data.decode("utf-8"))
                observaciones = payload.get("observaciones", "Corte guardado manualmente")
                user_label = f"{claims.get('nombre', 'Instructor')} ({claims.get('username', 'sena')})"

                hist_info = HISTORY_REPO.save_analysis(
                    SESSION_DATA["last_analysis"],
                    SESSION_DATA["filename"] or "Reporte_SENA.xlsx",
                    file_bytes=SESSION_DATA["file_bytes"],
                    observaciones=observaciones,
                    usuario=user_label,
                    skip_if_unchanged=False
                )
                self._send_json(200, {"success": True, "history_record": hist_info})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/history/delete":
            claims = self._require_auth(query)
            if not claims:
                return
            try:
                payload = json.loads(post_data.decode("utf-8"))
                analisis_id = int(payload.get("id", 0))
                deleted = HISTORY_REPO.delete_snapshot(analisis_id)
                self._send_json(200, {"success": deleted})
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        self.send_response(404)
        self.end_headers()


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
    print(f"  Autenticación JWT (HS256) y Liquibase activos.")
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
