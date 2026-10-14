@echo off
setlocal
pushd "%~dp0" || exit /b 1
python -m amg.extractor_gui %*
set "result=%errorlevel%"
popd
if not "%result%"=="0" pause
exit /b %result%
