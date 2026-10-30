"""
Servidor HTTP y API REST en Python puro para la aplicación SENA Análisis RAPs.
Soporta análisis simultáneo de múltiples fichas de formación, consolidación y ranking.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import mimetypes
import os
import sys
import urllib.parse
import traceback

from sena_processor import SenaAnalyzer, SenaReader, MultiFichaAnalyzer, auto_detect_columns
from export_utils import create_excel_report
from sample_data import generate_sample_excel

PORT = 8501
HOST = "localhost"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Almacén en memoria de la sesión actual
SESSION_DATA = {
    "files": [],       # Lista de tuplas (filename, bytes)
    "last_analysis": None
}


def preload_default_sample():
    """Precarga las fichas disponibles para habilitar análisis multi-ficha de inmediato."""
    try:
        real_path = os.path.join(BASE_DIR, "data", "Reporte_de_Juicios_Evaluativos.xls")
        sample_path = os.path.join(BASE_DIR, "data", "muestra_sena_juicios_evaluativos.xlsx")
        
        files_to_load = []
        if os.path.exists(real_path):
            with open(real_path, "rb") as f:
                files_to_load.append(("Reporte_de_Juicios_Evaluativos.xls", f.read()))
        if os.path.exists(sample_path):
            with open(sample_path, "rb") as f:
                files_to_load.append(("muestra_sena_juicios_evaluativos.xlsx", f.read()))
                
        if not files_to_load:
            generate_sample_excel(sample_path)
            with open(sample_path, "rb") as f:
                files_to_load.append(("muestra_sena_juicios_evaluativos.xlsx", f.read()))

        SESSION_DATA["files"] = files_to_load
        
        mf_analyzer = MultiFichaAnalyzer(files_to_load)
        analysis = mf_analyzer.run_multi_analysis(filter_estados=["EN FORMACION", "EN FORMACIÓN"])
        SESSION_DATA["last_analysis"] = analysis
        print(f"  -> {len(files_to_load)} fichas precargadas exitosamente en memoria.")
    except Exception as e:
        print(f"  [Aviso] No se pudo precargar la muestra: {e}")

# Ejecutar precarga al iniciar
preload_default_sample()


class SenaApiHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        # Silenciar logs en consola para mayor claridad
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

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._send_json(200, {"status": "ok", "app": "analisisraps-sena", "files_loaded": len(SESSION_DATA["files"])})
            return

        elif path == "/api/sample":
            preload_default_sample()
            mf_analyzer = MultiFichaAnalyzer(SESSION_DATA["files"])
            states = mf_analyzer.get_unique_states()
            self._send_json(200, {
                "success": True,
                "is_multi_ficha": SESSION_DATA["last_analysis"]["is_multi_ficha"],
                "total_fichas": SESSION_DATA["last_analysis"]["total_fichas"],
                "fichas_selector": SESSION_DATA["last_analysis"]["fichas_selector"],
                "states": states,
                "analysis": SESSION_DATA["last_analysis"]
            })
            return

        elif path == "/api/export":
            if not SESSION_DATA["last_analysis"]:
                self._send_json(400, {"error": "No hay análisis previo para exportar."})
                return
            
            excel_bytes = create_excel_report(SESSION_DATA["last_analysis"])
            export_name = "Informe_Avance_RAPs_SENA_Consolidado.xlsx"
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

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        if path == "/api/upload":
            try:
                import base64
                payload = json.loads(post_data.decode("utf-8"))
                
                # Soporte para múltiples archivos o archivo individual
                files_payload = payload.get("files")
                uploaded_files = []

                if files_payload and isinstance(files_payload, list):
                    for item in files_payload:
                        f_bytes = base64.b64decode(item["content_base64"])
                        uploaded_files.append((item["filename"], f_bytes))
                elif "content_base64" in payload:
                    f_bytes = base64.b64decode(payload["content_base64"])
                    uploaded_files.append((payload["filename"], f_bytes))
                else:
                    raise ValueError("No se encontraron archivos en la solicitud.")

                # Si el usuario desea anexar a los existentes o reemplazar
                append_mode = payload.get("append", False)
                if append_mode:
                    SESSION_DATA["files"].extend(uploaded_files)
                else:
                    SESSION_DATA["files"] = uploaded_files

                mf_analyzer = MultiFichaAnalyzer(SESSION_DATA["files"])
                states = mf_analyzer.get_unique_states()

                # Filtro inicial prioritario para 'EN FORMACIÓN'
                initial_filters = [s for s in states if "FORMACI" in s] or None
                try:
                    analysis = mf_analyzer.run_multi_analysis(filter_estados=initial_filters)
                except Exception as e_filter:
                    sys.stderr.write(f"[Info] Filtro inicial '{initial_filters}' no aplicable: {e_filter}. Analizando todos los estados.\n")
                    analysis = mf_analyzer.run_multi_analysis(filter_estados=None)

                SESSION_DATA["last_analysis"] = analysis

                self._send_json(200, {
                    "success": True,
                    "is_multi_ficha": analysis["is_multi_ficha"],
                    "total_fichas": analysis["total_fichas"],
                    "fichas_selector": analysis["fichas_selector"],
                    "states": states,
                    "analysis": analysis
                })
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                self._send_json(400, {"success": False, "error": str(e)})
            return

        elif path == "/api/analyze":
            try:
                if not SESSION_DATA["files"]:
                    raise ValueError("No se han cargado fichas previamente.")

                payload = json.loads(post_data.decode("utf-8"))
                filter_estados = payload.get("filter_estados")
                umbral_verde = float(payload.get("umbral_verde", 80.0))
                umbral_amarillo = float(payload.get("umbral_amarillo", 50.0))

                mf_analyzer = MultiFichaAnalyzer(SESSION_DATA["files"])
                analysis = mf_analyzer.run_multi_analysis(
                    filter_estados=filter_estados,
                    umbral_verde=umbral_verde,
                    umbral_amarillo=umbral_amarillo
                )
                SESSION_DATA["last_analysis"] = analysis

                self._send_json(200, {
                    "success": True,
                    "is_multi_ficha": analysis["is_multi_ficha"],
                    "total_fichas": analysis["total_fichas"],
                    "fichas_selector": analysis["fichas_selector"],
                    "analysis": analysis
                })
            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
            return

        self.send_response(404)
        self.end_headers()


def start_server(port=PORT):
    server_address = ("", port)
    httpd = HTTPServer(server_address, SenaApiHandler)
    url = f"http://{HOST}:{port}"
    print(f"\n=======================================================")
    print(f"  SENA - SISTEMA MULTI-FICHA DE ANÁLISIS DE RAPS")
    print(f"=======================================================")
    print(f"  Aplicación iniciada en: {url}")
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
