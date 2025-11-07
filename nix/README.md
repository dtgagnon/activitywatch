# Nix Configuration

This directory contains the Nix expressions for building and developing the ActivityWatch LLM Worker.

## Files

### `shell.nix`

Development shell configuration with all dependencies needed for development:
- Python 3.11 with Poetry
- Rust toolchain (for aw-server-rust)
- Qt libraries (for aw-qt)
- Node.js (for web UI)
- Development tools (pyright, ruff)

**Usage:**

```bash
# Enter development shell
nix-shell nix/shell.nix

# Or with flakes
nix develop
```

### `package.nix`

Package derivation for the `aw-llm-worker` application. Builds a proper Nix package that can be:
- Installed system-wide
- Used in NixOS configurations
- Deployed as a systemd service

**Usage:**

```bash
# Build the package
nix build .#aw-llm-worker

# Run the package
nix run .#aw-llm-worker -- --help

# Install to profile
nix profile install .#aw-llm-worker
```

## Integration with flake.nix

The root `flake.nix` imports these files to provide:

- **Development shell**: `nix develop` → uses `shell.nix`
- **Package**: `nix build` → uses `package.nix`
- **App**: `nix run` → runs `aw-sorter` CLI

## NixOS Module (Future)

For NixOS system integration, create a module file here that:
- Defines a systemd service for `aw-llm-worker`
- Manages configuration via NixOS options
- Handles automatic startup and restarts

Example service structure:

```nix
# nix/module.nix (future)
{ config, lib, pkgs, ... }:

{
  options.services.aw-llm-worker = {
    enable = lib.mkEnableOption "ActivityWatch LLM Worker";

    config = lib.mkOption {
      type = lib.types.path;
      description = "Path to config.yaml";
    };

    # ... more options
  };

  config = lib.mkIf config.services.aw-llm-worker.enable {
    systemd.user.services.aw-llm-worker = {
      # ... service definition
    };
  };
}
```

## Dependencies

The package has two types of dependencies:

1. **External Python packages** (from nixpkgs):
   - requests, pyyaml, click
   - openai (for OpenAI API support)
   - watchdog (config hot-reload)
   - pydantic (data validation)
   - sqlalchemy (caching)

2. **Local ActivityWatch packages**:
   - aw-client (from `activitywatch_src/aw-client`)
   - aw-core (from `activitywatch_src/aw-core`)

These are currently built from the local source tree.

## Development Workflow

1. **Setup environment:**
   ```bash
   nix develop
   poetry install
   ```

2. **Run in development:**
   ```bash
   poetry run aw-sorter run --since 60
   ```

3. **Build production package:**
   ```bash
   nix build .#aw-llm-worker
   ./result/bin/aw-sorter --help
   ```

4. **Test package:**
   ```bash
   nix run .#aw-llm-worker -- stats
   ```
