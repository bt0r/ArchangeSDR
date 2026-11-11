#!/bin/bash
# Installs ArchangeSDR for the current user: the program, its translations and default ranges in
# ~/.local/share/archangesdr/app, the command ~/.local/bin/archangesdr, and ~/.local/bin/sdrscanner (its
# former name, which the archSDR and uBonsole menus call). Run as your user:
#   ./install.sh               install or update
#   ./install.sh --uninstall   remove the program (settings, ranges and history stay)
set -e
cd "$(dirname "$0")"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APP="$DATA/archangesdr/app"
BIN="$HOME/.local/bin/archangesdr"
OLD_BIN="$HOME/.local/bin/sdrscanner"   # the former name: kept as a second command
OLD_APP="$DATA/sdrscanner/app"          # the former install, replaced by this one

if [ "$1" = --uninstall ]; then
  rm -rf "$APP" "$OLD_APP"
  rm -f "$BIN"
  [ -L "$OLD_BIN" ] && rm -f "$OLD_BIN"
  echo "ArchangeSDR removed (settings, ranges and history are kept)."
  exit 0
fi

mkdir -p "$APP" "$(dirname "$BIN")"
rm -rf "$APP/lang" "$APP/ranges"
install -m 755 archangesdr "$APP/archangesdr"
cp -r lang ranges "$APP/"
ln -sf "$APP/archangesdr" "$BIN"
ln -sf "$APP/archangesdr" "$OLD_BIN"
# The former install goes; its data (if it ran standalone) moves at the first start of ArchangeSDR
rm -rf "$OLD_APP"
rmdir "$DATA/sdrscanner" 2>/dev/null || true

# Dependencies: numpy, GTK 4 from Python, librtlsdr; notify-send for desktop notifications (optional)
missing=()
python3 -c 'import numpy' 2>/dev/null || missing+=(numpy)
python3 -c 'import gi; gi.require_version("Gtk", "4.0")' 2>/dev/null || missing+=("GTK 4 for Python")
python3 -c 'import ctypes.util, sys; sys.exit(not ctypes.util.find_library("rtlsdr"))' 2>/dev/null || missing+=(librtlsdr)
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null || missing+=("Python 3.8+")

# The install command of the distribution (ID / ID_LIKE of os-release), else every known one
deps_hint() {
  local ids=""
  [ -r /etc/os-release ] && ids="$(. /etc/os-release; echo "$ID $ID_LIKE")"
  case " $ids " in
    *" arch "*) echo "  sudo pacman -S --needed python-numpy python-gobject gtk4 rtl-sdr libnotify" ;;
    *" debian "*|*" ubuntu "*) echo "  sudo apt install python3-numpy python3-gi gir1.2-gtk-4.0 rtl-sdr libnotify-bin" ;;
    *" fedora "*|*" rhel "*) echo "  sudo dnf install python3-numpy python3-gobject gtk4 rtl-sdr libnotify" ;;
    *" suse "*|*" opensuse "*) echo "  sudo zypper install python3-numpy python3-gobject typelib-1_0-Gtk-4_0 rtl-sdr libnotify-tools" ;;
    *)
      echo "  Arch:            sudo pacman -S --needed python-numpy python-gobject gtk4 rtl-sdr libnotify"
      echo "  Debian / Ubuntu: sudo apt install python3-numpy python3-gi gir1.2-gtk-4.0 rtl-sdr libnotify-bin"
      echo "  Fedora:          sudo dnf install python3-numpy python3-gobject gtk4 rtl-sdr libnotify"
      echo "  openSUSE:        sudo zypper install python3-numpy python3-gobject typelib-1_0-Gtk-4_0 rtl-sdr libnotify-tools"
      ;;
  esac
}
if [ ${#missing[@]} -gt 0 ]; then
  echo "Missing: ${missing[*]}"
  deps_hint
fi
command -v gqrx >/dev/null || echo "Optional: GQRX, for \"Join\" (open a frequency)."
# whisper-cli: the free, local transcription (packaged on Arch, Fedora, Debian testing, Ubuntu 26.04+)
if ! command -v whisper-cli >/dev/null; then
  ids=""
  [ -r /etc/os-release ] && ids="$(. /etc/os-release; echo "$ID $ID_LIKE")"
  case " $ids " in
    *" arch "*) how="sudo pacman -S whisper-cpp" ;;
    *" fedora "*) how="sudo dnf install whisper-cpp" ;;
    *" debian "*|*" ubuntu "*)
      if apt-cache show whisper.cpp-tools >/dev/null 2>&1; then how="sudo apt install whisper.cpp-tools"
      else how="build it: see \"Transcription with whisper.cpp\" in README.md"; fi ;;
    *) how="see \"Transcription with whisper.cpp\" in README.md" ;;
  esac
  echo "Optional: whisper-cli, to transcribe the recordings ($how)."
fi
command -v pw-play >/dev/null || command -v paplay >/dev/null || command -v aplay >/dev/null ||
  echo "Optional: pw-play (PipeWire), paplay or aplay, to play the captures and recordings."
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "Add ~/.local/bin to your PATH." ;; esac
echo "Done: run archangesdr."
