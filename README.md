# OpenFanAuto

Unified fan controller + temperature automation + Web UI for the OpenFAN hardware — a single Docker container.

**Port 3211** | **Python 3.11+** | **Tornado** | **Tabler UI** | **Chart.js curve editor**

---

## Quick Start (Mock Hardware)

```bash
# Install dependencies
pip install -r requirements.txt

# Run with mock hardware (no physical device needed)
cd src
python main.py --mock --debug

# Open browser → http://localhost:3211
```

---

## Docker

### Local Dev (Mock)

```bash
docker compose up -d
docker compose logs -f
```

### Unraid — `docker run`

```bash
# 1. Prepare appdata directory
mkdir -p /mnt/user/appdata/openfanauto
cp config/config.yaml /mnt/user/appdata/openfanauto/

# 2. Run (adjust OPENFANCOMPORT to your device)
docker run -d \
  --name openfanauto \
  --restart unless-stopped \
  -p 3211:3211 \
  -e MOCK_HARDWARE=false \
  -e OPENFANCOMPORT=/dev/ttyUSB0 \
  -e OPENFAN_AUTO_ENABLED=true \
  -e OPENFAN_DEBUG_UART=false \
  -e OPENFAN_PORT=3211 \
  -e OPENFAN_POLL_INTERVAL=10 \
  -e OPENFAN_RELOAD_PROFILES=true \
  -v /mnt/user/appdata/openfanauto:/config:rw \
  -v /var/local/emhttp/disks.ini:/var/local/emhttp/disks.ini:ro \
  -v /dev:/dev:ro \
  --device /dev/ttyUSB0:/dev/ttyUSB0 \
  --cap-add SYS_RAWIO \
  openfanauto:latest

# 3. Open the Web UI → http://your-unraid-ip:3211
#    Create profiles, assign fans, and click 'Save' to persist.
```

### Unraid — `docker compose`

```bash
# 1. Prepare appdata
mkdir -p /mnt/user/appdata/openfanauto
cp config/config.yaml /mnt/user/appdata/openfanauto/

# 2. Edit docker-compose.prod.yml — set OPENFANCOMPORT, then:
docker compose -f docker-compose.prod.yml up -d
```

> **Note:** The default config path inside the container is `/config/config.yaml`.
> Mount your appdata directory to `/config` and config + profile saves will persist there.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_HARDWARE` | `false` | Use mock serial driver (no hardware needed) |
| `OPENFAN_AUTO_ENABLED` | `false` | Start with automation enabled on boot |
| `OPENFAN_DEBUG_UART` | `false` | Enable serial debug logging |
| `OPENFAN_PORT` | `3211` | Server listen port |
| `OPENFAN_POLL_INTERVAL` | `10` | Seconds between automation ticks |
| `OPENFAN_RELOAD_PROFILES` | `false` | Hot-reload YAML profiles each cycle |
| `OPENFAN_CONFIG` | `/config/config.yaml` | Path to YAML config file |
| `OPENFANCOMPORT` | — | Serial port for OpenFAN hardware |
| `OPENFAN_LOG_LEVEL` | `info` | Logging level (`info` or `debug`) |

---

## API Endpoints

All endpoints prefixed with `/api/v0/`. Responses are JSON: `{"status": "ok|fail", "message": "...", "data": {...}}`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/fan/status` | Fan RPMs + state |
| GET | `/fan/{0-9}/pwm?value=` | Set single fan PWM (0-100) |
| GET | `/fan/{0-9}/rpm?value=` | Set single fan RPM target |
| GET | `/fan/all/set?value=` | Set all fans PWM |
| GET | `/fan/{0-9}/mode?mode=manual\|auto` | Per-fan mode toggle |
| GET | `/sensors` | Current temperature readings |
| GET | `/profiles/list` | Fan profiles + fan controls |
| GET | `/profiles/set?name=` | Activate a profile (switches matching fans to auto) |
| POST | `/profiles/add` | Add/update a profile (body: `name`, `type`, `points` JSON, `tempsource`, `usepwm`) |
| GET | `/profiles/remove?name=` | Delete a profile |
| POST | `/controls/assign` | Assign a profile to a fan (`fan=0&profile=QuietMode`) |
| POST | `/config/update` | Bulk-update config keys (JSON body) |
| GET | `/config/save` | Persist all in-memory changes to `config.yaml` |
| GET | `/config/reload` | Reload config from disk (undo unsaved changes) |
| GET | `/alias/all/get` | All fan aliases |
| GET | `/alias/{n}/get` | Single fan alias |
| GET | `/alias/{n}/set?value=` | Set fan alias |
| GET | `/info` | Hardware/firmware/software info |
| GET | `/automation?action=status\|start\|stop` | Automation control |

---

## Configuration (config.yaml)

```yaml
server:
  hostname: localhost
  port: 3211

hardware:
  port: /dev/ttyUSB0        # Serial port (or COM3 on Windows)
  debug_uart: false

automation:
  enabled: true
  poll_interval: 10

paths:
  disks_ini: /var/local/emhttp/disks.ini   # Unraid disk temps

smartctl_devices:           # NVMe / unassigned devices fallback
  - "/dev/nvme0n1"
  - "/dev/sda"

fan_profiles:
  QuietMode:
    CurveType: "linear"
    TempSource: ["disk1", "disk2"]
    UsePWM: false
    Points:
      30: 500
      45: 1200
      60: 2000

fan_controls:
  "0":
    AssignedProfile: "QuietMode"
  "1":
    AssignedProfile: "QuietMode"
```

---

## Project Structure

```
OpenFanAuto/
├── config/
│   └── config.yaml
├── src/
│   ├── main.py                 # Entrypoint — wires everything
│   ├── base_logger.py
│   ├── config_manager.py       # YAML config loader with dot-notation
│   ├── fan_commander.py        # High-level fan control + state
│   ├── serial_driver.py        # Real serial hardware (pyserial)
│   ├── mock_serial_driver.py   # Mock hardware for dev/testing
│   ├── api/
│   │   └── handlers.py         # Tornado request handlers
│   ├── automation/
│   │   ├── auto_controller.py  # Temp → curve → fan speed loop
│   │   └── fan_curves.py       # Threshold & linear interpolation
│   ├── temperature/
│   │   ├── sensor_reader.py    # Merges disks.ini + smartctl
│   │   ├── disks_ini_parser.py # Parse Unraid disks.ini
│   │   └── smartctl_parser.py  # Parse smartctl -a output
│   └── UI/
│       ├── index.html          # Main page (Tabler + Chart.js CDN)
│       ├── css/app.css
│       └── js/app.js           # All UI logic (vanilla JS, no build step)
├── tests/
│   ├── test_auto_controller.py
│   ├── test_base_logger.py
│   ├── test_config_manager.py
│   ├── test_db.py
│   ├── test_disks_ini_parser.py
│   └── test_fan_curves.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml          # Local dev (mock hardware)
└── docker-compose.prod.yml     # Unraid production

---

## Credits

OpenFanAuto merges and builds upon two excellent projects by
[SasaKaranovic](https://github.com/SasaKaranovic):

- **[OpenFanController](https://github.com/SasaKaranovic/OpenFanController)** — RP2040 firmware, Python backend API, and Web GUI
- **[OpenFanUnraidService](https://github.com/SasaKaranovic/OpenFanUnraidService)** — Unraid disk temperature monitoring and automatic fan control
