@echo off
REM ---------------------------------------------------------------------------
REM  motivebatch - convert Motive .tak files to .csv
REM
REM  Drag one or more .tak files onto this file in Explorer, or run it from a
REM  command prompt:
REM
REM      convert.bat "C:\path\to\Take.tak"
REM      convert.bat "C:\Program Files\OptiTrack\Motive\assemblies\x64\NMotive.dll" Take.tak
REM
REM  Converted .csv files are written to the Desktop.
REM ---------------------------------------------------------------------------
setlocal EnableExtensions

set "REPO=%~dp0"
if "%REPO:~-1%"=="\" set "REPO=%REPO:~0,-1%"
set "VENV=%REPO%\.venv"
REM Explorer drops run with an unpredictable working directory.
set "PYTHONPATH=%REPO%;%PYTHONPATH%"

set "PYEXE="
if exist "%VENV%\Scripts\python.exe" (
    set "PYEXE=%VENV%\Scripts\python.exe"
    goto :have_python
)
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=py -3"
    goto :have_python
)
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=python"
    goto :have_python
)

echo.
echo   Python 3 was not found.
echo.
echo   Install it from https://www.python.org/downloads/ and tick
echo   "Add python.exe to PATH" during setup, then run this again.
echo.
pause
exit /b 1

:have_python
if "%~1"=="" goto :usage

REM Name what we were handed before anything else is printed, so a drag-and-drop
REM window always opens by saying which take it is working on.
echo.
for %%A in (%*) do (
    if /i "%%~xA"==".tak" echo   Take: %%~nxA
)

REM Nothing to install unless Motive is actually on this machine: the pure
REM Python reader handles CSV on its own.
if exist "%VENV%\Scripts\python.exe" goto :run
set "FOUNDDLL="
for /f "usebackq delims=" %%D in (`%PYEXE% -m motivebatch --find-dll %* 2^>nul`) do set "FOUNDDLL=%%D"
if not defined FOUNDDLL goto :run

echo   Motive found: %FOUNDDLL%
echo   Preparing Motive's own exporter for exact-fidelity output.
echo   This happens once and needs an internet connection.
echo.
%PYEXE% -m venv "%VENV%"
if errorlevel 1 goto :bootstrap_failed
"%VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --quiet pythonnet
if errorlevel 1 goto :bootstrap_failed
set "PYEXE=%VENV%\Scripts\python.exe"
echo   Done.
echo.
goto :run

:bootstrap_failed
echo.
echo   Could not set up Motive's exporter; continuing with the built-in reader.
echo   ^(Re-run after fixing your connection to enable exact-fidelity output.^)
echo.
if exist "%VENV%" rmdir /s /q "%VENV%" >nul 2>&1

:run
%PYEXE% -m motivebatch %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo   Done.
) else (
    echo   Finished with errors ^(exit code %RC%^).
)
pause
exit /b %RC%

:usage
echo.
echo   motivebatch - Motive .tak to .csv
echo.
echo   Drag one or more .tak files onto this file, or run:
echo.
echo       convert.bat "C:\path\to\Take.tak"
echo       convert.bat path\to\NMotive.dll "C:\path\to\Take.tak"
echo.
echo   Options: --markers  --units mm  --rotation XYZ  --beside-input
echo            --info  --list-backends
echo.
pause
exit /b 2
