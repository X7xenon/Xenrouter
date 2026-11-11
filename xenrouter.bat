@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONPATH=X:\Millionaire\Xenrouter;%PYTHONPATH%
"X:\Softwares\Python\python.exe" -m xenrouter.cli %*
