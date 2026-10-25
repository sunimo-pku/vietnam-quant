@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
pushd "%~dp0" || exit /b 1
set "VN_EXIT_CODE=1"
if not exist ".venv\Scripts\python.exe" goto try_py
".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto try_py
set VN_PYTHON=".venv\Scripts\python.exe"
goto run
:try_py
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto try_python
set "VN_PYTHON=py -3"
goto run
:try_python
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto missing
set "VN_PYTHON=python"
goto run
:run
%VN_PYTHON% -X utf8 scripts\bootstrap.py %*
set "VN_EXIT_CODE=%ERRORLEVEL%"
goto finish
:missing
echo 请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/
echo 安装时勾选 Add Python to PATH，然后重新运行。
:finish
if not "%VN_STATUS_NO_PAUSE%"=="1" pause
popd
exit /b %VN_EXIT_CODE%
