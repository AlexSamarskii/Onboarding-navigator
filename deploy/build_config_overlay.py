"""Apply the image-only HTTP configuration; never resolve environment values."""
import argparse
from pathlib import Path
import sys

import yaml


def load_config(path):
    with Path(path).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def apply_overlay(config):
    if not isinstance(config, dict):
        raise ValueError("config must be a mapping")
    http_server = config.setdefault("http_server", {})
    if not isinstance(http_server, dict):
        raise ValueError("http_server must be a mapping")
    http_server.update(enabled=True, port=8080)
    return config


def dump_config(path, config):
    with Path(path).open("w", encoding="utf-8") as stream:
        yaml.safe_dump(config, stream, allow_unicode=True, sort_keys=False,
                       default_flow_style=False)


def verify_overlay(path, expected_keys=None):
    config = load_config(path)
    if not isinstance(config, dict):
        raise ValueError("config must be a mapping")
    server = config.get("http_server")
    if (not isinstance(server, dict) or server.get("enabled") is not True
            or server.get("port") != 8080):
        raise ValueError("HTTP overlay verification failed")
    if expected_keys is not None and set(config) != set(expected_keys):
        raise ValueError("top-level configuration keys changed")
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config_path", type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config_path)
        if not isinstance(config, dict):
            raise ValueError("config must be a mapping")
        expected_keys = set(config) | {"http_server"}
        dump_config(args.config_path, apply_overlay(config))
        verify_overlay(args.config_path, expected_keys)
    except (OSError, ValueError, yaml.YAMLError):
        print("build config overlay failed: invalid or inaccessible configuration",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
