#!/usr/bin/env python3
"""
Conduit - PC helper (Windows)
=============================
Turns an iPhone into a wireless trackpad + keyboard for this PC.

It does two things on ONE port:
  1. Serves the phone app (index.html) over plain HTTP.
  2. Runs the WebSocket server the phone connects to, and replays the
     incoming events as real OS-level mouse/keyboard input via pynput.

Setup (one time):
    pip install aiohttp pynput qrcode

Run:
    python pc_remote.py

Then scan the QR code in this window with your iPhone camera, or open the
printed URL in Safari. Phone and PC must be on the SAME Wi-Fi network.
Tip: in Safari, Share -> "Add to Home Screen" to use it like a real app.
"""

import asyncio
import json
import socket
import sys
from pathlib import Path

try:
    from aiohttp import web, WSMsgType
except ImportError:
    sys.exit("Missing dependency. Run:  pip install aiohttp pynput qrcode")

try:
    from pynput.mouse import Controller as MouseController, Button
    from pynput.keyboard import Controller as KeyController, Key, KeyCode
except ImportError:
    sys.exit("Missing dependency. Run:  pip install aiohttp pynput qrcode")

PORT = 8765
def resource_dir() -> Path:
    # when frozen by PyInstaller (--onefile), files live in the temp _MEIPASS dir
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


HERE = resource_dir()
INDEX = HERE / "index.html"

mouse = MouseController()
kbd = KeyController()

# screen geometry for absolute (drawing-tablet) mapping; set at startup
SCREEN_W, SCREEN_H = 1920, 1080


def detect_screen_size():
    """Primary-monitor size in physical pixels (DPI-aware), for absolute mapping."""
    try:
        import ctypes
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
        u = ctypes.windll.user32
        w, h = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        if w and h:
            return int(w), int(h)
    except Exception:
        pass
    return 1920, 1080

# ---- name -> pynput key maps -------------------------------------------------
MOD_KEYS = {"ctrl": Key.ctrl, "alt": Key.alt, "win": Key.cmd, "shift": Key.shift}
SPECIAL_KEYS = {
    "escape": Key.esc, "tab": Key.tab, "backspace": Key.backspace,
    "enter": Key.enter, "space": Key.space, "delete": Key.delete,
    "left": Key.left, "right": Key.right, "up": Key.up, "down": Key.down,
    "home": Key.home, "end": Key.end, "pageup": Key.page_up, "pagedown": Key.page_down,
}
for _i in range(1, 13):
    SPECIAL_KEYS[f"f{_i}"] = getattr(Key, f"f{_i}")

# media / volume keys (for stream-deck buttons); guarded in case a pynput build lacks them
for _name, _attr in (
    ("volup", "media_volume_up"), ("voldown", "media_volume_down"),
    ("mute", "media_volume_mute"), ("playpause", "media_play_pause"),
    ("next", "media_next"), ("prev", "media_previous"),
):
    _mk = getattr(Key, _attr, None)
    if _mk is not None:
        SPECIAL_KEYS[_name] = _mk

BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}


def resolve_key(name: str):
    """Map an incoming key name to a pynput key/keycode."""
    if name in SPECIAL_KEYS:
        return SPECIAL_KEYS[name]
    if len(name) == 1:
        return KeyCode.from_char(name)
    return None


def handle(evt: dict):
    """Replay one event from the phone as real OS input."""
    t = evt.get("t")

    if t == "move":
        mouse.move(int(evt.get("dx", 0)), int(evt.get("dy", 0)))

    elif t == "scroll":
        mouse.scroll(int(evt.get("dx", 0)), int(evt.get("dy", 0)))

    elif t == "button":
        btn = BUTTONS.get(evt.get("b", "left"), Button.left)
        action = evt.get("a", "click")
        if action == "click":
            mouse.click(btn, 1)
        elif action == "down":
            mouse.press(btn)
        elif action == "up":
            mouse.release(btn)

    elif t == "mod":
        k = MOD_KEYS.get(evt.get("m"))
        if k is not None:
            (kbd.press if evt.get("down") else kbd.release)(k)

    elif t == "key":
        k = resolve_key(evt.get("key", ""))
        if k is not None:
            kbd.press(k)
            kbd.release(k)

    elif t == "combo":
        # atomic shortcut for stream-deck buttons: press mods, tap key, release mods
        mods = evt.get("mods") or []
        held = []
        try:
            for m in mods:
                mk = MOD_KEYS.get(m)
                if mk is not None:
                    kbd.press(mk)
                    held.append(mk)
            k = resolve_key(evt.get("key", ""))
            if k is not None:
                kbd.press(k)
                kbd.release(k)
        finally:
            for mk in reversed(held):
                try:
                    kbd.release(mk)
                except Exception:
                    pass

    elif t == "type":
        # self-heal: never let a stray held modifier swallow typed characters
        for mk in MOD_KEYS.values():
            try:
                kbd.release(mk)
            except Exception:
                pass
        text = evt.get("text", "")
        if text:
            kbd.type(text)

    elif t == "pen":
        # absolute drawing-tablet mapping to the primary monitor
        a = evt.get("a")
        if a == "up":
            try:
                mouse.release(Button.left)
            except Exception:
                pass
            return
        try:
            x = float(evt.get("x", 0.0))
            y = float(evt.get("y", 0.0))
        except (TypeError, ValueError):
            return
        mouse.position = (int(x * SCREEN_W), int(y * SCREEN_H))
        if a == "down":
            mouse.press(Button.left)
        # "move" keeps the already-pressed button down; "hover" just repositions

    elif t == "reset":
        # phone (re)connected: drop any modifiers / buttons we might still be holding
        for mk in MOD_KEYS.values():
            try:
                kbd.release(mk)
            except Exception:
                pass
        try:
            mouse.release(Button.left)
        except Exception:
            pass


# ---- web app -----------------------------------------------------------------
async def index_handler(request):
    if not INDEX.exists():
        return web.Response(status=500, text="index.html not found next to pc_remote.py")
    return web.Response(text=INDEX.read_text(encoding="utf-8"), content_type="text/html")


async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    peer = request.remote
    print(f"  [+] phone connected: {peer}")
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    handle(json.loads(msg.data))
                except Exception as e:
                    print(f"  [!] event error: {e}")
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        # safety: release any modifier or mouse button that might still be held down
        for k in MOD_KEYS.values():
            try:
                kbd.release(k)
            except Exception:
                pass
        try:
            mouse.release(Button.left)
        except Exception:
            pass
        print(f"  [-] phone disconnected: {peer}")
    return ws


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return socket.gethostbyname(socket.gethostname())
    finally:
        s.close()


def print_banner(url: str):
    print("\n" + "=" * 46)
    print("  CONDUIT  ·  iPhone -> PC trackpad & keyboard")
    print("=" * 46)
    print(f"  open on your iPhone:  {url}\n")
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:
        print("  (install 'qrcode' to show a scannable code)")
    print("  · phone + PC must share the same Wi-Fi")
    print("  · first run: allow it through Windows Firewall (Private)")
    print("  · Ctrl+C here to stop\n")


def main():
    global SCREEN_W, SCREEN_H
    SCREEN_W, SCREEN_H = detect_screen_size()

    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", ws_handler)

    url = f"http://{lan_ip()}:{PORT}"
    print_banner(url)
    print(f"  · drawing tablet maps to primary display: {SCREEN_W}x{SCREEN_H}\n")
    try:
        web.run_app(app, host="0.0.0.0", port=PORT, print=None)
    except KeyboardInterrupt:
        print("\n  stopped.")


if __name__ == "__main__":
    main()
