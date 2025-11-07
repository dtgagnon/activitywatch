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
      in
      {
        # Development shell - imported from nix/shell.nix
        devShells.default = import ./nix/shell.nix { inherit pkgs; };

        # Package definition for aw-llm-worker
        packages = {
          aw-llm-worker = python.pkgs.callPackage ./nix/package.nix {
            inherit (python.pkgs)
              buildPythonApplication
              poetry-core
              requests
              pyyaml
              click
              openai
              watchdog
              pydantic
              sqlalchemy;
          };

          default = self.packages.${system}.aw-llm-worker;
        };

        # Apps for easy running
        apps = {
          aw-llm-worker = {
            type = "app";
            program = "${self.packages.${system}.aw-llm-worker}/bin/aw-sorter";
          };

          default = self.apps.${system}.aw-llm-worker;
        };
      }
    );
}
