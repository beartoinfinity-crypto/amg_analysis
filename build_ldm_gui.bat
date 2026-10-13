@echo off
setlocal
pushd "%~dp0" || exit /b 1

if not exist "ldm_gui_launcher.py" (
    echo ERROR: ldm_gui_launcher.py not found.
    pause
    exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name AMGLDMExtractor ^
    ldm_gui_launcher.py

set "result=%errorlevel%"
popd
if not "%result%"=="0" pause
exit /b %result%
