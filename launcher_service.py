from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, IO, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen


def resolve_base_dir() -> Path:
  if getattr(sys, "frozen", False):
    return Path(sys.executable).resolve().parent
  return Path(__file__).resolve().parent


BASE_DIR = resolve_base_dir()
APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Koffmatic" / "IEDsimulator"
RUNTIME_DIR = APP_DATA_DIR / "runtime"
TOOLS_DIR = APP_DATA_DIR / "tools"
STATE_FILE = RUNTIME_DIR / "launcher_state.json"

DEFAULT_EXE_FIELD = "./ied_mms_server.exe"
DEFAULT_NETWORK_ADAPTER = "Ethernet"
DEFAULT_PORT = 102
DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8787
AUTO_RANDOM_INTERVAL_MS = 1000
PROCESS_POLL_INTERVAL_MS = 500
MAX_LOG_LINES = 250

HARDCODED_IED_KEYS_BY_NAME = {
  "REF615_SIM_01": "AA1H1H01BCF1",
  "REU615_SIM_01": "AA1H1H12BAR1",
  "RED615_SIM_01": "AA1H1311CR100BCD1",
}

STATUS_TONES = {"idle", "running", "stopped", "warning", "error"}

REF615_ANALOG_TAGS = [
    "LD0.CMMXU1.A.phsA.instCVal.mag.f",
    "LD0.CMMXU1.A.phsB.instCVal.mag.f",
    "LD0.CMMXU1.A.phsC.instCVal.mag.f",
    "LD0.VMMXU1.PPV.phsAB.instCVal.mag.f",
    "LD0.VMMXU1.PPV.phsBC.instCVal.mag.f",
    "LD0.VMMXU1.PPV.phsCA.instCVal.mag.f",
    "LD0.FMMXU1.Hz.instMag.f",
    "LD0.PEMMXU1.TotPF.instMag.f",
    "LD0.PEMMXU1.TotW.instMag.f",
    "LD0.PEMMXU1.TotVAr.instMag.f",
    "LD0.PEMMXU1.TotVA.instMag.f",
]

RELAY_ANALOG_TAGS = {
    "REF615": REF615_ANALOG_TAGS,
    "REU615": [
        "LD0.VMMXU1.PPV.phsAB.instCVal.mag.f",
        "LD0.VMMXU1.PPV.phsBC.instCVal.mag.f",
        "LD0.VMMXU1.PPV.phsCA.instCVal.mag.f",
        "LD0.FMMXU1.Hz.instMag.f",
    ],
    "RED615": [
        "LD0.CMMXU1.A.phsA.instCVal.mag.f",
        "LD0.CMMXU1.A.phsB.instCVal.mag.f",
        "LD0.CMMXU1.A.phsC.instCVal.mag.f",
    ],
}

COMMON_WORD_TAGS = [
    "LD0.SSCBR1.Mod.Oper.ctlVal",
    "LD0.SSCBR1.Beh.stVal",
]

COMMON_BOOL_TAGS = [
    *[f"LD0.LEDGGIO1.Ind{index}.stVal" for index in range(1, 12)],
    *[f"LD0.LEDGGIO1.Alm{index}.stVal" for index in range(1, 12)],
]

ANALOG_DEFAULTS = {
    "LD0.CMMXU1.A.phsA.instCVal.mag.f": 18.4,
    "LD0.CMMXU1.A.phsB.instCVal.mag.f": 18.1,
    "LD0.CMMXU1.A.phsC.instCVal.mag.f": 18.7,
    "LD0.VMMXU1.PPV.phsAB.instCVal.mag.f": 400.2,
    "LD0.VMMXU1.PPV.phsBC.instCVal.mag.f": 399.7,
    "LD0.VMMXU1.PPV.phsCA.instCVal.mag.f": 401.1,
    "LD0.FMMXU1.Hz.instMag.f": 50.0,
    "LD0.PEMMXU1.TotPF.instMag.f": 0.97,
    "LD0.PEMMXU1.TotW.instMag.f": 1250.0,
    "LD0.PEMMXU1.TotVAr.instMag.f": 210.0,
    "LD0.PEMMXU1.TotVA.instMag.f": 1280.0,
}

ANALOG_RANDOM_RANGES = {
    "LD0.CMMXU1.A.phsA.instCVal.mag.f": (0.0, 250.0),
    "LD0.CMMXU1.A.phsB.instCVal.mag.f": (0.0, 250.0),
    "LD0.CMMXU1.A.phsC.instCVal.mag.f": (0.0, 250.0),
    "LD0.VMMXU1.PPV.phsAB.instCVal.mag.f": (380.0, 420.0),
    "LD0.VMMXU1.PPV.phsBC.instCVal.mag.f": (380.0, 420.0),
    "LD0.VMMXU1.PPV.phsCA.instCVal.mag.f": (380.0, 420.0),
    "LD0.FMMXU1.Hz.instMag.f": (49.7, 50.3),
    "LD0.PEMMXU1.TotPF.instMag.f": (0.80, 1.00),
    "LD0.PEMMXU1.TotW.instMag.f": (0.0, 2000.0),
    "LD0.PEMMXU1.TotVAr.instMag.f": (-500.0, 500.0),
    "LD0.PEMMXU1.TotVA.instMag.f": (0.0, 2200.0),
}

WORD_DEFAULTS = {
    "LD0.SSCBR1.Mod.Oper.ctlVal": 1,
    "LD0.SSCBR1.Beh.stVal": 1,
}

WORD_RANDOM_RANGES = {
    "LD0.SSCBR1.Mod.Oper.ctlVal": (0, 4),
    "LD0.SSCBR1.Beh.stVal": (1, 5),
}

BOOL_DEFAULTS = {tag: tag.startswith("LD0.LEDGGIO1.Ind") for tag in COMMON_BOOL_TAGS}

HTML_PAGE = """<!doctype html>
<html lang="fi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IED Simulator Control Room</title>
  <link rel="stylesheet" href="/app.css">
</head>
<body>
  <div id="app"></div>
  <script src="/app.js" defer></script>
</body>
</html>
"""

CSS_PAGE = """:root {
  --bg: #f5efe4;
  --panel: rgba(255, 250, 240, 0.92);
  --panel-strong: rgba(255, 248, 235, 0.98);
  --text: #1f2933;
  --muted: #6b7280;
  --line: rgba(115, 92, 55, 0.18);
  --brand: #0f766e;
  --brand-strong: #115e59;
  --warning: #b45309;
  --danger: #b91c1c;
  --surface-shadow: 0 18px 40px rgba(66, 49, 24, 0.12);
  --radius-lg: 24px;
  --radius-md: 16px;
  --radius-sm: 12px;
  --font-ui: Bahnschrift, "Trebuchet MS", "Segoe UI", sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  font-family: var(--font-ui);
  color: var(--text);
  background:
    radial-gradient(circle at top left, rgba(15, 118, 110, 0.20), transparent 34%),
    radial-gradient(circle at bottom right, rgba(234, 179, 8, 0.18), transparent 30%),
    linear-gradient(160deg, #fbf6ec 0%, #efe3cf 100%);
}

button,
input,
select,
textarea {
  font: inherit;
}

.shell {
  width: min(1520px, calc(100vw - 28px));
  margin: 20px auto;
  padding: 26px;
  border-radius: 30px;
  background: rgba(255, 252, 246, 0.68);
  backdrop-filter: blur(18px);
  box-shadow: var(--surface-shadow);
  border: 1px solid rgba(255, 255, 255, 0.65);
}

.hero {
  display: grid;
  grid-template-columns: 1.4fr 1fr;
  gap: 18px;
  margin-bottom: 20px;
}

.hero-card,
.panel,
.relay-card,
.log-panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  box-shadow: 0 10px 20px rgba(85, 66, 39, 0.06);
}

.hero-card {
  padding: 24px;
}

.hero-card h1 {
  margin: 0;
  font-size: clamp(2rem, 3vw, 3rem);
  line-height: 1;
  letter-spacing: 0.01em;
}

.hero-card p,
.panel p,
.muted,
.relay-meta,
.help-line {
  color: var(--muted);
}

.hero-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.stat {
  padding: 18px;
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.64);
  border: 1px solid rgba(115, 92, 55, 0.12);
}

.stat-label {
  display: block;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--muted);
}

.stat-value {
  display: block;
  margin-top: 8px;
  font-size: 1.8rem;
  font-weight: 700;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: end;
}

.toolbar .field {
  flex: 1 1 340px;
}

.field label {
  display: block;
  margin-bottom: 6px;
  font-size: 0.85rem;
  color: var(--muted);
}

.field input,
.field select,
.field textarea,
.tag-row input {
  width: 100%;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid rgba(115, 92, 55, 0.18);
  background: rgba(255, 255, 255, 0.9);
  color: var(--text);
}

.field textarea {
  min-height: 90px;
  resize: vertical;
}

.button-row,
.card-actions,
.tag-actions,
.settings-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.button,
.tag-button,
.card-actions button,
.settings-actions button,
.toolbar button {
  border: none;
  border-radius: 999px;
  padding: 11px 16px;
  cursor: pointer;
  background: var(--brand);
  color: #f5fffe;
  transition: transform 140ms ease, box-shadow 140ms ease, background 140ms ease;
  box-shadow: 0 10px 18px rgba(15, 118, 110, 0.18);
}

button:hover {
  transform: translateY(-1px);
  box-shadow: 0 14px 24px rgba(15, 118, 110, 0.22);
}

button.secondary {
  background: #d6d3d1;
  color: #1f2933;
  box-shadow: none;
}

button.warning {
  background: var(--warning);
}

button.danger {
  background: var(--danger);
}

.status-banner {
  margin: 18px 0;
  padding: 14px 18px;
  border-radius: var(--radius-md);
  border: 1px solid rgba(15, 118, 110, 0.18);
  background: rgba(15, 118, 110, 0.08);
}

.status-banner.warning {
  border-color: rgba(180, 83, 9, 0.18);
  background: rgba(180, 83, 9, 0.08);
}

.status-banner.error {
  border-color: rgba(185, 28, 28, 0.18);
  background: rgba(185, 28, 28, 0.08);
}

.layout {
  display: grid;
  grid-template-columns: 1fr;
  gap: 18px;
}

.panel {
  padding: 20px;
}

.relay-grid {
  column-count: 2;
  column-gap: 16px;
}

.relay-card {
  display: inline-block;
  width: 100%;
  margin: 0 0 16px;
  padding: 18px;
  position: relative;
  overflow: hidden;
  break-inside: avoid;
  page-break-inside: avoid;
}

.relay-card::after {
  content: "";
  position: absolute;
  inset: auto -40px -60px auto;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: rgba(15, 118, 110, 0.06);
}

.relay-card.running {
  border-color: rgba(15, 118, 110, 0.32);
}

.relay-card.warning {
  border-color: rgba(180, 83, 9, 0.32);
}

.relay-card.error {
  border-color: rgba(185, 28, 28, 0.32);
}

.relay-head {
  display: flex;
  gap: 12px;
  align-items: start;
  justify-content: space-between;
}

.relay-head h3 {
  margin: 0;
  font-size: 1.2rem;
}

.relay-meta {
  margin-top: 6px;
  font-size: 0.95rem;
}

.relay-warning {
  margin-top: 8px;
  color: var(--warning);
  font-weight: 600;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 999px;
  font-size: 0.85rem;
  background: rgba(107, 114, 128, 0.12);
}

.status-pill.running {
  background: rgba(15, 118, 110, 0.12);
  color: var(--brand-strong);
}

.status-pill.warning {
  background: rgba(180, 83, 9, 0.12);
  color: var(--warning);
}

.status-pill.error {
  background: rgba(185, 28, 28, 0.12);
  color: var(--danger);
}

details {
  margin-top: 14px;
  position: relative;
  z-index: 1;
}

summary {
  cursor: pointer;
  color: var(--brand-strong);
  font-weight: 600;
}

.relay-form {
  display: grid;
  gap: 16px;
  margin-top: 16px;
}

.relay-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.relay-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding-top: 34px;
}

.tag-section {
  padding: 14px;
  border-radius: var(--radius-md);
  border: 1px solid rgba(115, 92, 55, 0.14);
  background: rgba(255, 255, 255, 0.62);
}

.tag-section h4 {
  margin: 0 0 6px;
}

.tag-list {
  display: grid;
  gap: 8px;
}

.tag-row {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(120px, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.range-row {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(110px, 1fr) minmax(110px, 1fr);
  gap: 8px;
  align-items: center;
}

.tag-row.bool {
  grid-template-columns: minmax(0, 1.8fr) auto auto;
}

.tag-row .bool-wrap {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
}

.range-label {
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid rgba(115, 92, 55, 0.18);
  background: rgba(246, 241, 232, 0.95);
  overflow-wrap: anywhere;
}

.modal-overlay {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow-y: auto;
  padding: 18px;
  background: rgba(31, 41, 51, 0.48);
  z-index: 1000;
}

.modal-card {
  width: min(900px, 100%);
  margin: auto;
  max-height: calc(100dvh - 36px);
  overflow: auto;
  padding: 20px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--line);
  background: var(--panel-strong);
  box-shadow: var(--surface-shadow);
}

.modal-card h3 {
  margin-top: 0;
}

.modal-card .toolbar {
  align-items: center;
}

.selection-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.selection-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid rgba(115, 92, 55, 0.14);
  background: rgba(255, 255, 255, 0.72);
}

.log-panel {
  padding: 18px;
}

.log-panel pre {
  margin: 0;
  min-height: 180px;
  max-height: 340px;
  overflow: auto;
  padding: 14px;
  border-radius: var(--radius-md);
  background: #1f2933;
  color: #e5ecef;
  font-family: Consolas, "Courier New", monospace;
  font-size: 0.92rem;
}

.empty-state {
  padding: 24px;
  text-align: center;
  border-radius: var(--radius-lg);
  border: 1px dashed rgba(115, 92, 55, 0.2);
  color: var(--muted);
  background: rgba(255, 255, 255, 0.55);
}

@media (max-width: 1100px) {
  .hero {
    grid-template-columns: 1fr;
  }

  .hero-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 780px) {
  .shell {
    width: calc(100vw - 12px);
    margin: 6px auto;
    padding: 16px;
    border-radius: 20px;
  }

  .hero-grid,
  .relay-fields,
  .range-row,
  .selection-list,
  .tag-row,
  .tag-row.bool {
    grid-template-columns: 1fr;
  }

  .relay-grid {
    column-count: 1;
  }

  .relay-head {
    flex-direction: column;
  }
}
"""


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def safe_name(value: str) -> str:
    cleaned = []
    for char in value.strip():
        if char.isalnum() or char in ("-", "_"):
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "".join(cleaned) or "IED"


def to_relative_posix(path: Path) -> str:
    try:
        return path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return str(path)


def normalize_relay_type(value: Any) -> str:
    text = str(value or "REF615").strip().upper()
    if text not in RELAY_ANALOG_TAGS:
        return "REF615"
    return text


def coerce_port(value: Any, default: int = DEFAULT_PORT) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if 1 <= parsed <= 65535:
        return parsed
    return default


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def analog_default_for(tag: str) -> float:
    return float(ANALOG_DEFAULTS.get(tag, 0.0))


def word_default_for(tag: str) -> int:
    return int(WORD_DEFAULTS.get(tag, 0))


def bool_default_for(tag: str) -> bool:
    return bool(BOOL_DEFAULTS.get(tag, False))


def analog_random_for(tag: str) -> float:
    low, high = ANALOG_RANDOM_RANGES.get(tag, (0.0, 100.0))
    return round(random.uniform(low, high), 3)


def word_random_for(tag: str) -> int:
    low, high = WORD_RANDOM_RANGES.get(tag, (0, 10))
    return random.randint(low, high)


def bool_random_for(tag: str) -> bool:
    if ".Ind" in tag:
        return random.random() >= 0.25
    if ".Alm" in tag:
        return random.random() >= 0.90
    return random.random() >= 0.50


def build_default_analogs(relay_type: str) -> Dict[str, float]:
    relay_type = normalize_relay_type(relay_type)
    return {tag: analog_default_for(tag) for tag in RELAY_ANALOG_TAGS[relay_type]}


def build_default_words() -> Dict[str, int]:
    return {tag: word_default_for(tag) for tag in COMMON_WORD_TAGS}


def build_default_bools() -> Dict[str, bool]:
    return {tag: bool_default_for(tag) for tag in COMMON_BOOL_TAGS}


def default_ied_key_for(name: str) -> str:
    cleaned_name = str(name or "").strip()
    return HARDCODED_IED_KEYS_BY_NAME.get(cleaned_name, cleaned_name)


def default_row_specs() -> List[Dict[str, Any]]:
  rows: List[Dict[str, Any]] = []
  for index in range(1, 12):
    name = f"REF615_SIM_{index:02d}"
    rows.append(
      {
        "enabled": True,
        "name": name,
        "ied_key": default_ied_key_for(name),
        "relay_type": "REF615",
        "ip": f"10.206.204.{index + 4}",
        "port": DEFAULT_PORT,
      }
    )

  for index in range(1, 3):
    name = f"REU615_SIM_{index:02d}"
    rows.append(
      {
        "enabled": True,
        "name": name,
        "ied_key": default_ied_key_for(name),
        "relay_type": "REU615",
        "ip": f"10.206.204.{index + 15}",
        "port": DEFAULT_PORT,
      }
    )

    name = "RED615_SIM_01"
    rows.append(
        {
            "enabled": True,
            "name": name,
            "ied_key": default_ied_key_for(name),
            "relay_type": "RED615",
            "ip": "10.206.204.18",
            "port": DEFAULT_PORT,
        }
    )
  return rows


def render_ip_alias_script(ip_addresses: List[str]) -> str:
  return render_ip_alias_script_for_adapter(DEFAULT_NETWORK_ADAPTER, ip_addresses)


def list_network_adapters() -> List[Dict[str, str]]:
  if os.name != "nt":
    return []

  command = (
    "Get-NetAdapter | Where-Object Status -ne 'Disabled' | "
    "Sort-Object @{Expression={ if ($_.Status -eq 'Up') {0} else {1} }}, Name | "
    "Select-Object Name, InterfaceDescription, Status | ConvertTo-Json -Compress"
  )
  try:
    result = subprocess.run(
      ["powershell", "-NoProfile", "-Command", command],
      capture_output=True,
      text=True,
      timeout=8,
      check=False,
      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
  except Exception:
    return []

  raw_output = result.stdout.strip()
  if result.returncode != 0 or not raw_output:
    return []

  try:
    payload = json.loads(raw_output)
  except json.JSONDecodeError:
    return []

  if isinstance(payload, dict):
    payload = [payload]
  if not isinstance(payload, list):
    return []

  adapters: List[Dict[str, str]] = []
  for entry in payload:
    if not isinstance(entry, dict):
      continue
    name = str(entry.get("Name", "")).strip()
    if not name:
      continue
    adapters.append(
      {
        "name": name,
        "description": str(entry.get("InterfaceDescription", "")).strip(),
        "status": str(entry.get("Status", "Unknown")).strip() or "Unknown",
      }
    )
  return adapters


def coerce_network_adapter(value: Any, adapters: List[Dict[str, str]]) -> str:
  requested = str(value or "").strip()
  names = [entry.get("name", "") for entry in adapters if entry.get("name")]
  if requested and requested in names:
    return requested
  if DEFAULT_NETWORK_ADAPTER in names:
    return DEFAULT_NETWORK_ADAPTER
  up_names = [entry["name"] for entry in adapters if entry.get("status") == "Up" and entry.get("name")]
  if up_names:
    return up_names[0]
  if names:
    return names[0]
  return requested or DEFAULT_NETWORK_ADAPTER


def list_adapter_ipv4_addresses(adapter_name: str) -> List[str]:
  cleaned_name = str(adapter_name or "").strip()
  if os.name != "nt" or not cleaned_name:
    return []

  escaped_name = cleaned_name.replace("'", "''")
  command = (
    f"$items = @(Get-NetIPAddress -InterfaceAlias '{escaped_name}' -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
    "Select-Object -ExpandProperty IPAddress); "
    "if ($items.Count -eq 0) { '[]' } else { $items | ConvertTo-Json -Compress }"
  )
  try:
    result = subprocess.run(
      ["powershell", "-NoProfile", "-Command", command],
      capture_output=True,
      text=True,
      timeout=8,
      check=False,
      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
  except Exception:
    return []

  raw_output = result.stdout.strip()
  if result.returncode != 0 or not raw_output:
    return []

  try:
    payload = json.loads(raw_output)
  except json.JSONDecodeError:
    return []

  if isinstance(payload, str):
    payload = [payload]
  if not isinstance(payload, list):
    return []

  addresses: List[str] = []
  for entry in payload:
    value = str(entry or "").strip()
    if value and value not in addresses:
      addresses.append(value)
  return addresses


def render_ip_alias_script_for_adapter(adapter_name: str, ip_addresses: List[str]) -> str:
    unique_ips = []
    seen = set()
    for ip_address in ip_addresses:
        cleaned = ip_address.strip()
        if not cleaned or cleaned in seen:
            continue
        unique_ips.append(cleaned)
        seen.add(cleaned)

    quoted_ips = ",\n    ".join(f'"{ip_address}"' for ip_address in unique_ips)
    escaped_adapter_name = adapter_name.replace("'", "''")
    return f'''# Run this PowerShell script as Administrator.
# Each simulated IED requires its own local IP alias on the same adapter.

$adapterName = '{escaped_adapter_name}'
$prefixLength = 24
$ipAddresses = @(
    {quoted_ips}
)

  $adapter = Get-NetAdapter -Name $adapterName -ErrorAction SilentlyContinue
  if ($null -eq $adapter) {{
    throw "Network adapter '$adapterName' was not found. Refresh the adapter list and try again."
  }}

foreach ($ipAddress in $ipAddresses) {{
    if ([string]::IsNullOrWhiteSpace($ipAddress)) {{
        continue
    }}

    $existingIps = @(Get-NetIPAddress -IPAddress $ipAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue)

    if ($existingIps.Count -gt 0) {{
      $existingOnAdapter = @($existingIps | Where-Object InterfaceAlias -eq $adapterName)
      if ($existingOnAdapter.Count -gt 0) {{
        Write-Host "$ipAddress already exists on $adapterName"
        continue
      }}

      $otherAdapters = @($existingIps | Select-Object -ExpandProperty InterfaceAlias -Unique)
      Write-Warning "$ipAddress already exists on another adapter: $($otherAdapters -join ', '). Skipping."
      continue
    }}

    try {{
      New-NetIPAddress -InterfaceAlias $adapterName -IPAddress $ipAddress -PrefixLength $prefixLength -AddressFamily IPv4 -ErrorAction Stop | Out-Null
      Write-Host "Added $ipAddress to $adapterName"
    }} catch {{
      Write-Warning ("Failed to add {{0}} to {{1}}: {{2}}" -f $ipAddress, $adapterName, $_.Exception.Message)
    }}
}}

Start-Sleep -Seconds 5
'''


@dataclass
class RelayRow:
    row_id: int
    enabled: bool
    name: str
    ied_key: str
    relay_type: str
    ip: str
    port: int
    analogs: Dict[str, float]
    words: Dict[str, int]
    bools: Dict[str, bool]
    analog_random_ranges: Dict[str, Tuple[float, float]]
    word_random_ranges: Dict[str, Tuple[int, int]]
    status_text: str = "idle"
    status_tone: str = "idle"
    process: Optional[subprocess.Popen] = field(default=None, repr=False)
    process_log: Optional[IO[str]] = field(default=None, repr=False)


class LauncherState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.rows: List[RelayRow] = []
        self.network_adapter_options: List[Dict[str, str]] = list_network_adapters()
        self.network_adapter = DEFAULT_NETWORK_ADAPTER
        self.adapter_ipv4_addresses: List[str] = []
        self.adapter_ip_refresh_ms = 0
        self.logs: Deque[str] = deque(maxlen=MAX_LOG_LINES)
        self.exe_path = DEFAULT_EXE_FIELD
        self.auto_random_enabled = False
        self.last_auto_random_ms = 0
        self.activity = "Ready. Open localhost in a browser to control the simulator."
        self.next_row_id = 1
        self.browser_url = f"http://{DEFAULT_WEB_HOST}:{DEFAULT_WEB_PORT}"
        self._maintenance_thread = threading.Thread(target=self._maintenance_loop, name="launcher-maintenance", daemon=True)
        self._load_state()
        with self.lock:
            self._write_all_runtime_files_unlocked(log=False)
            self._cleanup_stale_runtime_files_unlocked(log=False)
            self._generate_ip_alias_script_unlocked(log=False)

    def configure_service_endpoint(self, host: str, port: int) -> None:
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        with self.lock:
            self.browser_url = f"http://{display_host}:{port}"

    def start(self) -> None:
        if not self._maintenance_thread.is_alive():
            self._maintenance_thread.start()
        with self.lock:
            self._log_unlocked(f"Launcher available at {self.browser_url}")

    def shutdown(self) -> None:
        self.stop_event.set()
        if self._maintenance_thread.is_alive():
            self._maintenance_thread.join(timeout=2.0)
        with self.lock:
            for row in list(self.rows):
                self._stop_row_unlocked(row, log=True)
            self._persist_state_unlocked()
            self._log_unlocked("Launcher stopped")

    def snapshot(self) -> Dict[str, Any]:
      with self.lock:
        self._refresh_adapter_ipv4_addresses_unlocked()
        self._poll_processes_unlocked()
        rows = [self._row_to_api_dict(row, index) for index, row in enumerate(self.rows, start=1)]
        running = sum(1 for row in self.rows if row.process is not None and row.process.poll() is None)
        enabled = sum(1 for row in self.rows if row.enabled)
        return {
          "activity": self.activity,
          "auto_random_enabled": self.auto_random_enabled,
          "browser_url": self.browser_url,
          "network_adapter": self.network_adapter,
          "network_adapter_options": list(self.network_adapter_options),
          "relay_types": list(RELAY_ANALOG_TAGS.keys()),
          "rows": rows,
          "stats": {
            "total": len(self.rows),
            "enabled": enabled,
            "running": running,
          },
          "log_lines": list(self.logs),
          "ip_script_path": to_relative_posix(TOOLS_DIR / "add_ip_aliases.ps1"),
        }

    def update_settings(self, payload: Dict[str, Any]) -> str:
      with self.lock:
        self.exe_path = DEFAULT_EXE_FIELD
        self.network_adapter_options = list_network_adapters()
        requested_adapter = str(payload.get("network_adapter", "")).strip()
        if requested_adapter:
          available_names = {entry.get("name", "") for entry in self.network_adapter_options}
          if available_names and requested_adapter not in available_names:
            raise ValueError(f"Network adapter '{requested_adapter}' was not found")
          self.network_adapter = requested_adapter
        else:
          self.network_adapter = coerce_network_adapter(self.network_adapter, self.network_adapter_options)
        self._refresh_adapter_ipv4_addresses_unlocked(force=True)
        self._write_all_runtime_files_unlocked(log=False)
        self._cleanup_stale_runtime_files_unlocked(log=False)
        self._generate_ip_alias_script_unlocked(log=False)
        self._persist_state_unlocked()
        self._log_unlocked(f"Network adapter set to {self.network_adapter}")
        return self.activity

    def add_row(self, payload: Dict[str, Any]) -> str:
        relay_type = normalize_relay_type(payload.get("relay_type", "REF615"))
        with self.lock:
            row = self._new_row_unlocked(relay_type)
            self.rows.append(row)
            self._write_row_runtime_files_unlocked(row, log=False)
            self._cleanup_stale_runtime_files_unlocked(log=False)
            self._generate_ip_alias_script_unlocked(log=False)
            self._persist_state_unlocked()
            self._log_unlocked(f"Added {row.name}")
            return self.activity

    def update_row(self, row_id: int, payload: Dict[str, Any]) -> str:
        with self.lock:
            row = self._require_row_unlocked(row_id)
            previous = (row.name, row.relay_type, row.ip, row.port)
            self._apply_row_payload_unlocked(row, payload)
            self._write_row_runtime_files_unlocked(row, log=False)
            self._cleanup_stale_runtime_files_unlocked(log=False)
            self._generate_ip_alias_script_unlocked(log=False)
            self._persist_state_unlocked()
            current = (row.name, row.relay_type, row.ip, row.port)
            if row.process is not None and row.process.poll() is None and current != previous:
                self._log_unlocked(f"Saved {row.name}. Restart is required for name/type/IP/port changes to affect the running process")
            else:
                self._log_unlocked(f"Saved {row.name}")
            return self.activity

    def remove_row(self, row_id: int) -> str:
        with self.lock:
            row = self._require_row_unlocked(row_id)
            self._stop_row_unlocked(row, log=False)
            self.rows = [candidate for candidate in self.rows if candidate.row_id != row_id]
            self._cleanup_stale_runtime_files_unlocked(log=False)
            self._generate_ip_alias_script_unlocked(log=False)
            self._persist_state_unlocked()
            self._log_unlocked(f"Removed {row.name}")
            return self.activity

    def write_row_runtime_files(self, row_id: int) -> str:
        with self.lock:
            row = self._require_row_unlocked(row_id)
            self._write_row_runtime_files_unlocked(row, log=True)
            self._cleanup_stale_runtime_files_unlocked(log=False)
            self._persist_state_unlocked()
            return self.activity

    def write_all_runtime_files(self) -> str:
      with self.lock:
        self._write_all_runtime_files_unlocked(log=False)
        self._cleanup_stale_runtime_files_unlocked(log=True)
        self._persist_state_unlocked()
        self._log_unlocked(f"Wrote runtime JSON files for {len(self.rows)} relays")
        return self.activity

    def start_row(self, row_id: int) -> str:
        with self.lock:
            row = self._require_row_unlocked(row_id)
            self._start_row_unlocked(row)
            self._persist_state_unlocked()
            return self.activity

    def stop_row(self, row_id: int) -> str:
        with self.lock:
            row = self._require_row_unlocked(row_id)
            self._stop_row_unlocked(row, log=True)
            self._persist_state_unlocked()
            return self.activity

    def start_all(self) -> str:
        with self.lock:
            enabled_rows = [row for row in self.rows if row.enabled]
            if not enabled_rows:
                self._log_unlocked("Start all skipped: no relay rows are enabled")
            for row in enabled_rows:
                self._start_row_unlocked(row)
            self._persist_state_unlocked()
            return self.activity

    def stop_all(self) -> str:
        with self.lock:
            for row in list(self.rows):
                self._stop_row_unlocked(row, log=False)
            self._persist_state_unlocked()
            self._log_unlocked("Stopped all relays")
            return self.activity

    def randomize_row(self, row_id: int) -> str:
        with self.lock:
            row = self._require_row_unlocked(row_id)
            self._randomize_row_unlocked(row)
            self._write_row_runtime_files_unlocked(row, log=False)
            self._persist_state_unlocked()
            self._log_unlocked(f"Randomized values for {row.name}")
            return self.activity

    def update_random_settings(self, row_id: int, payload: Dict[str, Any]) -> str:
      with self.lock:
        row = self._require_row_unlocked(row_id)
        row.analog_random_ranges = self._coerce_range_entries(
          payload.get("analog_random_ranges"),
          "analogs",
          list(row.analogs.keys()),
          row.analog_random_ranges,
        )
        row.word_random_ranges = self._coerce_range_entries(
          payload.get("word_random_ranges"),
          "words",
          list(row.words.keys()),
          row.word_random_ranges,
        )
        self._persist_state_unlocked()
        self._log_unlocked(f"Saved random ranges for {row.name}")
        return self.activity

    def toggle_auto_random(self) -> str:
        with self.lock:
            self.auto_random_enabled = not self.auto_random_enabled
            self.last_auto_random_ms = 0
            self._persist_state_unlocked()
            if self.auto_random_enabled:
                self._log_unlocked("Auto random enabled")
            else:
                self._log_unlocked("Auto random stopped")
            return self.activity

    def generate_ip_alias_script(self) -> str:
        with self.lock:
            self._generate_ip_alias_script_unlocked(log=True)
            self._persist_state_unlocked()
            return self.activity

    def prepare_network(self) -> str:
      with self.lock:
        self._generate_ip_alias_script_unlocked(log=False)
        script_path = TOOLS_DIR / "add_ip_aliases.ps1"
        adapter_name = self.network_adapter

      command = (
        "$scriptPath = '{0}'; "
        "Start-Process powershell -Verb RunAs -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',$scriptPath)"
      ).format(str(script_path).replace("'", "''"))

      try:
        subprocess.run(
          ["powershell", "-NoProfile", "-Command", command],
          capture_output=True,
          text=True,
          timeout=10,
          check=False,
          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
      except Exception as exc:
        with self.lock:
          self._log_unlocked(f"Network preparation failed to start ({exc})")
          raise RuntimeError("Failed to start network preparation") from exc

      with self.lock:
        self._persist_state_unlocked()
        self._log_unlocked(f"Network preparation launched for {adapter_name}. Accept the Windows prompt to continue")
        return self.activity

    def _maintenance_loop(self) -> None:
        while not self.stop_event.wait(PROCESS_POLL_INTERVAL_MS / 1000.0):
            with self.lock:
                self._poll_processes_unlocked()
                if not self.auto_random_enabled:
                    continue
                current_ms = now_ms()
                if current_ms - self.last_auto_random_ms < AUTO_RANDOM_INTERVAL_MS:
                    continue
                targets = [row for row in self.rows if row.enabled] or list(self.rows)
                for row in targets:
                    self._randomize_row_unlocked(row)
                    self._write_row_runtime_files_unlocked(row, log=False)
                self.last_auto_random_ms = current_ms
                self.activity = f"Auto random updated {len(targets)} relays at {time.strftime('%H:%M:%S')}"
                self._persist_state_unlocked()

    def _load_state(self) -> None:
        with self.lock:
            payload: Dict[str, Any] = {}
            if STATE_FILE.exists():
                try:
                    payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    self._log_unlocked("State file was invalid JSON. Falling back to defaults")

            self.exe_path = DEFAULT_EXE_FIELD
            self.network_adapter_options = list_network_adapters()
            self.network_adapter = coerce_network_adapter(payload.get("network_adapter", DEFAULT_NETWORK_ADAPTER), self.network_adapter_options)
            self._refresh_adapter_ipv4_addresses_unlocked(force=True)
            self.auto_random_enabled = bool(payload.get("auto_random_enabled", False))
            rows_payload = payload.get("rows")
            if not isinstance(rows_payload, list) or not rows_payload:
                rows_payload = default_row_specs()

            self.rows = []
            self.next_row_id = 1
            for raw_row in rows_payload:
                row = self._coerce_row_from_payload_unlocked(raw_row)
                self.rows.append(row)
            self._persist_state_unlocked()

    def _persist_state_unlocked(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
          "exe_path": self.exe_path,
            "network_adapter": self.network_adapter,
            "auto_random_enabled": self.auto_random_enabled,
            "rows": [self._row_to_state_dict(row) for row in self.rows],
        }
        STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _row_to_state_dict(self, row: RelayRow) -> Dict[str, Any]:
        return {
            "id": row.row_id,
            "enabled": row.enabled,
            "name": row.name,
            "ied_key": row.ied_key,
            "relay_type": row.relay_type,
            "ip": row.ip,
            "port": row.port,
            "analogs": self._ordered_entries(row.analogs),
            "words": self._ordered_entries(row.words),
            "bools": self._ordered_entries(row.bools),
            "analog_random_ranges": self._ordered_range_entries(row.analog_random_ranges),
            "word_random_ranges": self._ordered_range_entries(row.word_random_ranges),
        }

    def _row_to_api_dict(self, row: RelayRow, position: int) -> Dict[str, Any]:
        running = row.process is not None and row.process.poll() is None
        return {
            "id": row.row_id,
            "position": position,
            "enabled": row.enabled,
            "name": row.name,
            "ied_key": row.ied_key,
            "relay_type": row.relay_type,
            "ip": row.ip,
            "port": row.port,
            "status": row.status_text,
            "status_tone": row.status_tone,
            "running": running,
            "ip_alias_present": row.ip in self.adapter_ipv4_addresses,
            "analogs": self._ordered_entries(row.analogs),
            "words": self._ordered_entries(row.words),
            "bools": self._ordered_entries(row.bools),
            "analog_random_ranges": self._ordered_range_entries(row.analog_random_ranges),
            "word_random_ranges": self._ordered_range_entries(row.word_random_ranges),
        }

    def _refresh_adapter_ipv4_addresses_unlocked(self, force: bool = False) -> None:
        current_ms = now_ms()
        if not force and (current_ms - self.adapter_ip_refresh_ms) < 3000:
            return
        self.adapter_ipv4_addresses = list_adapter_ipv4_addresses(self.network_adapter)
        self.adapter_ip_refresh_ms = current_ms

    def _cleanup_stale_runtime_files_unlocked(self, log: bool) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        expected_paths = {STATE_FILE.resolve()}
        for row in self.rows:
            for path in self._runtime_paths_unlocked(row):
                expected_paths.add(path.resolve())

        removed_count = 0
        for candidate in RUNTIME_DIR.iterdir():
            if candidate.is_dir():
                continue
            if candidate.resolve() in expected_paths:
                continue
            if not candidate.name.endswith(("_config.json", "_values.json", "_server.log")):
                continue
            try:
                candidate.unlink()
                removed_count += 1
            except OSError:
                continue

        if removed_count > 0 and log:
            self._log_unlocked(f"Removed {removed_count} stale runtime files")

    @staticmethod
    def _ordered_entries(mapping: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [{"tag": tag, "value": value} for tag, value in mapping.items()]

    @staticmethod
    def _ordered_range_entries(mapping: Dict[str, Tuple[Any, Any]]) -> List[Dict[str, Any]]:
      return [{"tag": tag, "min": bounds[0], "max": bounds[1]} for tag, bounds in mapping.items()]

    def _coerce_row_from_payload_unlocked(self, payload: Any) -> RelayRow:
        if not isinstance(payload, dict):
            payload = {}
        relay_type = normalize_relay_type(payload.get("relay_type", payload.get("type", "REF615")))
        row_id = int(payload.get("id") or self.next_row_id)
        self.next_row_id = max(self.next_row_id, row_id + 1)
        name = str(payload.get("name", "")).strip() or self._suggest_name_unlocked(relay_type)
        ied_key = str(payload.get("ied_key", "")).strip() or default_ied_key_for(name)
        ip = str(payload.get("ip", "")).strip() or self._suggest_ip_unlocked()
        port = coerce_port(payload.get("port", DEFAULT_PORT))
        analogs = self._coerce_entries(payload.get("analogs"), "analogs", relay_type)
        words = self._coerce_entries(payload.get("words"), "words", relay_type)
        bools = self._coerce_entries(payload.get("bools"), "bools", relay_type)
        analog_random_ranges = self._coerce_range_entries(
          payload.get("analog_random_ranges"),
          "analogs",
          list(analogs.keys()),
        )
        word_random_ranges = self._coerce_range_entries(
          payload.get("word_random_ranges"),
          "words",
          list(words.keys()),
        )
        return RelayRow(
            row_id=row_id,
            enabled=parse_bool(payload.get("enabled", True), True),
            name=name,
            ied_key=ied_key,
            relay_type=relay_type,
            ip=ip,
            port=port,
            analogs=analogs,
            words=words,
            bools=bools,
            analog_random_ranges=analog_random_ranges,
            word_random_ranges=word_random_ranges,
        )

    def _new_row_unlocked(self, relay_type: str) -> RelayRow:
        analogs = build_default_analogs(relay_type)
        words = build_default_words()
        row = RelayRow(
            row_id=self.next_row_id,
            enabled=True,
            name=self._suggest_name_unlocked(relay_type),
            ied_key="",
            relay_type=relay_type,
            ip=self._suggest_ip_unlocked(),
            port=DEFAULT_PORT,
            analogs=analogs,
            words=words,
            bools=build_default_bools(),
            analog_random_ranges=self._coerce_range_entries(None, "analogs", list(analogs.keys())),
            word_random_ranges=self._coerce_range_entries(None, "words", list(words.keys())),
        )
        row.ied_key = default_ied_key_for(row.name)
        self.next_row_id += 1
        return row

    def _apply_row_payload_unlocked(self, row: RelayRow, payload: Dict[str, Any]) -> None:
        relay_type = normalize_relay_type(payload.get("relay_type", row.relay_type))
        previous_relay_type = row.relay_type
        row.enabled = parse_bool(payload.get("enabled", row.enabled), row.enabled)
        row.name = str(payload.get("name", row.name)).strip() or row.name
        row.ied_key = str(payload.get("ied_key", row.ied_key)).strip() or default_ied_key_for(row.name)
        row.relay_type = relay_type
        row.ip = str(payload.get("ip", row.ip)).strip() or row.ip
        row.port = coerce_port(payload.get("port", row.port), row.port)

        if "analogs" in payload:
            row.analogs = self._coerce_entries(payload.get("analogs"), "analogs", relay_type)
        elif relay_type != previous_relay_type:
            row.analogs = build_default_analogs(relay_type)

        if "words" in payload:
            row.words = self._coerce_entries(payload.get("words"), "words", relay_type)

        if "bools" in payload:
            row.bools = self._coerce_entries(payload.get("bools"), "bools", relay_type)

        row.analog_random_ranges = self._coerce_range_entries(
            payload.get("analog_random_ranges"),
            "analogs",
            list(row.analogs.keys()),
            row.analog_random_ranges,
        )
        row.word_random_ranges = self._coerce_range_entries(
            payload.get("word_random_ranges"),
            "words",
            list(row.words.keys()),
            row.word_random_ranges,
        )

    def _coerce_entries(self, payload: Any, category: str, relay_type: str) -> Dict[str, Any]:
        if payload is None:
            if category == "analogs":
                return build_default_analogs(relay_type)
            if category == "words":
                return build_default_words()
            return build_default_bools()

        result: Dict[str, Any] = {}
        for entry in payload if isinstance(payload, list) else []:
            if not isinstance(entry, dict):
                continue
            tag = str(entry.get("tag", "")).strip()
            if not tag or tag in result:
                continue
            if category == "analogs":
                try:
                    value = float(entry.get("value", analog_default_for(tag)))
                except (TypeError, ValueError):
                    value = analog_default_for(tag)
            elif category == "words":
                try:
                    value = int(entry.get("value", word_default_for(tag)))
                except (TypeError, ValueError):
                    value = word_default_for(tag)
            else:
                value = parse_bool(entry.get("value", bool_default_for(tag)), bool_default_for(tag))
            result[tag] = value
        return result

    def _coerce_range_entries(
        self,
        payload: Any,
        category: str,
        tags: List[str],
        existing: Optional[Dict[str, Tuple[Any, Any]]] = None,
    ) -> Dict[str, Tuple[Any, Any]]:
        parsed: Dict[str, Tuple[Any, Any]] = {}
        allowed_tags = set(tags)
        for entry in payload if isinstance(payload, list) else []:
            if not isinstance(entry, dict):
                continue
            tag = str(entry.get("tag", "")).strip()
            if not tag or tag not in allowed_tags or tag in parsed:
                continue
            parsed[tag] = self._normalize_range_bounds(entry.get("min"), entry.get("max"), category, tag)

        normalized: Dict[str, Tuple[Any, Any]] = {}
        existing = existing or {}
        for tag in tags:
            if tag in parsed:
                normalized[tag] = parsed[tag]
            elif tag in existing:
                current_min, current_max = existing[tag]
                normalized[tag] = self._normalize_range_bounds(current_min, current_max, category, tag)
            else:
                normalized[tag] = self._default_range_for(tag, category)
        return normalized

    def _default_range_for(self, tag: str, category: str) -> Tuple[Any, Any]:
        if category == "analogs":
            return ANALOG_RANDOM_RANGES.get(tag, (0.0, 100.0))
        return WORD_RANDOM_RANGES.get(tag, (0, 10))

    def _normalize_range_bounds(self, minimum: Any, maximum: Any, category: str, tag: str) -> Tuple[Any, Any]:
        default_min, default_max = self._default_range_for(tag, category)
        try:
            if category == "words":
                low = int(minimum)
                high = int(maximum)
            else:
                low = float(minimum)
                high = float(maximum)
        except (TypeError, ValueError):
            low, high = default_min, default_max
        if low > high:
            low, high = high, low
        return low, high

    def _suggest_name_unlocked(self, relay_type: str) -> str:
        relay_type = normalize_relay_type(relay_type)
        prefix = f"{relay_type}_SIM_"
        used = {row.name for row in self.rows}
        candidate = 1
        while True:
            name = f"{prefix}{candidate:02d}"
            if name not in used:
                return name
            candidate += 1

    def _suggest_ip_unlocked(self) -> str:
        last_octets = []
        for row in self.rows:
            parts = row.ip.split(".")
            if len(parts) != 4:
                continue
            try:
                last_octets.append(int(parts[3]))
            except ValueError:
                continue
        next_octet = max(last_octets, default=4) + 1
        return f"10.206.204.{next_octet}"

    def _require_row_unlocked(self, row_id: int) -> RelayRow:
        for row in self.rows:
            if row.row_id == row_id:
                return row
        raise KeyError(f"Relay row {row_id} was not found")

    def _runtime_paths_unlocked(self, row: RelayRow) -> Tuple[Path, Path, Path]:
        stem = safe_name(row.name)
        return (
            RUNTIME_DIR / f"{stem}_config.json",
            RUNTIME_DIR / f"{stem}_values.json",
            RUNTIME_DIR / f"{stem}_server.log",
        )

    def _values_payload_unlocked(self, row: RelayRow) -> Dict[str, Any]:
        return {
            "analogs": {tag: float(value) for tag, value in row.analogs.items()},
            "bools": {tag: bool(value) for tag, value in row.bools.items()},
            "words": {tag: int(value) for tag, value in row.words.items()},
            "updated_unix_ms": now_ms(),
        }

    def _config_payload_unlocked(self, row: RelayRow, values_path: Path) -> Dict[str, Any]:
        return {
            "enabled": bool(row.enabled),
        "display_name": row.name,
        "ied_name": row.ied_key,
            "relay_type": row.relay_type,
            "bind_ip": row.ip,
            "port": row.port,
            "values_path": to_relative_posix(values_path),
            "analog_tags": list(row.analogs.keys()),
            "word_tags": list(row.words.keys()),
            "bool_tags": list(row.bools.keys()),
            "mms_server_executable": self.exe_path,
            "updated_unix_ms": now_ms(),
        }

    def _write_row_runtime_files_unlocked(self, row: RelayRow, log: bool) -> Tuple[Path, Path]:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        config_path, values_path, _log_path = self._runtime_paths_unlocked(row)
        config_payload = self._config_payload_unlocked(row, values_path)
        values_payload = self._values_payload_unlocked(row)
        config_path.write_text(json.dumps(config_payload, indent=2), encoding="utf-8")
        values_path.write_text(json.dumps(values_payload, indent=2), encoding="utf-8")
        if log:
            self._log_unlocked(f"Wrote {to_relative_posix(config_path)} and {to_relative_posix(values_path)}")
        return config_path, values_path

    def _write_all_runtime_files_unlocked(self, log: bool) -> None:
        for row in self.rows:
            self._write_row_runtime_files_unlocked(row, log=log)

    def _resolved_executable_unlocked(self) -> Tuple[str, Path]:
        raw_path = self.exe_path.strip() or DEFAULT_EXE_FIELD
        executable = Path(raw_path)
        if executable.is_absolute():
            return raw_path, executable

        candidates = [(BASE_DIR / executable).resolve()]
        if getattr(sys, "frozen", False):
            candidates.append((BASE_DIR / "_internal" / executable).resolve())

        for candidate in candidates:
            if candidate.exists():
                return raw_path, candidate

        return raw_path, candidates[0]

    def _start_row_unlocked(self, row: RelayRow) -> None:
        if row.process is not None and row.process.poll() is None:
            self._set_status_unlocked(row, "running", "running")
            self._log_unlocked(f"{row.name} is already running")
            return

        _config_path, values_path = self._write_row_runtime_files_unlocked(row, log=False)
        values_arg = to_relative_posix(values_path)
        raw_exe_path, executable = self._resolved_executable_unlocked()
        if not executable.exists():
            self._set_status_unlocked(row, "missing exe", "warning")
            self._log_unlocked(f"{row.name}: missing executable at {raw_exe_path}")
            return

        _config_path, _values_path, log_path = self._runtime_paths_unlocked(row)
        log_handle: Optional[IO[str]] = None
        try:
            log_handle = log_path.open("a", encoding="utf-8")
            log_handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting {row.name}\n")
            log_handle.flush()
            command = [
                str(executable),
                "--ied-name",
              row.ied_key,
                "--type",
                row.relay_type,
                "--bind",
                row.ip,
                "--port",
                str(row.port),
                "--values",
                values_arg,
            ]
            row.process = subprocess.Popen(
                command,
                cwd=str(BASE_DIR),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
            row.process_log = log_handle
            self._set_status_unlocked(row, "running", "running")
            self._log_unlocked(f"Started {row.name} ({row.ied_key}) on {row.ip}:{row.port}")
        except Exception as exc:
            if log_handle is not None:
                log_handle.close()
            row.process = None
            row.process_log = None
            self._set_status_unlocked(row, "start failed", "error")
            self._log_unlocked(f"{row.name}: failed to start process ({exc})")

    def _stop_row_unlocked(self, row: RelayRow, log: bool) -> None:
        if row.process is None:
            self._set_status_unlocked(row, "stopped", "stopped")
            if log:
                self._log_unlocked(f"{row.name}: no running process")
            return

        process = row.process
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        except Exception as exc:
            self._set_status_unlocked(row, "stop failed", "error")
            if log:
                self._log_unlocked(f"{row.name}: failed to stop process ({exc})")
            return
        finally:
            row.process = None
            if row.process_log is not None:
                row.process_log.close()
                row.process_log = None
        self._set_status_unlocked(row, "stopped", "stopped")
        if log:
            self._log_unlocked(f"Stopped {row.name}")

    def _randomize_row_unlocked(self, row: RelayRow) -> None:
        row.analogs = {
            tag: round(random.uniform(*row.analog_random_ranges.get(tag, self._default_range_for(tag, "analogs"))), 3)
            for tag in row.analogs.keys()
        }
        row.words = {
            tag: random.randint(*row.word_random_ranges.get(tag, self._default_range_for(tag, "words")))
            for tag in row.words.keys()
        }
        row.bools = {tag: bool_random_for(tag) for tag in row.bools.keys()}

    def _generate_ip_alias_script_unlocked(self, log: bool) -> None:
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        script_path = TOOLS_DIR / "add_ip_aliases.ps1"
        script_path.write_text(
            render_ip_alias_script_for_adapter(self.network_adapter, [row.ip for row in self.rows]),
            encoding="utf-8",
        )
        if log:
            self._log_unlocked(f"Generated {to_relative_posix(script_path)} for {self.network_adapter}")

    def _poll_processes_unlocked(self) -> None:
        for row in self.rows:
            if row.process is None:
                continue
            return_code = row.process.poll()
            if return_code is None:
                continue
            if row.process_log is not None:
                row.process_log.close()
                row.process_log = None
            row.process = None
            if return_code == 0:
                self._set_status_unlocked(row, "exited (0)", "stopped")
            else:
                self._set_status_unlocked(row, f"exited ({return_code})", "warning")
            self._log_unlocked(f"{row.name}: process exited with code {return_code}")

    def _set_status_unlocked(self, row: RelayRow, text: str, tone: str) -> None:
        row.status_text = text
        row.status_tone = tone if tone in STATUS_TONES else "idle"

    def _log_unlocked(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self.logs.append(line)
        self.activity = message
        print(line, flush=True)


def build_app_js() -> str:
    defaults = {
        "relayTypes": list(RELAY_ANALOG_TAGS.keys()),
        "defaultAnalogTags": RELAY_ANALOG_TAGS,
        "defaultWordTags": COMMON_WORD_TAGS,
        "defaultBoolTags": COMMON_BOOL_TAGS,
        "defaultAnalogValues": ANALOG_DEFAULTS,
        "defaultWordValues": WORD_DEFAULTS,
        "defaultBoolValues": BOOL_DEFAULTS,
    }
    return (
        "const UI_DEFAULTS = " + json.dumps(defaults) + ";\n"
        + r'''
const store = {
  snapshot: null,
  openRows: new Set(),
  bannerTone: 'info',
  bannerText: 'Launcher is ready.',
  randomDialogRowId: null,
  globalRandomDialogOpen: false,
  pollHandle: null,
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function hasOpenDialog() {
  return store.randomDialogRowId !== null || store.globalRandomDialogOpen;
}

function isEditing() {
  const active = document.activeElement;
  return !!active && active.matches('input, textarea, select');
}

function shouldPauseRefresh() {
  return isEditing() || hasOpenDialog();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || 'Request failed');
  }
  return payload;
}

function defaultEntries(relayType, kind) {
  if (kind === 'analogs') {
    return (UI_DEFAULTS.defaultAnalogTags[relayType] || []).map((tag) => ({
      tag,
      value: UI_DEFAULTS.defaultAnalogValues[tag] ?? 0,
    }));
  }
  if (kind === 'words') {
    return UI_DEFAULTS.defaultWordTags.map((tag) => ({
      tag,
      value: UI_DEFAULTS.defaultWordValues[tag] ?? 0,
    }));
  }
  return UI_DEFAULTS.defaultBoolTags.map((tag) => ({
    tag,
    value: Boolean(UI_DEFAULTS.defaultBoolValues[tag]),
  }));
}

function renderTagRows(entries, kind) {
  if (!entries.length) {
    return '<div class="muted">No tags configured.</div>';
  }
  return entries.map((entry) => {
    const tag = escapeHtml(entry.tag);
    if (kind === 'bools') {
      return `
        <div class="tag-row bool" data-kind="${kind}">
          <input class="tag-name" type="text" value="${tag}" placeholder="Tag name">
          <label class="bool-wrap"><input class="tag-value" type="checkbox" ${entry.value ? 'checked' : ''}> Value</label>
          <button type="button" class="secondary" data-action="remove-tag">Remove</button>
        </div>
      `;
    }
    const inputType = kind === 'words' ? 'number' : 'number';
    const step = kind === 'words' ? '1' : '0.001';
    return `
      <div class="tag-row" data-kind="${kind}">
        <input class="tag-name" type="text" value="${tag}" placeholder="Tag name">
        <input class="tag-value" type="${inputType}" step="${step}" value="${escapeHtml(entry.value)}">
        <button type="button" class="secondary" data-action="remove-tag">Remove</button>
      </div>
    `;
  }).join('');
}

function renderRandomRangeRows(entries, kind) {
  if (!entries.length) {
    return '<div class="muted">No configurable numeric tags.</div>';
  }
  const step = kind === 'words' ? '1' : '0.001';
  return entries.map((entry) => `
    <div class="range-row" data-kind="${kind}">
      <div class="range-label">${escapeHtml(entry.tag)}</div>
      <input class="range-min" type="number" step="${step}" value="${escapeHtml(entry.min)}">
      <input class="range-max" type="number" step="${step}" value="${escapeHtml(entry.max)}">
    </div>
  `).join('');
}

function renderRandomDialog(snapshot) {
  const row = snapshot.rows.find((candidate) => candidate.id === store.randomDialogRowId);
  if (!row) {
    return '';
  }
  return `
    <div class="modal-overlay">
      <section class="modal-card" aria-modal="true" aria-labelledby="random-settings-title" role="dialog">
        <h3 id="random-settings-title">Random settings for ${escapeHtml(row.name)}</h3>
        <p class="help-line">Set the random min/max range for tags currently used by this relay. For example, voltage can be set to 380-420.</p>
        <form id="random-settings-form" data-row-id="${row.id}">
          <section class="tag-section" data-kind="analogs">
            <h4>Analog ranges</h4>
            <p class="help-line">Min and max values used when analogs are randomized.</p>
            <div class="tag-list">${renderRandomRangeRows(row.analog_random_ranges, 'analogs')}</div>
          </section>
          <section class="tag-section" data-kind="words" style="margin-top:16px;">
            <h4>Word ranges</h4>
            <p class="help-line">Integer ranges used when word tags are randomized.</p>
            <div class="tag-list">${renderRandomRangeRows(row.word_random_ranges, 'words')}</div>
          </section>
          <div class="settings-actions" style="margin-top:16px;">
            <button type="submit">Save random ranges</button>
            <button type="button" class="warning" data-action="randomize-row" data-row-id="${row.id}">Randomize now</button>
            <button type="button" class="secondary" data-action="toggle-auto-random">${snapshot.auto_random_enabled ? 'Stop auto random' : 'Start auto random'}</button>
            <button type="button" class="secondary" data-action="close-random-dialog">Close</button>
          </div>
        </form>
      </section>
    </div>
  `;
}

function collectUnionRanges(snapshot, key) {
  const seen = new Map();
  snapshot.rows.forEach((row) => {
    row[key].forEach((entry) => {
      if (!seen.has(entry.tag)) {
        seen.set(entry.tag, { tag: entry.tag, min: entry.min, max: entry.max });
      }
    });
  });
  return Array.from(seen.values());
}

function renderGlobalRandomDialog(snapshot) {
  if (!store.globalRandomDialogOpen) {
    return '';
  }
  const analogRanges = collectUnionRanges(snapshot, 'analog_random_ranges');
  const wordRanges = collectUnionRanges(snapshot, 'word_random_ranges');
  return `
    <div class="modal-overlay">
      <section class="modal-card" aria-modal="true" aria-labelledby="global-random-settings-title" role="dialog">
        <h3 id="global-random-settings-title">Global random settings</h3>
        <p class="help-line">Apply the same random min/max ranges to all relays or only selected ones. Only tags that exist in each relay are updated.</p>
        <form id="global-random-settings-form">
          <section class="tag-section">
            <h4>Target relays</h4>
            <div class="toolbar">
              <button type="button" class="secondary" data-action="global-select-all">Select all</button>
              <button type="button" class="secondary" data-action="global-select-enabled">Select enabled</button>
              <button type="button" class="secondary" data-action="global-clear-selection">Clear selection</button>
            </div>
            <div class="selection-list">
              ${snapshot.rows.map((row) => `
                <label class="selection-item">
                  <input type="checkbox" name="selected_rows" value="${row.id}" ${row.enabled ? 'checked' : ''}>
                  <span>${escapeHtml(row.name)} (${escapeHtml(row.relay_type)})</span>
                </label>
              `).join('')}
            </div>
          </section>
          <section class="tag-section" data-kind="analogs" style="margin-top:16px;">
            <h4>Analog ranges</h4>
            <div class="tag-list">${renderRandomRangeRows(analogRanges, 'analogs')}</div>
          </section>
          <section class="tag-section" data-kind="words" style="margin-top:16px;">
            <h4>Word ranges</h4>
            <div class="tag-list">${renderRandomRangeRows(wordRanges, 'words')}</div>
          </section>
          <div class="settings-actions" style="margin-top:16px;">
            <button type="submit">Apply to selected relays</button>
            <button type="button" class="secondary" data-action="close-global-random-dialog">Close</button>
          </div>
        </form>
      </section>
    </div>
  `;
}

function rowCard(row) {
  const open = store.openRows.has(row.id) ? 'open' : '';
  const statusClass = escapeHtml(row.status_tone || 'idle');
  const iedKeyMeta = row.ied_key && row.ied_key !== row.name
    ? ` · IED key ${escapeHtml(row.ied_key)}`
    : '';
  const aliasWarning = row.ip_alias_present
    ? ''
    : `<div class="help-line relay-warning">IP alias ${escapeHtml(row.ip)} is missing on ${escapeHtml(store.snapshot.network_adapter || 'selected adapter')}</div>`;
  return `
    <article class="relay-card ${statusClass}">
      <div class="relay-head">
        <div>
          <h3>${escapeHtml(row.name)}</h3>
          <div class="relay-meta">#${row.position} · ${escapeHtml(row.relay_type)} · ${escapeHtml(row.ip)}:${escapeHtml(row.port)}${iedKeyMeta}</div>
          ${aliasWarning}
        </div>
        <div class="status-pill ${statusClass}">${escapeHtml(row.status)}</div>
      </div>

      <div class="card-actions" style="margin-top:14px; position: relative; z-index: 1;">
        <button type="button" class="secondary" data-action="edit-row" data-row-id="${row.id}">${store.openRows.has(row.id) ? 'Close' : 'Edit'}</button>
        <button type="button" data-action="start-row" data-row-id="${row.id}">Start</button>
        <button type="button" class="secondary" data-action="stop-row" data-row-id="${row.id}">Stop</button>
      </div>

      <details data-row-id="${row.id}" ${open}>
        <summary>Relay settings</summary>
        <form class="relay-form" data-row-id="${row.id}">
          <div class="relay-fields">
            <div class="field">
              <label>Name</label>
              <input name="name" type="text" value="${escapeHtml(row.name)}" data-previous-value="${escapeHtml(row.name)}">
            </div>
            <div class="field">
              <label>IED key</label>
              <input name="ied_key" type="text" value="${escapeHtml(row.ied_key || row.name)}">
            </div>
            <div class="field">
              <label>Relay type</label>
              <select name="relay_type" class="relay-type-select">
                ${UI_DEFAULTS.relayTypes.map((value) => `<option value="${value}" ${value === row.relay_type ? 'selected' : ''}>${value}</option>`).join('')}
              </select>
            </div>
            <div class="field">
              <label>IP address</label>
              <input name="ip" type="text" value="${escapeHtml(row.ip)}">
            </div>
            <div class="field">
              <label>Port</label>
              <input name="port" type="number" min="1" max="65535" value="${escapeHtml(row.port)}">
            </div>
            <label class="relay-check"><input name="enabled" type="checkbox" ${row.enabled ? 'checked' : ''}> Enabled</label>
          </div>

          <div class="settings-actions">
            <button type="submit">Save relay</button>
            <button type="button" class="warning" data-action="randomize-row" data-row-id="${row.id}">Randomize now</button>
            <button type="button" class="secondary" data-action="open-random-settings" data-row-id="${row.id}">Random settings</button>
            <button type="button" class="danger" data-action="remove-row" data-row-id="${row.id}">Remove relay</button>
          </div>

          <section class="tag-section" data-kind="analogs">
            <h4>Analog tags</h4>
            <p class="help-line">Editable list of analog tags and their current values.</p>
            <div class="tag-list">${renderTagRows(row.analogs, 'analogs')}</div>
            <div class="tag-actions" style="margin-top:10px;">
              <button type="button" class="secondary" data-action="add-tag" data-kind="analogs">Add analog tag</button>
              <button type="button" class="secondary" data-action="reset-default-tags" data-kind="analogs">Restore type defaults</button>
            </div>
          </section>

          <section class="tag-section" data-kind="words">
            <h4>Word tags</h4>
            <p class="help-line">Integer tags exposed to the simulator.</p>
            <div class="tag-list">${renderTagRows(row.words, 'words')}</div>
            <div class="tag-actions" style="margin-top:10px;">
              <button type="button" class="secondary" data-action="add-tag" data-kind="words">Add word tag</button>
              <button type="button" class="secondary" data-action="reset-default-tags" data-kind="words">Restore common defaults</button>
            </div>
          </section>

          <section class="tag-section" data-kind="bools">
            <h4>Bool tags</h4>
            <p class="help-line">Boolean indication and alarm tags.</p>
            <div class="tag-list">${renderTagRows(row.bools, 'bools')}</div>
            <div class="tag-actions" style="margin-top:10px;">
              <button type="button" class="secondary" data-action="add-tag" data-kind="bools">Add bool tag</button>
              <button type="button" class="secondary" data-action="reset-default-tags" data-kind="bools">Restore common defaults</button>
            </div>
          </section>

        </form>
      </details>
    </article>
  `;
}

function renderNetworkAdapterOptions(snapshot) {
  if (!snapshot.network_adapter_options.length) {
    return `<option value="${escapeHtml(snapshot.network_adapter)}">${escapeHtml(snapshot.network_adapter || 'No adapters found')}</option>`;
  }
  return snapshot.network_adapter_options.map((adapter) => {
    const labelParts = [adapter.name];
    if (adapter.status) {
      labelParts.push(adapter.status);
    }
    if (adapter.description) {
      labelParts.push(adapter.description);
    }
    const label = labelParts.join(' · ');
    return `<option value="${escapeHtml(adapter.name)}" ${adapter.name === snapshot.network_adapter ? 'selected' : ''}>${escapeHtml(label)}</option>`;
  }).join('');
}

function serializeLauncherSettings() {
  const adapterSelect = document.querySelector('#network-adapter-select');
  return {
    network_adapter: adapterSelect ? adapterSelect.value : '',
  };
}

function render(snapshot) {
  store.snapshot = snapshot;
  const app = document.querySelector('#app');
  const rowsHtml = snapshot.rows.length
    ? snapshot.rows.map((row) => rowCard(row)).join('')
    : '<div class="empty-state">No relay rows. Add one from the controls above.</div>';

  app.innerHTML = `
    <main class="shell">
      <section class="hero">
        <div class="hero-card">
          <p class="muted">Browser-based launcher for local IEC 61850 MMS simulator processes.</p>
          <h1>IED Simulator Control Room</h1>
          <p>${escapeHtml(snapshot.activity)}</p>
          <p class="help-line">Leave this service running and revisit <strong>${escapeHtml(snapshot.browser_url)}</strong> whenever needed.</p>
        </div>
        <div class="hero-grid">
          <div class="stat"><span class="stat-label">Relays</span><span class="stat-value">${snapshot.stats.total}</span></div>
          <div class="stat"><span class="stat-label">Enabled</span><span class="stat-value">${snapshot.stats.enabled}</span></div>
          <div class="stat"><span class="stat-label">Running</span><span class="stat-value">${snapshot.stats.running}</span></div>
          <div class="stat"><span class="stat-label">Auto Random</span><span class="stat-value">${snapshot.auto_random_enabled ? 'ON' : 'OFF'}</span></div>
        </div>
      </section>

      <section class="panel">
        <div class="layout">
          <div class="toolbar">
            <div class="settings-actions">
              <button type="button" data-action="start-all">Start all enabled</button>
              <button type="button" class="secondary" data-action="stop-all">Stop all</button>
              <button type="button" class="secondary" data-action="toggle-auto-random">${snapshot.auto_random_enabled ? 'Stop auto random' : 'Start auto random'}</button>
              <button type="button" class="secondary" data-action="open-global-random-settings">Global random settings</button>
              <button type="button" class="danger" data-action="shutdown-service">Shutdown service</button>
            </div>
          </div>
          <div class="toolbar">
            <div class="field" style="max-width:420px;">
              <label>Network adapter</label>
              <select id="network-adapter-select">
                ${renderNetworkAdapterOptions(snapshot)}
              </select>
            </div>
            <div class="settings-actions">
              <button type="button" class="secondary" data-action="save-launcher-settings">Save launcher settings</button>
              <button type="button" class="secondary" data-action="refresh-network-adapters">Refresh</button>
              <button type="button" class="secondary" data-action="prepare-network">Prepare network</button>
            </div>
            <div class="field" style="max-width:260px;">
              <label>Add relay type</label>
              <select id="new-relay-type">
                ${UI_DEFAULTS.relayTypes.map((value) => `<option value="${value}">${value}</option>`).join('')}
              </select>
            </div>
            <div class="settings-actions">
              <button type="button" data-action="add-row">Add relay row</button>
            </div>
          </div>
        </div>
      </section>

      <div class="status-banner ${escapeHtml(store.bannerTone)}">${escapeHtml(store.bannerText)}</div>

      <section class="relay-grid">
        ${rowsHtml}
      </section>

      <section class="log-panel">
        <h3>Launcher log</h3>
        <pre>${escapeHtml(snapshot.log_lines.join('\n'))}</pre>
      </section>
    </main>

    ${renderRandomDialog(snapshot)}
    ${renderGlobalRandomDialog(snapshot)}
  `;
}

function closeOpenDialog() {
  if (store.randomDialogRowId !== null) {
    store.randomDialogRowId = null;
  }
  if (store.globalRandomDialogOpen) {
    store.globalRandomDialogOpen = false;
  }
}

function renderServiceStopped() {
  const app = document.querySelector('#app');
  app.innerHTML = `
    <main class="shell">
      <section class="hero-card">
        <p class="muted">Launcher service has been stopped.</p>
        <h1>Service stopped</h1>
        <p>You can close this browser tab or start the launcher again from the application.</p>
      </section>
    </main>
  `;
}

function setBanner(text, tone = 'info') {
  store.bannerText = text;
  store.bannerTone = tone;
  if (store.snapshot && !isEditing()) {
    render(store.snapshot);
  }
}

function appendTagRow(listElement, kind, entry = { tag: '', value: kind === 'bools' ? false : 0 }) {
  const wrapper = document.createElement('div');
  wrapper.className = kind === 'bools' ? 'tag-row bool' : 'tag-row';
  wrapper.dataset.kind = kind;
  if (kind === 'bools') {
    wrapper.innerHTML = `
      <input class="tag-name" type="text" value="${escapeHtml(entry.tag)}" placeholder="Tag name">
      <label class="bool-wrap"><input class="tag-value" type="checkbox" ${entry.value ? 'checked' : ''}> Value</label>
      <button type="button" class="secondary" data-action="remove-tag">Remove</button>
    `;
  } else {
    wrapper.innerHTML = `
      <input class="tag-name" type="text" value="${escapeHtml(entry.tag)}" placeholder="Tag name">
      <input class="tag-value" type="number" step="${kind === 'words' ? '1' : '0.001'}" value="${escapeHtml(entry.value)}">
      <button type="button" class="secondary" data-action="remove-tag">Remove</button>
    `;
  }
  listElement.appendChild(wrapper);
}

function serializeEntries(section) {
  const kind = section.dataset.kind;
  return Array.from(section.querySelectorAll('.tag-row')).map((row) => {
    const tag = row.querySelector('.tag-name').value.trim();
    if (!tag) {
      return null;
    }
    const valueField = row.querySelector('.tag-value');
    let value = 0;
    if (kind === 'bools') {
      value = valueField.checked;
    } else if (kind === 'words') {
      value = Number.parseInt(valueField.value || '0', 10);
      if (Number.isNaN(value)) {
        value = 0;
      }
    } else {
      value = Number.parseFloat(valueField.value || '0');
      if (Number.isNaN(value)) {
        value = 0;
      }
    }
    return { tag, value };
  }).filter(Boolean);
}

function serializeRowForm(form) {
  return {
    name: form.elements.name.value.trim(),
    ied_key: form.elements.ied_key.value.trim(),
    relay_type: form.elements.relay_type.value,
    ip: form.elements.ip.value.trim(),
    port: Number.parseInt(form.elements.port.value || '102', 10),
    enabled: form.elements.enabled.checked,
    analogs: serializeEntries(form.querySelector('[data-kind="analogs"]')),
    words: serializeEntries(form.querySelector('[data-kind="words"]')),
    bools: serializeEntries(form.querySelector('[data-kind="bools"]')),
  };
}

function rememberDetailsState() {
  store.openRows = new Set(
    Array.from(document.querySelectorAll('details[data-row-id][open]')).map((node) => Number(node.dataset.rowId))
  );
}

function setRowDetailsOpen(rowId, shouldOpen) {
  const details = document.querySelector(`details[data-row-id="${rowId}"]`);
  const toggleButton = document.querySelector(`button[data-action="edit-row"][data-row-id="${rowId}"]`);
  if (!details) {
    return;
  }
  details.open = shouldOpen;
  if (shouldOpen) {
    store.openRows.add(rowId);
  } else {
    store.openRows.delete(rowId);
  }
  if (toggleButton) {
    toggleButton.textContent = shouldOpen ? 'Close' : 'Edit';
  }
}

function serializeRangeEntries(section) {
  const kind = section.dataset.kind;
  return Array.from(section.querySelectorAll('.range-row')).map((row) => {
    const tag = row.querySelector('.range-label').textContent.trim();
    const minimumField = row.querySelector('.range-min');
    const maximumField = row.querySelector('.range-max');
    let minimum = kind === 'words' ? Number.parseInt(minimumField.value || '0', 10) : Number.parseFloat(minimumField.value || '0');
    let maximum = kind === 'words' ? Number.parseInt(maximumField.value || '0', 10) : Number.parseFloat(maximumField.value || '0');
    if (Number.isNaN(minimum)) {
      minimum = 0;
    }
    if (Number.isNaN(maximum)) {
      maximum = 0;
    }
    return { tag, min: minimum, max: maximum };
  });
}

function serializeRandomSettingsForm(form) {
  return {
    analog_random_ranges: serializeRangeEntries(form.querySelector('[data-kind="analogs"]')),
    word_random_ranges: serializeRangeEntries(form.querySelector('[data-kind="words"]')),
  };
}

function buildRangeMap(entries) {
  return new Map(entries.map((entry) => [entry.tag, entry]));
}

async function applyGlobalRandomSettings(form) {
  const selectedRowIds = Array.from(form.querySelectorAll('input[name="selected_rows"]:checked')).map((node) => Number(node.value));
  if (!selectedRowIds.length) {
    throw new Error('Select at least one relay');
  }

  const analogOverrides = buildRangeMap(serializeRangeEntries(form.querySelector('[data-kind="analogs"]')));
  const wordOverrides = buildRangeMap(serializeRangeEntries(form.querySelector('[data-kind="words"]')));
  let latestState = null;

  for (const rowId of selectedRowIds) {
    const row = store.snapshot.rows.find((candidate) => candidate.id === rowId);
    if (!row) {
      continue;
    }
    const payload = {
      analog_random_ranges: row.analog_random_ranges.map((entry) => analogOverrides.get(entry.tag) || entry),
      word_random_ranges: row.word_random_ranges.map((entry) => wordOverrides.get(entry.tag) || entry),
    };
    const response = await api(`/api/rows/${rowId}/random-settings`, { body: payload });
    latestState = response.state;
    store.snapshot = response.state;
  }

  return latestState || store.snapshot;
}

function setGlobalSelection(mode) {
  const dialog = document.querySelector('#global-random-settings-form');
  if (!dialog || !store.snapshot) {
    return;
  }
  const enabledIds = new Set(store.snapshot.rows.filter((row) => row.enabled).map((row) => row.id));
  dialog.querySelectorAll('input[name="selected_rows"]').forEach((checkbox) => {
    if (mode === 'all') {
      checkbox.checked = true;
    } else if (mode === 'enabled') {
      checkbox.checked = enabledIds.has(Number(checkbox.value));
    } else {
      checkbox.checked = false;
    }
  });
}

async function refresh(force = false) {
  try {
    const response = await fetch('/api/state');
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || 'Failed to load state');
    }
    if (force || !shouldPauseRefresh()) {
      render(payload.state);
    } else {
      store.snapshot = payload.state;
    }
  } catch (error) {
    setBanner(error.message, 'error');
  }
}

document.addEventListener('submit', async (event) => {
  if (event.target.matches('.relay-form')) {
    event.preventDefault();
    rememberDetailsState();
    const rowId = Number(event.target.dataset.rowId);
    try {
      const payload = await api(`/api/rows/${rowId}`, {
        method: 'PUT',
        body: serializeRowForm(event.target),
      });
      setBanner(payload.message || 'Relay saved');
      render(payload.state);
    } catch (error) {
      setBanner(error.message, 'error');
    }
    return;
  }

  if (event.target.id === 'random-settings-form') {
    event.preventDefault();
    const rowId = Number(event.target.dataset.rowId);
    try {
      const payload = await api(`/api/rows/${rowId}/random-settings`, {
        body: serializeRandomSettingsForm(event.target),
      });
      setBanner(payload.message || 'Random settings saved');
      render(payload.state);
    } catch (error) {
      setBanner(error.message, 'error');
    }
    return;
  }

  if (event.target.id === 'global-random-settings-form') {
    event.preventDefault();
    try {
      const state = await applyGlobalRandomSettings(event.target);
      setBanner('Global random settings applied');
      render(state);
    } catch (error) {
      setBanner(error.message, 'error');
    }
  }
});

document.addEventListener('click', async (event) => {
  const overlay = event.target.closest('.modal-overlay');
  if (overlay && event.target === overlay) {
    closeOpenDialog();
    render(store.snapshot);
    return;
  }

  const button = event.target.closest('button[data-action]');
  if (!button) {
    return;
  }
  const action = button.dataset.action;

  if (action === 'remove-tag') {
    button.closest('.tag-row')?.remove();
    return;
  }

  if (action === 'add-tag') {
    const section = button.closest('.tag-section');
    const list = section.querySelector('.tag-list');
    appendTagRow(list, button.dataset.kind);
    return;
  }

  if (action === 'reset-default-tags') {
    const section = button.closest('.tag-section');
    const form = button.closest('.relay-form');
    const kind = button.dataset.kind;
    const list = section.querySelector('.tag-list');
    const relayType = form.elements.relay_type.value;
    list.innerHTML = '';
    defaultEntries(relayType, kind).forEach((entry) => appendTagRow(list, kind, entry));
    return;
  }

  rememberDetailsState();

  try {
    let payload;
    if (action === 'add-row') {
      const relayType = document.querySelector('#new-relay-type').value;
      payload = await api('/api/rows', { body: { relay_type: relayType } });
    } else if (action === 'save-launcher-settings') {
      payload = await api('/api/settings', { body: serializeLauncherSettings() });
    } else if (action === 'refresh-network-adapters') {
      payload = await api('/api/settings', { body: serializeLauncherSettings() });
    } else if (action === 'prepare-network') {
      payload = await api('/api/actions/prepare-network');
    } else if (action === 'shutdown-service') {
      const confirmed = window.confirm('Stop the launcher service and all running relay processes?');
      if (!confirmed) {
        return;
      }
      if (store.pollHandle) {
        window.clearInterval(store.pollHandle);
        store.pollHandle = null;
      }
      await api('/api/actions/shutdown-service');
      renderServiceStopped();
      return;
    } else if (action === 'open-global-random-settings') {
      store.globalRandomDialogOpen = true;
      render(store.snapshot);
      return;
    } else if (action === 'close-global-random-dialog') {
      store.globalRandomDialogOpen = false;
      render(store.snapshot);
      return;
    } else if (action === 'global-select-all') {
      setGlobalSelection('all');
      return;
    } else if (action === 'global-select-enabled') {
      setGlobalSelection('enabled');
      return;
    } else if (action === 'global-clear-selection') {
      setGlobalSelection('none');
      return;
    } else if (action === 'open-random-settings') {
      store.randomDialogRowId = Number(button.dataset.rowId);
      render(store.snapshot);
      return;
    } else if (action === 'close-random-dialog') {
      store.randomDialogRowId = null;
      render(store.snapshot);
      return;
    } else if (action === 'edit-row') {
      const rowId = Number(button.dataset.rowId);
      const isOpen = store.openRows.has(rowId);
      setRowDetailsOpen(rowId, !isOpen);
      return;
    } else if (action === 'start-all') {
      payload = await api('/api/actions/start-all');
    } else if (action === 'stop-all') {
      payload = await api('/api/actions/stop-all');
    } else if (action === 'toggle-auto-random') {
      payload = await api('/api/actions/toggle-auto-random');
    } else {
      const rowId = Number(button.dataset.rowId);
      if (action === 'start-row') {
        payload = await api(`/api/rows/${rowId}/start`);
      } else if (action === 'stop-row') {
        payload = await api(`/api/rows/${rowId}/stop`);
      } else if (action === 'randomize-row') {
        payload = await api(`/api/rows/${rowId}/randomize`);
      } else if (action === 'remove-row') {
        const confirmed = window.confirm('Remove this relay row?');
        if (!confirmed) {
          return;
        }
        payload = await api(`/api/rows/${rowId}`, { method: 'DELETE' });
      }
    }

    if (payload) {
      setBanner(payload.message || 'Action completed');
      render(payload.state);
    }
  } catch (error) {
    setBanner(error.message, 'error');
  }
});

document.addEventListener('change', async (event) => {
  if (event.target.id === 'network-adapter-select') {
    try {
      const payload = await api('/api/settings', { body: serializeLauncherSettings() });
      setBanner(payload.message || 'Network adapter saved');
      render(payload.state);
    } catch (error) {
      setBanner(error.message, 'error');
    }
    return;
  }

  if (!event.target.matches('.relay-type-select')) {
    return;
  }
  const form = event.target.closest('.relay-form');
  const section = form.querySelector('[data-kind="analogs"] .tag-list');
  section.innerHTML = '';
  defaultEntries(event.target.value, 'analogs').forEach((entry) => appendTagRow(section, 'analogs', entry));
});

document.addEventListener('input', (event) => {
  if (!event.target.matches('.relay-form input[name="name"]')) {
    return;
  }

  const nameInput = event.target;
  const form = nameInput.closest('.relay-form');
  if (!form) {
    return;
  }

  const keyInput = form.elements.ied_key;
  if (!keyInput) {
    return;
  }

  const previousValue = nameInput.dataset.previousValue || '';
  if (keyInput.value.trim() === '' || keyInput.value === previousValue) {
    keyInput.value = nameInput.value;
  }
  nameInput.dataset.previousValue = nameInput.value;
});

document.addEventListener('toggle', (event) => {
  if (event.target.matches('details[data-row-id]')) {
    rememberDetailsState();
  }
}, true);

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape' || !hasOpenDialog()) {
    return;
  }
  closeOpenDialog();
  render(store.snapshot);
});

window.addEventListener('focus', () => refresh(true));

refresh(true);
store.pollHandle = window.setInterval(() => refresh(false), 2000);
'''
    )


def build_handler(state: LauncherState):
    class LauncherRequestHandler(BaseHTTPRequestHandler):
        server_version = "IEDSimulatorLauncher/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/":
                self._send_bytes(HTML_PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if self.path == "/app.css":
                self._send_bytes(CSS_PAGE.encode("utf-8"), "text/css; charset=utf-8")
                return
            if self.path == "/app.js":
                self._send_bytes(build_app_js().encode("utf-8"), "application/javascript; charset=utf-8")
                return
            if self.path == "/api/state":
                self._send_json(HTTPStatus.OK, {"ok": True, "state": state.snapshot()})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})

        def do_POST(self) -> None:
            payload = self._read_json()
            try:
                if self.path == "/api/settings":
                    message = state.update_settings(payload)
                elif self.path == "/api/rows":
                    message = state.add_row(payload)
                elif self.path == "/api/actions/start-all":
                    message = state.start_all()
                elif self.path == "/api/actions/stop-all":
                    message = state.stop_all()
                elif self.path == "/api/actions/write-all":
                    message = state.write_all_runtime_files()
                elif self.path == "/api/actions/toggle-auto-random":
                    message = state.toggle_auto_random()
                elif self.path == "/api/actions/prepare-network":
                  message = state.prepare_network()
                elif self.path == "/api/actions/shutdown-service":
                  message = "Launcher service is stopping"
                elif self.path == "/api/actions/generate-ip-script":
                    message = state.generate_ip_alias_script()
                elif self.path.startswith("/api/rows/") and self.path.endswith("/start"):
                    message = state.start_row(self._path_id("/start"))
                elif self.path.startswith("/api/rows/") and self.path.endswith("/stop"):
                    message = state.stop_row(self._path_id("/stop"))
                elif self.path.startswith("/api/rows/") and self.path.endswith("/write"):
                    message = state.write_row_runtime_files(self._path_id("/write"))
                elif self.path.startswith("/api/rows/") and self.path.endswith("/randomize"):
                    message = state.randomize_row(self._path_id("/randomize"))
                elif self.path.startswith("/api/rows/") and self.path.endswith("/random-settings"):
                  message = state.update_random_settings(self._path_id("/random-settings"), payload)
                else:
                    self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown route"})
                    return
                self._send_json(HTTPStatus.OK, {"ok": True, "message": message, "state": state.snapshot()})
                if self.path == "/api/actions/shutdown-service":
                  threading.Thread(target=self.server.shutdown, name="launcher-http-shutdown", daemon=True).start()
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

        def do_PUT(self) -> None:
            if not self.path.startswith("/api/rows/"):
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown route"})
                return
            try:
                message = state.update_row(self._path_id(), self._read_json())
                self._send_json(HTTPStatus.OK, {"ok": True, "message": message, "state": state.snapshot()})
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

        def do_DELETE(self) -> None:
            if not self.path.startswith("/api/rows/"):
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Unknown route"})
                return
            try:
                message = state.remove_row(self._path_id())
                self._send_json(HTTPStatus.OK, {"ok": True, "message": message, "state": state.snapshot()})
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))

        def _path_id(self, suffix: str = "") -> int:
            path = self.path
            if suffix and path.endswith(suffix):
                path = path[: -len(suffix)]
            return int(path.rsplit("/", 1)[-1])

        def _send_json(self, status: HTTPStatus, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8", status)

        def _send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return LauncherRequestHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser-based IEC 61850 IED simulator launcher")
    parser.add_argument("--host", default=DEFAULT_WEB_HOST, help="HTTP bind host for the launcher UI")
    parser.add_argument("--port", type=int, default=DEFAULT_WEB_PORT, help="HTTP port for the launcher UI")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the launcher UI in the default browser")
    return parser.parse_args()


def launcher_is_running(url: str) -> bool:
    try:
        with urlopen(f"{url}/api/state", timeout=1.0) as response:
            return response.status == HTTPStatus.OK
    except (URLError, TimeoutError, OSError):
        return False


def main() -> None:
    args = parse_args()
    host = args.host
    port = coerce_port(args.port, DEFAULT_WEB_PORT)
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{port}"

    if launcher_is_running(url):
        print(f"Launcher UI is already available at {url}", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return

    state = LauncherState()
    state.configure_service_endpoint(host, port)

    try:
        server = ThreadingHTTPServer((host, port), build_handler(state))
    except OSError as exc:
        message = str(exc)
        print(f"Launcher UI appears to be running already at {url} ({message})", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return

    state.start()
    print(f"IED simulator launcher serving at {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("Stopping launcher service...", flush=True)
    finally:
        server.server_close()
        state.shutdown()


if __name__ == "__main__":
    main()