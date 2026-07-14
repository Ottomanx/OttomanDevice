from ottomandevice.core.config import ConfigManager
from ottomandevice.core.logger import configure_logging, get_logger
from ottomandevice.runtime import Device


def main() -> None:
    """Legacy entry point that reports local device metadata."""
    ConfigManager.get_instance().load()
    configure_logging()
    logger = get_logger("main")

    device = Device()

    logger.info("-----------------------------------")
    logger.info("Ottoman Device")
    logger.info("Device ID: %s", device.device_id)
    logger.info("Computer Name: %s", device.computer_name)
    logger.info("Operating System: %s", device.operating_system)
    logger.info("Python Version: %s", device.python_version)
    logger.info("Firmware Version: %s", device.firmware_version)
    logger.info("Status: %s", device.status.value)
    logger.info("-----------------------------------")


if __name__ == "__main__":
    main()
