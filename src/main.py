"""OpenFanAuto — single-Python-process fan controller + temperature automation + Web UI.

Usage::

    cd src && python main.py --mock
    cd src && python main.py --config ../config/config.yaml

Environment variables:
    MOCK_HARDWARE=true      use mock serial driver
    OPENFAN_POLL_INTERVAL   seconds between automation ticks (default 10)
    OPENFAN_RELOAD_PROFILES true to hot-reload YAML before each tick
    OPENFAN_CONFIG          path to config.yaml
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

import tornado.ioloop
import tornado.web

from api.handlers import (  # pylint: disable=unused-import
    AutomationHandler,
    ConfigReloadHandler,
    ConfigSaveHandler,
    ConfigUpdateHandler,
    ControlAssignHandler,
    Default404Handler,
    FanAliasAllHandler,
    FanAliasGetHandler,
    FanAliasSetHandler,
    FanModeHandler,
    FanSetAllPWMHandler,
    FanSetPWMHandler,
    FanSetRPMHandler,
    FanStatusHandler,
    InfoHandler,
    ProfileAddHandler,
    ProfileListHandler,
    ProfileRemoveHandler,
    ProfileSetHandler,
    SensorsHandler,
)
from automation.auto_controller import AutoController
from config_manager import ConfigManager
from fan_commander import FanCommander
from temperature.sensor_reader import SensorReader

from base_logger import logger, set_logger_level

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OpenFanAuto")
    p.add_argument(
        "--config",
        default=os.environ.get("OPENFAN_CONFIG", str(Path(__file__).resolve().parent.parent / "config" / "config.yaml")),
        help="Path to config YAML (env: OPENFAN_CONFIG)",
    )
    p.add_argument("--mock", action="store_true", help="Use mock serial driver")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    return p.parse_args()


# ---------------------------------------------------------------------------
# build Tornado app
# ---------------------------------------------------------------------------


def make_app(
    commander: FanCommander,
    config: ConfigManager,
    auto_controller: AutoController,
    debug: bool,
) -> tornado.web.Application:
    ui_dir = Path(__file__).resolve().parent / "UI"

    init_kwargs = {
        "commander": commander,
        "config": config,
        "auto_controller": auto_controller,
    }

    routes: list = [
        # Fan status & control
        (r"/api/v0/fan/status", FanStatusHandler, init_kwargs),
        (r"/api/v0/fan/([0-9])/pwm", FanSetPWMHandler, init_kwargs),
        (r"/api/v0/fan/([0-9])/set", FanSetPWMHandler, init_kwargs),  # deprecated alias
        (r"/api/v0/fan/([0-9])/rpm", FanSetRPMHandler, init_kwargs),
        (r"/api/v0/fan/all/set", FanSetAllPWMHandler, init_kwargs),
        (r"/api/v0/fan/([0-9])/mode", FanModeHandler, init_kwargs),
        # Aliases
        (r"/api/v0/alias/all/get", FanAliasAllHandler, init_kwargs),
        (r"/api/v0/alias/([0-9])/get", FanAliasGetHandler, init_kwargs),
        (r"/api/v0/alias/([0-9])/set", FanAliasSetHandler, init_kwargs),
        # Profiles
        (r"/api/v0/profiles/list", ProfileListHandler, init_kwargs),
        (r"/api/v0/profiles/set", ProfileSetHandler, init_kwargs),
        (r"/api/v0/profiles/add", ProfileAddHandler, init_kwargs),
        (r"/api/v0/profiles/remove", ProfileRemoveHandler, init_kwargs),
        # Config
        (r"/api/v0/config/save", ConfigSaveHandler, init_kwargs),
        (r"/api/v0/config/reload", ConfigReloadHandler, init_kwargs),
        (r"/api/v0/config/update", ConfigUpdateHandler, init_kwargs),
        # Controls (profile assignment)
        (r"/api/v0/controls/assign", ControlAssignHandler, init_kwargs),
        # Sensors
        (r"/api/v0/sensors", SensorsHandler, init_kwargs),
        # Info
        (r"/api/v0/info", InfoHandler, init_kwargs),
        # Automation
        (r"/api/v0/automation", AutomationHandler, init_kwargs),
    ]

    # Static UI — if UI/ directory exists
    if ui_dir.is_dir():
        routes.append((r"/", tornado.web.RedirectHandler, {"url": "/index.html"}))
        routes.append(
            (r"/(.*)", tornado.web.StaticFileHandler, {"path": str(ui_dir), "default_filename": "index.html"})
        )
    else:
        routes.append((r"/", Default404Handler))

    return tornado.web.Application(
        routes,
        debug=debug,
        autoreload=False,
        default_handler_class=Default404Handler,
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()

    if args.debug:
        set_logger_level("debug")
    else:
        set_logger_level("info")

    logger.info("=== OpenFanAuto starting ===")

    # ---- Config ----------------------------------------------------------
    config = ConfigManager(args.config)

    # ---- Hardware backend ------------------------------------------------
    use_mock = args.mock or os.environ.get("MOCK_HARDWARE", "false").lower() == "true"

    if use_mock:
        logger.info("Using MOCK hardware")
        from mock_serial_driver import MockSerialHardware

        backend = MockSerialHardware()
    else:
        port_cfg = config.get("hardware.port", None) or os.environ.get("OPENFANCOMPORT")
        if not port_cfg:
            logger.error("No hardware port configured (set hardware.port in config or OPENFANCOMPORT env)")
            sys.exit(1)
        logger.info("Using real hardware on %s", port_cfg)
        from serial_driver import SerialHardware

        backend = SerialHardware(
            port_info=port_cfg,
            flush_on_write=True,
            serialPrefix="",
            serialSuffix="\r\n",
            timeout=0.2,
            debug_uart=config.get("hardware.debug_uart", False),
        )

    commander = FanCommander(backend)
    commander.open()

    # ---- Sensor reader ---------------------------------------------------
    disks_ini = config.get("paths.disks_ini", "config/disks.ini")
    smartctl_devices = config.get("smartctl_devices", [])
    sensors = SensorReader(disks_ini_path=disks_ini, smartctl_devices=smartctl_devices)

    # ---- Automation controller -------------------------------------------
    auto_ctrl = AutoController(commander, config, sensors)
    if config.get("automation.enabled", False):
        auto_ctrl.start()

    # ---- Tornado app -----------------------------------------------------
    app = make_app(commander, config, auto_ctrl, args.debug)
    port = config.get("server.port", 3211)

    # ---- Periodic automation callback ------------------------------------
    poll_interval = int(os.environ.get("OPENFAN_POLL_INTERVAL", config.get("automation.poll_interval", 10)))
    live_reload = os.environ.get("OPENFAN_RELOAD_PROFILES", "false").lower() in ("true", "1", "yes")

    def automation_tick() -> None:
        if live_reload:
            config.reload()
        auto_ctrl.tick()

    loop = tornado.ioloop.IOLoop.current()
    timer = tornado.ioloop.PeriodicCallback(automation_tick, poll_interval * 1000)
    timer.start()

    # ---- Signal handling -------------------------------------------------
    def shutdown() -> None:
        logger.info("Shutting down…")
        timer.stop()
        auto_ctrl.stop()
        commander.close()
        loop.stop()

    signal.signal(signal.SIGINT, lambda s, f: loop.add_callback_from_signal(shutdown))
    signal.signal(signal.SIGTERM, lambda s, f: loop.add_callback_from_signal(shutdown))

    # ---- Run -------------------------------------------------------------
    logger.info("Listening on port %d", port)
    app.listen(port)
    try:
        loop.start()
    except KeyboardInterrupt:
        shutdown()

    logger.info("Goodbye.")


if __name__ == "__main__":
    main()