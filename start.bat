@echo off
cd /d "%~dp0"
python -m hydroflow init
if errorlevel 1 goto failure
python -m hydroflow serve
goto :eof
:failure
echo Не удалось запустить приложение. Проверьте Python и сообщения выше.
pause
