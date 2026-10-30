@echo off
chcp 65001 > nul
echo ==============================================================
echo      SENA - ANALIZADOR DE AVANCE POR RAPS Y JUICIOS
echo ==============================================================
echo Iniciando servidor local en http://localhost:8501 ...
echo.

if exist .venv\Scripts\python.exe (
    start http://localhost:8501
    .venv\Scripts\python.exe server.py
) else (
    start http://localhost:8501
    python server.py
)

pause
