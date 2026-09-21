@echo off
setlocal
pushd "%~dp0" || exit /b 1
python -m amg.encrypt_config %*
set "result=%errorlevel%"
popd
if not "%result%"=="0" pause
exit /b %result%
