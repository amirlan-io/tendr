#!/bin/bash
export BROWSER_USE_API_KEY="bu_NwlRCdoQFXw17CcBomkoI707IpBfYhj_07CMlhFYcyY"
cd /home/angel/Рабочий\ стол/project\ all/tendr/backend
exec /home/angel/Рабочий\ стол/project\ all/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
