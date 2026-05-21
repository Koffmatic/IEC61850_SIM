from __future__ import annotations

import json
import random
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, IO, List, Optional, Tuple

try:
    import customtkinter as ctk
except ImportError as exc:
    raise SystemExit(
        "customtkinter is missing. Install dependencies with: py -m pip install -r requirements.txt"
    ) from exc


BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "runtime"
TOOLS_DIR = BASE_DIR / "tools"

DEFAULT_EXE_FIELD = "./ied_mms_server_real.exe"
DEFAULT_PORT = 102
AUTO_RANDOM_INTERVAL_MS = 1000
PROCESS_POLL_INTERVAL_MS = 500

STATUS_COLORS = {
    "idle": "#8a94a6",
    "running": "#2fa572",
    "stopped": "#8a94a6",
    "warning": "#d69e2e",
    "error": "#e05f5f",
}

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

BOOL_DEFAULTS = {
    tag: tag.startswith("LD0.LEDGGIO1.Ind") for tag in COMMON_BOOL_TAGS
}

DEFAULT_IEDS = [
    {
        "enabled": True,
        "name": "AA1H1H01BCF1",
        "type": "REF615",
        "ip": "10.206.204.5",
        "port": DEFAULT_PORT,
    },
    {
        "enabled": True,
        "name": "REU615_SIM_01",
        "type": "REU615",
        "ip": "10.206.204.16",
        "port": DEFAULT_PORT,
    },
    {
        "enabled": True,
        "name": "RED615_SIM_01",
        "type": "RED615",
        "ip": "10.206.204.17",
        "port": DEFAULT_PORT,
    },
]


@dataclass
class RelayRow:
    ordinal: int
    default_name: str
    default_type: str
    default_ip: str
    default_port: int
    enabled_var: object
    name_var: object
    type_var: object
    ip_var: object
    port_var: object
    status_var: object
    status_label: object
    analogs: Dict[str, float] = field(default_factory=dict)
    bools: Dict[str, bool] = field(default_factory=dict)
    words: Dict[str, int] = field(default_factory=dict)
    process: Optional[subprocess.Popen] = None
    process_log: Optional[IO[str]] = None


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


def build_default_analogs(relay_type: str) -> Dict[str, float]:
    return {tag: ANALOG_DEFAULTS[tag] for tag in RELAY_ANALOG_TAGS[relay_type]}


def build_default_words() -> Dict[str, int]:
    return dict(WORD_DEFAULTS)


def build_default_bools() -> Dict[str, bool]:
    return dict(BOOL_DEFAULTS)


def render_ip_alias_script(ip_addresses: List[str]) -> str:
    unique_ips = []
    seen = set()
    for ip_address in ip_addresses:
        cleaned = ip_address.strip()
        if not cleaned or cleaned in seen:
            continue
        unique_ips.append(cleaned)
        seen.add(cleaned)

    quoted_ips = ",\n    ".join(f'"{ip_address}"' for ip_address in unique_ips)
    return f'''# Run this PowerShell script as Administrator.
# Each simulated IED requires its own local IP alias on the same adapter.

$adapterName = "Ethernet"
$prefixLength = 24
$ipAddresses = @(
    {quoted_ips}
)

foreach ($ipAddress in $ipAddresses) {{
    if ([string]::IsNullOrWhiteSpace($ipAddress)) {{
        continue
    }}

    $existingIp = Get-NetIPAddress -InterfaceAlias $adapterName -IPAddress $ipAddress -ErrorAction SilentlyContinue

    if ($null -ne $existingIp) {{
        Write-Host "$ipAddress already exists on $adapterName"
        continue
    }}

    New-NetIPAddress -InterfaceAlias $adapterName -IPAddress $ipAddress -PrefixLength $prefixLength -AddressFamily IPv4
    Write-Host "Added $ipAddress to $adapterName"
}}
'''


class LauncherApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.title("IEC 61850 MMS IED Simulator Launcher")
        self.geometry("1460x760")
        self.minsize(1260, 620)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self.exe_path_var = ctk.StringVar(value=DEFAULT_EXE_FIELD)
        self.activity_var = ctk.StringVar(value="Ready. Write values to create runtime JSON files.")

        self.rows: List[RelayRow] = []
        self.auto_random_enabled = False
        self.auto_random_after_id: Optional[str] = None
        self.poll_after_id: Optional[str] = None

        self._build_ui()
        self._generate_ip_alias_script(log=False)
        self.poll_after_id = self.after(PROCESS_POLL_INTERVAL_MS, self._poll_processes)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        title = ctk.CTkLabel(
            self,
            text="IEC 61850 MMS IED Simulator Launcher",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title.grid(row=0, column=0, padx=20, pady=(18, 8), sticky="w")

        settings_frame = ctk.CTkFrame(self)
        settings_frame.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="ew")
        settings_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(settings_frame, text="MMS server executable").grid(
            row=0, column=0, padx=(16, 10), pady=14, sticky="w"
        )
        ctk.CTkEntry(settings_frame, textvariable=self.exe_path_var).grid(
            row=0, column=1, padx=(0, 10), pady=14, sticky="ew"
        )
        ctk.CTkLabel(
            settings_frame,
            text="Relative path is resolved from the IEDsimulator folder.",
            text_color="#8a94a6",
        ).grid(row=0, column=2, padx=(0, 16), pady=14, sticky="e")

        table_frame = ctk.CTkFrame(self)
        table_frame.grid(row=2, column=0, padx=20, pady=(0, 12), sticky="ew")
        for column in range(8):
            table_frame.grid_columnconfigure(column, weight=1 if column in (1, 3) else 0)

        headers = [
            ("Enabled", 0),
            ("IED name", 1),
            ("Relay type", 2),
            ("IP address", 3),
            ("Port", 4),
            ("Start", 5),
            ("Stop", 6),
            ("Status", 7),
        ]
        for text, column in headers:
            ctk.CTkLabel(
                table_frame,
                text=text,
                font=ctk.CTkFont(size=14, weight="bold"),
            ).grid(row=0, column=column, padx=8, pady=(12, 8), sticky="w")

        for row_index, spec in enumerate(DEFAULT_IEDS, start=1):
            self._build_relay_row(table_frame, row_index, spec)

        actions_frame = ctk.CTkFrame(self)
        actions_frame.grid(row=3, column=0, padx=20, pady=(0, 12), sticky="ew")
        for column in range(5):
            actions_frame.grid_columnconfigure(column, weight=1)

        self.start_all_button = ctk.CTkButton(actions_frame, text="Start all", command=self._start_all)
        self.start_all_button.grid(row=0, column=0, padx=8, pady=14, sticky="ew")

        self.stop_all_button = ctk.CTkButton(
            actions_frame,
            text="Stop all",
            command=self._stop_all,
            fg_color="#6b7280",
            hover_color="#4b5563",
        )
        self.stop_all_button.grid(row=0, column=1, padx=8, pady=14, sticky="ew")

        self.write_values_button = ctk.CTkButton(
            actions_frame,
            text="Write values",
            command=self._write_all_runtime_files,
        )
        self.write_values_button.grid(row=0, column=2, padx=8, pady=14, sticky="ew")

        self.auto_random_button = ctk.CTkButton(
            actions_frame,
            text="Auto random values",
            command=self._toggle_auto_random,
        )
        self.auto_random_button.grid(row=0, column=3, padx=8, pady=14, sticky="ew")

        self.ip_script_button = ctk.CTkButton(
            actions_frame,
            text="Generate PowerShell IP alias script",
            command=self._generate_ip_alias_script,
        )
        self.ip_script_button.grid(row=0, column=4, padx=8, pady=14, sticky="ew")

        bottom_frame = ctk.CTkFrame(self)
        bottom_frame.grid(row=4, column=0, padx=20, pady=(0, 20), sticky="nsew")
        bottom_frame.grid_columnconfigure(0, weight=1)
        bottom_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            bottom_frame,
            textvariable=self.activity_var,
            anchor="w",
            text_color="#d0d4dc",
        ).grid(row=0, column=0, padx=16, pady=(14, 6), sticky="ew")

        self.log_box = ctk.CTkTextbox(bottom_frame)
        self.log_box.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        self.log_box.insert(
            "end",
            "Launcher ready. Missing ied_mms_server.exe does not stop JSON/script generation.\n",
        )
        self.log_box.configure(state="disabled")

    def _build_relay_row(self, parent: ctk.CTkFrame, row_index: int, spec: Dict[str, object]) -> None:
        enabled_var = ctk.BooleanVar(value=bool(spec["enabled"]))
        name_var = ctk.StringVar(value=str(spec["name"]))
        type_var = ctk.StringVar(value=str(spec["type"]))
        ip_var = ctk.StringVar(value=str(spec["ip"]))
        port_var = ctk.StringVar(value=str(spec["port"]))
        status_var = ctk.StringVar(value="idle")

        ctk.CTkCheckBox(parent, text="", variable=enabled_var, width=28).grid(
            row=row_index, column=0, padx=8, pady=8, sticky="w"
        )
        ctk.CTkEntry(parent, textvariable=name_var).grid(
            row=row_index, column=1, padx=8, pady=8, sticky="ew"
        )
        ctk.CTkOptionMenu(
            parent,
            values=list(RELAY_ANALOG_TAGS.keys()),
            variable=type_var,
            command=lambda _value, idx=row_index - 1: self._on_type_changed(idx),
        ).grid(row=row_index, column=2, padx=8, pady=8, sticky="ew")
        ctk.CTkEntry(parent, textvariable=ip_var).grid(
            row=row_index, column=3, padx=8, pady=8, sticky="ew"
        )
        ctk.CTkEntry(parent, textvariable=port_var, width=90).grid(
            row=row_index, column=4, padx=8, pady=8, sticky="ew"
        )
        ctk.CTkButton(
            parent,
            text="Start",
            width=90,
            command=lambda idx=row_index - 1: self._start_row(idx),
        ).grid(row=row_index, column=5, padx=8, pady=8, sticky="ew")
        ctk.CTkButton(
            parent,
            text="Stop",
            width=90,
            command=lambda idx=row_index - 1: self._stop_row(idx),
            fg_color="#6b7280",
            hover_color="#4b5563",
        ).grid(row=row_index, column=6, padx=8, pady=8, sticky="ew")
        status_label = ctk.CTkLabel(parent, textvariable=status_var, text_color=STATUS_COLORS["idle"])
        status_label.grid(row=row_index, column=7, padx=8, pady=8, sticky="w")

        relay_row = RelayRow(
            ordinal=row_index,
            default_name=str(spec["name"]),
            default_type=str(spec["type"]),
            default_ip=str(spec["ip"]),
            default_port=int(spec["port"]),
            enabled_var=enabled_var,
            name_var=name_var,
            type_var=type_var,
            ip_var=ip_var,
            port_var=port_var,
            status_var=status_var,
            status_label=status_label,
        )
        self._ensure_value_maps(relay_row)
        self.rows.append(relay_row)

    def _log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self.activity_var.set(message)

    def _set_status(self, row: RelayRow, text: str, tone: str) -> None:
        row.status_var.set(text)
        row.status_label.configure(text_color=STATUS_COLORS[tone])

    def _normalize_row_inputs(self, row: RelayRow) -> Tuple[str, str, str, int]:
        name = row.name_var.get().strip() or row.default_name
        row.name_var.set(name)

        relay_type = row.type_var.get().strip() or row.default_type
        if relay_type not in RELAY_ANALOG_TAGS:
            relay_type = row.default_type
            row.type_var.set(relay_type)

        ip_address = row.ip_var.get().strip() or row.default_ip
        row.ip_var.set(ip_address)

        try:
            port = int(str(row.port_var.get()).strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            port = row.default_port
            row.port_var.set(str(port))

        self._ensure_value_maps(row)
        return name, relay_type, ip_address, port

    def _ensure_value_maps(self, row: RelayRow) -> None:
        relay_type = row.type_var.get().strip() or row.default_type
        if relay_type not in RELAY_ANALOG_TAGS:
            relay_type = row.default_type
            row.type_var.set(relay_type)

        existing_analogs = dict(row.analogs)
        row.analogs = {
            tag: float(existing_analogs.get(tag, ANALOG_DEFAULTS[tag]))
            for tag in RELAY_ANALOG_TAGS[relay_type]
        }

        existing_words = dict(row.words)
        row.words = {
            tag: int(existing_words.get(tag, WORD_DEFAULTS[tag]))
            for tag in COMMON_WORD_TAGS
        }

        existing_bools = dict(row.bools)
        row.bools = {
            tag: bool(existing_bools.get(tag, BOOL_DEFAULTS[tag]))
            for tag in COMMON_BOOL_TAGS
        }

    def _runtime_paths(self, row: RelayRow) -> Tuple[Path, Path, Path]:
        name, _relay_type, _ip_address, _port = self._normalize_row_inputs(row)
        stem = safe_name(name)
        return (
            RUNTIME_DIR / f"{stem}_config.json",
            RUNTIME_DIR / f"{stem}_values.json",
            RUNTIME_DIR / f"{stem}_server.log",
        )

    def _values_payload(self, row: RelayRow) -> Dict[str, object]:
        self._ensure_value_maps(row)
        return {
            "analogs": {tag: float(value) for tag, value in row.analogs.items()},
            "bools": {tag: bool(value) for tag, value in row.bools.items()},
            "words": {tag: int(value) for tag, value in row.words.items()},
            "updated_unix_ms": now_ms(),
        }

    def _config_payload(self, row: RelayRow, values_path: Path) -> Dict[str, object]:
        name, relay_type, ip_address, port = self._normalize_row_inputs(row)
        return {
            "enabled": bool(row.enabled_var.get()),
            "ied_name": name,
            "relay_type": relay_type,
            "bind_ip": ip_address,
            "port": port,
            "values_path": to_relative_posix(values_path),
            "analog_tags": list(row.analogs.keys()),
            "word_tags": list(row.words.keys()),
            "bool_tags": list(row.bools.keys()),
            "mms_server_executable": self.exe_path_var.get().strip() or DEFAULT_EXE_FIELD,
            "updated_unix_ms": now_ms(),
        }

    def _write_row_runtime_files(self, row: RelayRow, log: bool = True) -> Tuple[Path, Path]:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        config_path, values_path, _log_path = self._runtime_paths(row)
        config_payload = self._config_payload(row, values_path)
        values_payload = self._values_payload(row)

        config_path.write_text(json.dumps(config_payload, indent=2), encoding="utf-8")
        values_path.write_text(json.dumps(values_payload, indent=2), encoding="utf-8")

        if log:
            self._log(
                f"Wrote {to_relative_posix(config_path)} and {to_relative_posix(values_path)}"
            )

        return config_path, values_path

    def _write_all_runtime_files(self) -> None:
        for row in self.rows:
            self._write_row_runtime_files(row, log=False)
        self._log(f"Wrote runtime JSON files for {len(self.rows)} IEDs")

    def _resolved_executable(self) -> Tuple[str, Path]:
        raw_path = self.exe_path_var.get().strip() or DEFAULT_EXE_FIELD
        self.exe_path_var.set(raw_path)
        executable = Path(raw_path)
        if not executable.is_absolute():
            executable = (BASE_DIR / executable).resolve()
        return raw_path, executable

    def _start_row(self, index: int) -> None:
        row = self.rows[index]

        if row.process is not None and row.process.poll() is None:
            self._set_status(row, "running", "running")
            self._log(f"{row.name_var.get()} is already running")
            return

        name, relay_type, ip_address, port = self._normalize_row_inputs(row)
        _config_path, values_path = self._write_row_runtime_files(row, log=False)
        values_arg = to_relative_posix(values_path)

        raw_exe_path, executable = self._resolved_executable()
        if not executable.exists():
            self._set_status(row, "missing exe", "warning")
            self._log(f"{name}: missing executable at {raw_exe_path}")
            return

        _config_path, _values_path, log_path = self._runtime_paths(row)
        try:
            log_handle = log_path.open("a", encoding="utf-8")
            log_handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting {name}\n")
            log_handle.flush()

            command = [
                str(executable),
                "--ied-name",
                name,
                "--type",
                relay_type,
                "--bind",
                ip_address,
                "--port",
                str(port),
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
            self._set_status(row, "running", "running")
            self._log(f"Started {name} on {ip_address}:{port}")
        except Exception as exc:
            if "log_handle" in locals() and log_handle:
                log_handle.close()
            row.process = None
            row.process_log = None
            self._set_status(row, "start failed", "error")
            self._log(f"{name}: failed to start process ({exc})")

    def _stop_row(self, index: int) -> None:
        row = self.rows[index]
        name = self._normalize_row_inputs(row)[0]

        if row.process is None:
            self._set_status(row, "stopped", "stopped")
            self._log(f"{name}: no running process")
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
            self._set_status(row, "stop failed", "error")
            self._log(f"{name}: failed to stop process ({exc})")
        finally:
            row.process = None
            if row.process_log is not None:
                row.process_log.close()
                row.process_log = None

        self._set_status(row, "stopped", "stopped")
        self._log(f"Stopped {name}")

    def _start_all(self) -> None:
        enabled_rows = [row for row in self.rows if bool(row.enabled_var.get())]
        if not enabled_rows:
            self._log("Start all skipped: no IED rows are enabled")
            return

        for index, row in enumerate(self.rows):
            if bool(row.enabled_var.get()):
                self._start_row(index)

    def _stop_all(self) -> None:
        for index in range(len(self.rows)):
            self._stop_row(index)

    def _on_type_changed(self, index: int) -> None:
        row = self.rows[index]
        self._ensure_value_maps(row)
        self._log(f"{row.name_var.get().strip() or row.default_name}: relay type set to {row.type_var.get()}")

    def _randomize_row_values(self, row: RelayRow) -> None:
        _name, relay_type, _ip_address, _port = self._normalize_row_inputs(row)

        row.analogs = {}
        for tag in RELAY_ANALOG_TAGS[relay_type]:
            low, high = ANALOG_RANDOM_RANGES[tag]
            row.analogs[tag] = round(random.uniform(low, high), 3)

        row.words = {}
        for tag in COMMON_WORD_TAGS:
            low, high = WORD_RANDOM_RANGES[tag]
            row.words[tag] = random.randint(low, high)

        row.bools = {}
        for tag in COMMON_BOOL_TAGS:
            if ".Ind" in tag:
                row.bools[tag] = random.random() >= 0.25
            else:
                row.bools[tag] = random.random() >= 0.90

    def _toggle_auto_random(self) -> None:
        self.auto_random_enabled = not self.auto_random_enabled

        if self.auto_random_enabled:
            self.auto_random_button.configure(text="Stop auto random")
            self._log("Auto random enabled")
            self._auto_random_tick()
        else:
            if self.auto_random_after_id is not None:
                self.after_cancel(self.auto_random_after_id)
                self.auto_random_after_id = None
            self.auto_random_button.configure(text="Auto random values")
            self._log("Auto random stopped")

    def _auto_random_tick(self) -> None:
        if not self.auto_random_enabled:
            return

        targets = [row for row in self.rows if bool(row.enabled_var.get())] or self.rows
        for row in targets:
            self._randomize_row_values(row)
            self._write_row_runtime_files(row, log=False)

        self.activity_var.set(
            f"Auto random updated {len(targets)} IED value files at {time.strftime('%H:%M:%S')}"
        )
        self.auto_random_after_id = self.after(AUTO_RANDOM_INTERVAL_MS, self._auto_random_tick)

    def _generate_ip_alias_script(self, log: bool = True) -> None:
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        ip_addresses = []
        for row in self.rows:
            _name, _relay_type, ip_address, _port = self._normalize_row_inputs(row)
            ip_addresses.append(ip_address)

        script_path = TOOLS_DIR / "add_ip_aliases.ps1"
        script_path.write_text(render_ip_alias_script(ip_addresses), encoding="utf-8")

        if log:
            self._log(f"Generated {to_relative_posix(script_path)}")

    def _poll_processes(self) -> None:
        for row in self.rows:
            if row.process is None:
                continue

            return_code = row.process.poll()
            if return_code is None:
                continue

            name = row.name_var.get().strip() or row.default_name
            if row.process_log is not None:
                row.process_log.close()
                row.process_log = None

            row.process = None
            if return_code == 0:
                self._set_status(row, "exited (0)", "stopped")
            else:
                self._set_status(row, f"exited ({return_code})", "warning")
            self._log(f"{name}: process exited with code {return_code}")

        self.poll_after_id = self.after(PROCESS_POLL_INTERVAL_MS, self._poll_processes)

    def _on_close(self) -> None:
        if self.auto_random_after_id is not None:
            self.after_cancel(self.auto_random_after_id)
            self.auto_random_after_id = None
        if self.poll_after_id is not None:
            self.after_cancel(self.poll_after_id)
            self.poll_after_id = None

        for index, row in enumerate(self.rows):
            if row.process is not None:
                try:
                    self._stop_row(index)
                except Exception:
                    pass

        self.destroy()


def main() -> None:
    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()