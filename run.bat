@echo off
echo ===================================================
echo   CareerSync - The Anti-Exhaustion Job Engine
echo ===================================================
echo.
echo Starting FastAPI Web Server at http://localhost:8000 ...
echo.
python -m uvicorn main:app --reload --port 8000
pause
