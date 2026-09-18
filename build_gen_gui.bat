@echo off
setlocal
pushd "%~dp0" || exit /b 1
if not exist "amg\message_templates.json" (
    echo Missing amg\message_templates.json. Prepare the template library before building.
    popd
    exit /b 1
)
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AMGMessageGenerator --add-data "amg\message_templates.json;amg" "gen_gui_launcher.py"
set "result=%errorlevel%"
popd
exit /b %result%
