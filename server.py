"""
Servidor HTTP y API REST en Python puro para la aplicación SENA Análisis RAPs.
No requiere dependencias externas binarias y funciona en cualquier entorno Windows.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import mimetypes
import os
import sys
import urllib.parse
import webbrowser

from sena_processor import SenaAnalyzer, SenaReader, auto_detect_columns
from export_utils import create_excel_report
from sample_data import generate_sample_excel

PORT = 8501
HOST = "localhost"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Almacén en memoria de la sesión actual
SESSION_DATA = {
    "file_bytes": None,
    "filename": None,
    "last_analysis": None
}

def preload_default_sample():
    """Precarga el archivo de prueba para que la aplicación inicie con datos listos."""
    try:
        sample_path = os.path.join(BASE_DIR, "data", "muestra_sena_juicios_evaluativos.xlsx")
        if not os.path.exists(sample_path):
            generate_sample_excel(sample_path)
        with open(sample_path, "rb") as f:
            content = f.read()
        SESSION_DATA["file_bytes"] = content
        SESSION_DATA["filename"] = "muestra_sena_juicios_evaluativos.xlsx"
        analyzer = SenaAnalyzer(content, SESSION_DATA["filename"])
        SESSION_DATA["last_analysis"] = analyzer.run_analysis(filter_estados=["EN FORMACIÓN"])
        print("  -> Archivo de prueba SENA precargado exitosamente en memoria.")
    except Exception as e:
        print(f"  [Aviso] No se pudo precargar la muestra: {e}")

# Ejecutar precarga al importar/iniciar
preload_default_sample()



class SenaApiHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        # Silenciar logs ruidosos en consola
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
            self._send_json(200, {"status": "ok", "app": "analisisraps-sena"})
            return

        elif path == "/api/sample":
            # Cargar archivo de muestra generado
            sample_path = os.path.join(BASE_DIR, "data", "muestra_sena_juicios_evaluativos.xlsx")
            if not os.path.exists(sample_path):
                generate_sample_excel(sample_path)
            
            with open(sample_path, "rb") as f:
                content = f.read()

            SESSION_DATA["file_bytes"] = content
            SESSION_DATA["filename"] = "muestra_sena_juicios_evaluativos.xlsx"

            analyzer = SenaAnalyzer(content, SESSION_DATA["filename"])
            analysis = analyzer.run_analysis(filter_estados=["EN FORMACIÓN"])
            SESSION_DATA["last_analysis"] = analysis

            self._send_json(200, {
                "success": True,
                "filename": SESSION_DATA["filename"],
                "columns": analyzer.get_available_columns(),
                "mapping": analyzer.get_detected_columns(),
                "states": analyzer.get_unique_states(),
                "analysis": analysis
            })
            return

        elif path == "/api/export":
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

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        if path == "/api/upload":
            try:
                # El cliente envía JSON con: { filename: str, content_base64: str }
                payload = json.loads(post_data.decode("utf-8"))
                import base64
                file_bytes = base64.b64decode(payload["content_base64"])
                filename = payload["filename"]

                SESSION_DATA["file_bytes"] = file_bytes
                SESSION_DATA["filename"] = filename

                analyzer = SenaAnalyzer(file_bytes, filename)
                mapping = analyzer.get_detected_columns()
                states = analyzer.get_unique_states()

                # Ejecutar análisis preliminar con 'EN FORMACIÓN' si existe, o sin filtro si no hay
                initial_filters = [s for s in states if "FORMACI" in s] or None
                try:
                    analysis = analyzer.run_analysis(filter_estados=initial_filters)
                except Exception as e_filter:
                    sys.stderr.write(f"[Info] Filtro inicial '{initial_filters}' no aplicable: {e_filter}. Analizando todos los estados.\n")
                    analysis = analyzer.run_analysis(filter_estados=None)

                SESSION_DATA["last_analysis"] = analysis

                self._send_json(200, {
                    "success": True,
                    "filename": filename,
                    "columns": analyzer.get_available_columns(),
                    "mapping": mapping,
                    "states": states,
                    "analysis": analysis
                })
            except Exception as e:
                import traceback
                traceback.print_exc(file=sys.stderr)
                self._send_json(400, {"success": False, "error": str(e)})
            return


        elif path == "/api/analyze":
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

        self.send_response(404)
        self.end_headers()


def start_server(port=PORT):
    # Asegurar que exista el archivo de prueba
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
