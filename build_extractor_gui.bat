@echo off
setlocal
pushd "%~dp0" || exit /b 1

if not exist "extractor_gui_launcher.py" (
    echo ERROR: extractor_gui_launcher.py not found.
    pause
    exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name AMGMessageExtractor ^
    extractor_gui_launcher.py

set "result=%errorlevel%"
popd
if not "%result%"=="0" pause
exit /b %result%
