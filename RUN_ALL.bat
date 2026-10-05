@echo off
REM ===========================================================================
REM  RUN_ALL.bat — Master runner for Emergency Route Intelligence Warehouse
REM  Run from: C:\Users\harsh\Downloads\data\
REM ===========================================================================

echo.
echo ===================================================================
echo   EMERGENCY ROUTE INTELLIGENCE WAREHOUSE — COMPLETE SETUP
echo ===================================================================
echo.

REM ── 1. Install dependencies ──────────────────────────────────────────────
echo [STEP 1/7] Installing Python dependencies...
pip install -r requirements.txt --quiet
if %ERRORLEVEL% neq 0 (echo ERROR: pip install failed & pause & exit /b 1)
echo   Done.

REM ── 2. Audit current DB state ────────────────────────────────────────────
echo.
echo [STEP 2/7] Auditing database row counts...
python audit.py
if %ERRORLEVEL% neq 0 (echo ERROR: Audit failed. Check .env and DB connection. & pause & exit /b 1)

REM ── 3. Load warehouse (idempotent — skips existing data) ─────────────────
echo.
echo [STEP 3/7] Loading warehouse dimensions and facts...
echo   (Safe: uses ON CONFLICT DO NOTHING. Existing rows preserved.)
python run_warehouse.py
if %ERRORLEVEL% neq 0 (
    echo WARNING: Warehouse load had errors. Check output above.
    echo   Some tables may have been skipped due to data type issues.
)

REM ── 4. Run ML suite ──────────────────────────────────────────────────────
echo.
echo [STEP 4/7] Running ML analysis suite (may take 5-15 min)...
python -m ml.run_all_ml
if %ERRORLEVEL% neq 0 (echo WARNING: Some ML modules failed. Check output.)

REM ── 5. Run demo simulation ───────────────────────────────────────────────
echo.
echo [STEP 5/7] Running demo simulation (Pune, Hour=9, Rain)...
python simulator.py
if %ERRORLEVEL% neq 0 (echo WARNING: Simulator failed. Run warehouse load first.)

REM ── 6. Run hospital analysis ─────────────────────────────────────────────
echo.
echo [STEP 6/7] Running hospital analysis...
python hospital_analysis.py
if %ERRORLEVEL% neq 0 (echo WARNING: Hospital analysis had errors.)

REM ── 7. Run full test suite ───────────────────────────────────────────────
echo.
echo [STEP 7/7] Running full test suite...
python tests\test_all.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo SOME TESTS FAILED — Check test_results.txt for details.
    echo The app will still run. Some warehouse tables may be empty.
)

REM ── Start dashboard ──────────────────────────────────────────────────────
echo.
echo ===================================================================
echo   SETUP COMPLETE — Starting Dashboard
echo   Open: http://localhost:5000
echo   Press Ctrl+C to stop
echo ===================================================================
echo.
python app.py

pause
