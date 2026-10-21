@echo off
setlocal
pushd "%~dp0" || exit /b 1

if not exist "msg_analysis_launcher.py" (
    echo ERROR: msg_analysis_launcher.py not found.
    pause
    exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name AMGMsgAnalysis ^
    msg_analysis_launcher.py

set "result=%errorlevel%"
popd
if not "%result%"=="0" pause
exit /b %result%
