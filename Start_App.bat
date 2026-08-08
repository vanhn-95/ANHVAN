@echo off
REM ==========================================================
REM  SubAI Studio - nhap doi vao file nay la chay
REM  Tu tao venv, tu cai thu vien, tu bat server dich thuat.
REM ==========================================================

cd /d "%~dp0"
title SubAI Studio

echo ==========================================================
echo    SubAI Studio
echo ==========================================================
echo.

REM ---------- Kiem tra dung thu muc ----------
if exist "run_desktop.py" goto :find_python
echo [LOI] Khong thay file run_desktop.py trong thu muc nay:
echo    %CD%
echo.
echo File .bat nay phai nam CUNG THU MUC voi run_desktop.py.
echo Neu ban giai nen bi long 2 tang (SubAIStudio\SubAIStudio)
echo thi hay vao tang trong roi chay lai.
echo.
pause
exit /b 1

REM ---------- Tim Python 3.11 ----------
:find_python
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
echo Cai xong phai MO LAI file .bat nay.
echo.
pause
exit /b 1

:have_python
echo Python: %PYEXE%
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
if not errorlevel 1 goto :check_server_deps

echo [2/3] Dang cai thu vien giao dien...
echo       Lan dau mat vai phut, tai khoang 150MB. Vui long doi.
echo.
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r requirements-desktop.txt
if errorlevel 1 goto :fail
echo       Xong.
echo.

:check_server_deps
REM ---------- Cai fastapi/uvicorn de bat server dich thuat ngam ----------
"%VPY%" -c "import fastapi, uvicorn" >nul 2>&1
if not errorlevel 1 goto :run_app

echo [2b/3] Dang cai thu vien server dich thuat...
"%VPY%" -m pip install -r requirements-server.txt
if errorlevel 1 goto :fail
echo       Xong.
echo.

:run_app
echo [3/3] Dang mo SubAI Studio...
echo       Server dich thuat se tu chay ngam - khong can mo them CMD nao.
echo       Dong app la server tu tat.
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
pause
exit /b 1
