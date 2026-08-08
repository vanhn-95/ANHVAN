@echo off
REM Khoi dong SubAI Studio tren Windows: tu tao venv, tu cai thu vien, tu mo app.
REM Chi can nhap doi vao file nay.

cd /d "%~dp0"
title SubAI Studio

echo ==========================================================
echo    SubAI Studio - Khoi dong
echo ==========================================================
echo.

REM ---------- Tim Python 3.11 ----------
set "PYEXE="

py -3.11 --version >nul 2>&1
if not errorlevel 1 set "PYEXE=py -3.11"
if defined PYEXE goto :have_python

python --version >nul 2>&1
if not errorlevel 1 set "PYEXE=python"
if defined PYEXE goto :have_python

echo [LOI] Khong tim thay Python tren may nay.
echo.
echo Tai Python 3.11 tai:
echo    https://www.python.org/downloads/release/python-3119/
echo.
echo QUAN TRONG: khi cai nho tick o "Add python.exe to PATH".
echo Sau khi cai xong phai MO LAI cua so nay.
echo.
pause
exit /b 1

:have_python
echo Dung Python: %PYEXE%
%PYEXE% --version
echo.

REM ---------- Tao venv neu chua co ----------
if exist "venv\Scripts\python.exe" goto :have_venv

echo [1/3] Dang tao moi truong ao (venv)...
%PYEXE% -m venv venv
if errorlevel 1 goto :fail
echo       Xong.
echo.

:have_venv
set "VPY=venv\Scripts\python.exe"

REM ---------- Cai thu vien neu thieu ----------
"%VPY%" -c "import PySide6" >nul 2>&1
if not errorlevel 1 goto :have_deps

echo [2/3] Dang cai thu vien giao dien...
echo       Lan dau se mat vai phut, tai khoang 150MB. Vui long doi.
echo.
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements-desktop.txt
if errorlevel 1 goto :fail
echo       Xong.
echo.

:have_deps
echo [3/3] Dang mo SubAI Studio...
echo.
"%VPY%" run_desktop.py
if errorlevel 1 goto :fail

exit /b 0

:fail
echo.
echo ==========================================================
echo    CO LOI XAY RA
echo ==========================================================
echo.
echo Chay lenh sau de biet chinh xac thieu gi:
echo.
echo    venv\Scripts\python.exe check_setup.py
echo.
echo Neu venv chua tao duoc thi chay:
echo.
echo    %PYEXE% check_setup.py
echo.
pause
exit /b 1
