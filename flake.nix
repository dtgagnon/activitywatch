{
  description = "TimeGoggles - Time Never Looked so Good";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python311;

        # Python environment with Poetry
        # Using Python 3.11 (project supports 3.8+, but 3.9 is EOL Oct 2025)
        pythonEnv = python.withPackages (ps: with ps; [
          poetry-core
          pip
          setuptools
          virtualenv
        ]);
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            # Python and Poetry
            pythonEnv
            pkgs.poetry

            # Build tools
            gnumake
            git

            # Rust toolchain (optional, for aw-server-rust)
            rustc
            cargo
            rustfmt
            clippy

            # System libraries that may be needed by Python packages
            zlib
            libffi
            openssl

            # For Qt-based components (aw-qt)
            qt5.qtbase
            qt5.qtsvg
            qt5.wrapQtAppsHook

            # Node.js for web UI development
            nodejs

            # Additional development tools
            pyright # Python LSP
            ruff # Python linter/formatter
          ] ++ pkgs.lib.optionals pkgs.stdenv.isLinux [
            # Linux-specific dependencies
            libGL
          ];

          shellHook = ''
            echo "🕐 ActivityWatch development environment"
            echo ""
            echo "Available commands:"
            echo "  make build          - Build all components"
            echo "  make test           - Run tests"
            echo "  make lint           - Run linters"
            echo "  poetry install      - Install Python dependencies"
            echo ""
            echo "Python: $(python --version)"
            echo "Poetry: $(poetry --version)"
            echo "Rust:   $(rustc --version 2>/dev/null || echo 'not available')"
            echo "Node:   $(node --version)"
            echo ""

            # Set up virtual environment location
            export POETRY_VIRTUALENVS_IN_PROJECT=true
            export POETRY_VIRTUALENVS_PATH=".venv"

            # Add local bin to PATH for installed tools
            export PATH="$PWD/.venv/bin:$PATH"

            # For PyQt5 on NixOS
            export QT_QPA_PLATFORM_PLUGIN_PATH="${pkgs.qt5.qtbase.bin}/lib/qt-${pkgs.qt5.qtbase.version}/plugins"
          '';
        };
      }
    );
}
