from ottomandevice.core.lifecycle import Runtime


def main() -> None:
    """Start the OttomanDevice production runtime."""
    Runtime().run()


if __name__ == "__main__":
    main()
