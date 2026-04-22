@echo off
title AVVIO_BRIDGE_CAD
echo [SISTEMA] Avvio Bridge CAD in corso...
cd /d "D:\Applicazioni\Portale_cad"
set PYTHONUTF8=1
python -u bridge.py
pause
