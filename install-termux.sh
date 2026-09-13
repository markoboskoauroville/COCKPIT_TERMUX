#!/data/data/com.termux/files/usr/bin/bash
# Install the Cockpit in Termux. One command, on a phone where `gh auth login` has been done
# (the repository is private until Marko says it can go public; gh carries the credential, the
# script carries none):
#   curl -fsSL https://raw.githubusercontent.com/markoboskoauroville/COCKPIT_TERMUX/main/install-termux.sh | bash
# On a public repository the same line works with plain git. No venv (Termux's pip installs straight
# into site-packages, modules/termux-app.md §3).
set -euo pipefail
REPO="markoboskoauroville/COCKPIT_TERMUX"
REPO_URL="https://github.com/$REPO.git"
INSTALL_DIR="$HOME/COCKPIT_TERMUX"
if [ -t 1 ]; then AM="\033[38;5;214m"; OK="\033[1;32m"; BAD="\033[1;31m"; OFF="\033[0m"; else AM=""; OK=""; BAD=""; OFF=""; fi

printf "\n  ${AM}Cockpit${OFF}  the phone's health, and the hand on it\n\n"
MISSING=""
printf "  %-14s " "python";   command -v python3 >/dev/null && printf "${OK}ok${OFF} $(python3 --version 2>&1)\n" || { printf "${BAD}MISSING${OFF}  pkg install python\n"; MISSING=1; }
printf "  %-14s " "git";      command -v git >/dev/null && printf "${OK}ok${OFF}\n" || { printf "${BAD}MISSING${OFF}  pkg install git\n"; MISSING=1; }
printf "  %-14s " "flask";    python3 -c "import flask" 2>/dev/null && printf "${OK}ok${OFF}\n" || printf "will install\n"
printf "  %-14s " "waitress"; python3 -c "import waitress" 2>/dev/null && printf "${OK}ok${OFF}\n" || printf "will install\n"
printf "  %-14s " "adb";      command -v adb >/dev/null && printf "${OK}ok${OFF}  (the bridge)\n" || printf "absent: pkg install android-tools, for the bridge (kill, every process, thermal)\n"
printf "  %-14s " "termux-api"; command -v termux-battery-status >/dev/null && printf "${OK}ok${OFF}\n" || printf "absent: pkg install termux-api + the Termux:API app, for battery and wifi\n"
if [ -n "$MISSING" ]; then pkg install -y python git; fi
python3 -c "import flask, waitress" 2>/dev/null || pip install --quiet flask waitress

if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull -q --ff-only
elif command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  gh repo clone "$REPO" "$INSTALL_DIR" -- -q
else
  git clone -q "$REPO_URL" "$INSTALL_DIR" || { printf "  ${BAD}the repository is private${OFF}: run  gh auth login  first, then this again\n"; exit 1; }
fi
chmod +x "$INSTALL_DIR/cockpit"
bash "$INSTALL_DIR/cockpit" install
mkdir -p "$HOME/.cockpit" && chmod 700 "$HOME/.cockpit"
printf "\n  done. ${AM}cockpit${OFF} starts it. For the bridge: Developer options → Wireless debugging → pair, then the page's bridge box.\n\n"
