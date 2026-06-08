#!/usr/bin/env bash
# Installation sur un poste Ubuntu/Debian + entree dans le menu d'applications.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

echo ">> Dependances systeme (tkinter, UNO pour Calc, pipx)..."
sudo apt update
sudo apt install -y python3-tk python3-uno pipx
pipx ensurepath

echo ">> Installation de l'app..."
pipx install --system-site-packages "$HERE"   # --system-site-packages : pour voir python3-uno

echo ">> Integration au menu d'applications..."
BINDIR="$HOME/.local/bin"
APPDIR="$HOME/.local/share/applications"
ICONDIR="$HOME/.local/share/icons"
mkdir -p "$BINDIR" "$APPDIR" "$ICONDIR"

install -m755 "$HERE/telemetre-calc.sh" "$BINDIR/telemetre-calc"

ICON="$ICONDIR/telemetre.svg"
cp "$HERE/telemetre.svg" "$ICON"
[ -f "$HERE/telemetre.png" ] && cp "$HERE/telemetre.png" "$ICONDIR/telemetre.png" && ICON="$ICONDIR/telemetre.png"

cat > "$APPDIR/telemetre.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Télémètre Bosch
Comment=Mesures Bosch vers LibreOffice Calc
Exec=$BINDIR/telemetre-calc
Icon=$ICON
Terminal=false
Categories=Utility;Science;
Keywords=telemetre;laser;bosch;mesure;calc;
StartupNotify=true
EOF

update-desktop-database "$APPDIR" 2>/dev/null || true
echo
echo "OK. 'Télémètre Bosch' est maintenant dans le menu des applications."
echo "(Au besoin, lancement direct : telemetre-calc)"
