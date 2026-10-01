# -*- coding: utf-8 -*-
"""QR pairing for Nuvio/Stremio — local network, no external server.

Flow:
  1. User picks "Log in with QR" in settings.
  2. The addon starts a tiny HTTP server on the device's LAN IP (random port)
     and shows a QR of  http://<lan-ip>:<port>/  on the TV.
  3. The user scans it with their phone, gets a small form (proper keyboard!),
     enters email + password. The phone POSTs them over the LAN to the addon.
  4. The addon logs in to Nuvio/Stremio directly, stores the token, and the
     server shuts down. The password exists only in RAM for the login call.

Nothing leaves the local network; the credential hop is phone -> TV on the
user's own Wi-Fi. Nuvio's backend (GoTrue) offers no device-code flow for
accounts, so this is the cleanest possible remote-keyboard experience.
"""
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import xbmc
import xbmcgui

from .i18n import tr


_PAIR_TTL = 300  # seconds the pairing window stays open


def _lan_ip():
    """Best-effort LAN IP of this device (works without internet)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return '127.0.0.1'


_PAGE = u'''<!doctype html>
<html lang="en" dir="ltr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Link %(service_title)s — Nuvio Hub</title>
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0b0d14;color:#e7e7ef;
      display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
 .card{background:#141824;border-radius:16px;padding:28px;width:min(420px,92vw);
       box-shadow:0 8px 40px rgba(0,0,0,.5)}
 h1{font-size:20px;margin:0 0 4px} p{color:#9aa0b4;font-size:14px;margin:0 0 20px}
 label{display:block;font-size:13px;margin:14px 0 6px;color:#c6cadb}
 input{width:100%%;box-sizing:border-box;padding:12px;border-radius:10px;border:1px solid #2a3044;
       background:#0e1120;color:#fff;font-size:16px}
 button{width:100%%;margin-top:22px;padding:14px;border:0;border-radius:12px;font-size:16px;
        font-weight:700;color:#fff;background:linear-gradient(135deg,#7c3aed,#06b6d4);cursor:pointer}
 .ok{color:#34d399;text-align:center;font-size:16px;margin-top:16px;display:none}
 .err{color:#f87171;text-align:center;font-size:14px;margin-top:16px;display:none}
</style></head><body><div class="card">
<h1>Link %(service_title)s account</h1>
<p>Enter your account details. They are sent directly to your Kodi device over your local network only.</p>
<label>Email</label>
<input id="email" type="email" autocomplete="username" inputmode="email">
<label>Password</label>
<input id="password" type="password" autocomplete="current-password">
<button onclick="go()">Link account</button>
<div class="ok" id="ok">Linked successfully ✓ — return to your TV</div>
<div class="err" id="err"></div>
<script>
async function go(){
  const e=document.getElementById('email').value.trim();
  const p=document.getElementById('password').value;
  const ok=document.getElementById('ok'), er=document.getElementById('err');
  ok.style.display='none'; er.style.display='none';
  if(!e||!p){er.textContent='Enter your email and password';er.style.display='block';return}
  try{
    const r=await fetch('/pair',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({token:'%(token)s',email:e,password:p})});
    const d=await r.json();
    if(d.ok){ok.style.display='block'}
    else{er.textContent=d.error||'Login failed';er.style.display='block'}
  }catch(x){er.textContent='Could not reach the device — make sure both devices are on the same network';er.style.display='block'}
}
</script></div></body></html>'''


class _PairWindow(xbmcgui.WindowDialog):
    def __init__(self, *args, **kwargs):
        self.cancelled = False
        qr_path = kwargs.get('qr_path') or ''
        url = kwargs.get('url') or ''
        service_title = kwargs.get('service_title') or ''
        w, h = 980, 520
        x, y = (1280 - w) // 2, (720 - h) // 2
        self.addControl(xbmcgui.ControlImage(x, y, w, h, '', colorDiffuse='EE080810'))
        if qr_path:
            self.addControl(xbmcgui.ControlImage(x + 45, y + 70, 360, 360, qr_path))
        self.addControl(xbmcgui.ControlLabel(
            x + 440, y + 55, w - 485, 46,
            '%s %s' % (tr('Link account'), service_title), textColor='FFFFFFFF'))
        self._body = xbmcgui.ControlTextBox(x + 440, y + 115, w - 485, 340)
        self.addControl(self._body)
        self.set_status(
            tr('Scan the QR code with your phone camera.') + '\n\n'
            + tr('A page will open where you type your email and password using your phone keyboard. They are sent straight to this device over your local network and never pass through any external server.') + '\n\n'
            + tr('Or open this link manually:') + '\n[B][COLOR cyan]%s[/COLOR][/B]\n\n' % url
            + tr('Waiting to link…'))

    def set_status(self, text):
        try:
            self._body.setText(text)
        except Exception:
            pass

    def onAction(self, action):
        try:
            if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
                self.cancelled = True
                self.close()
        except Exception:
            self.cancelled = True
            self.close()
