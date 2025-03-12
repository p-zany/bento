{
  description = "Bento - A personal finance management system built with Beancount and Fava, providing automated transaction imports and classification.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    devenv.url = "github:cachix/devenv";
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, devenv, flake-utils, nixpkgs, ... } @ inputs:
    flake-utils.lib.eachDefaultSystem (system:
      let
        inherit (nixpkgs) lib;
        pkgs = import nixpkgs { inherit system; };
        workspace = inputs.uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

        overlay = workspace.mkPyprojectOverlay {
          sourcePreference = "wheel";
        };

        python = pkgs.python313;

        pythonSet =
          (pkgs.callPackage inputs.pyproject-nix.build.packages {
            inherit python;
          }).overrideScope
            (lib.composeManyExtensions [
              inputs.pyproject-build-systems.overlays.default
              overlay
            ]);

        # Add file/libmagic dependency
        bentoEnv = pythonSet.mkVirtualEnv "bento-env" workspace.deps.default;
        bento = pkgs.symlinkJoin {
          name = "bento";
          paths = [
            bentoEnv
            pkgs.file  # Provides libmagic
          ];
        };

        dockerImage = { extraConfig ? {} }: pkgs.dockerTools.buildImage {
          name = "bento";
          tag = "latest";
          copyToRoot = pkgs.buildEnv {
            name = "root";
            paths = [
              pkgs.bash
              pkgs.coreutils
              pkgs.file  # Provides libmagic in the Docker image
              bento
              (pkgs.runCommand "bento-importer" {} ''
                mkdir -p $out/bento
                cp -r ${./.}/bento/* $out/bento
              '')
            ];
          };

          config = {
            Entrypoint = [ "${bento}/bin/fava" ];
            ExposedPorts = {
              "5000/tcp" = {};
            };
            Volumes = {
              "/data" = {};
            };
            WorkingDir = "/data";
            Env = [
              "PYTHONPATH=${bento}/${pkgs.python312.sitePackages}"
            ];
          } // extraConfig;
        };
      in {
        packages = {
          default = bento;
          bento-image = dockerImage { extraConfig = {}; };
          devenv-up = self.devShells.${system}.default.config.procfileScript;
          devenv-test = self.devShells.${system}.default.config.test;
        };

        devShells.default = devenv.lib.mkShell {
          inherit inputs pkgs;
          modules = [
            ({ pkgs, config, ... }: {
              packages = with pkgs; [
                file
                sqlite
              ];

              languages.python = {
                enable = true;
                package = pkgs.python313;
                uv = {
                  enable = true;
                  sync.enable = true;
                };
              };

              pre-commit.hooks = {
                deadnix = {
                  enable = true;
                  settings = {
                    edit = true;
                    noLambdaPatternNames = true;
                  };
                };
                ruff.enable = true;
                ruff-format.enable = true;
                trim-trailing-whitespace.enable = true;
              };
            })
          ];
        };

        apps = {
          default = {
            type = "app";
            program = "${self.packages.default}/bin/bento";
          };
        };
      }
    );
}
