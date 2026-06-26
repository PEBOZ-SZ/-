Set-Location -LiteralPath "D:\完整版自动报价\自报项目"
python -m uvicorn api_server:app --host 127.0.0.1 --port 8010 *> "logs\api_8010_ps.log"
