#!/usr/bin/env bash
# Lance LibreOffice Calc avec le socket UNO (si pas deja la), puis l'app.
export PATH="$HOME/.local/bin:$PATH"
if ! pgrep -f "accept=socket.*2002" >/dev/null 2>&1; then
  soffice --calc --accept="socket,host=localhost,port=2002;urp;" &
  sleep 4
fi
exec telemetre
