# KittyCaster

A command-line tool for scheduling and casting YouTube videos to Chromecast devices.

## Installation

```bash
pip install kittycaster
```

## Quick Start

### Initialize Configuration

```bash
kittycaster init
```

### One-Off Casting

Cast a video:

```bash
kittycaster once --start --video_id dQw4w9WgXcQ
```

Stop casting:

```bash
kittycaster once --stop
```

### Schedule Casting

Interactive scheduling:

```bash
kittycaster schedule --interactive
```

Run predefined schedule:

```bash
kittycaster schedule
```

## Usage Overview

### General Command

```bash
kittycaster --help  # See available subcommands
```

### Initialization

```bash
kittycaster init
```

Creates a default `config.yaml` in `~/.config/kittycaster/`.

### One-Off Casting

```bash
kittycaster once [options]
```

Options:

- `--start`: Cast a video
- `--stop`: Stop casting
- `--friendly_name`: Override Chromecast name
- `--video_id`: Specify YouTube video
- `--volume`: Set volume (0.0-1.0)

### Scheduling

```bash
kittycaster schedule [options]
```

Options:

- `--interactive`: Interactively create schedules

## Configuration

Default config: `~/.config/kittycaster/config.yaml`

Example config:

```yaml
friendly_name: "KittyCaster TV"
video_ids:
  - "dQw4w9WgXcQ"
schedule:
  - start_time: "08:00"
    end_time: "09:00"
    volume: 0.05
```

### Custom Config

Use `--config` to specify a different config file:

```bash
kittycaster --config /path/to/config.yaml schedule
```

## Troubleshooting

- Ensure Chromecast and computer are on the same network
- Verify `friendly_name` matches your device
- Check system clock and time zone settings

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit changes
4. Push to the branch
5. Create a Pull Request

## License

GNU General Public License v3.0 (GPLv3)
