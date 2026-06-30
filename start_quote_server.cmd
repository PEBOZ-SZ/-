@echo off
cd /d "%~dp0"
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" server.py --force-unlock >> logs\server_live.out.log 2>> logs\server_live.err.log
