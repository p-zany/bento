{
  description = "Bento - A personal finance management system built with Beancount and Fava, providing automated transaction imports and classification.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        inherit (poetry2nix.lib.mkPoetry2Nix { inherit pkgs; }) mkPoetryEnv;

        bento = mkPoetryEnv {
          projectDir = ./.;
          preferWheels = true;
        };

        dockerImage = { extraConfig ? {} }: pkgs.dockerTools.buildImage {
          name = "bento";
          tag = "latest";
          copyToRoot = pkgs.buildEnv {
            name = "root";
            paths = [
              pkgs.bash
              pkgs.coreutils
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
          default = dockerImage { extraConfig = {}; };
        };

        lib = {
          inherit dockerImage;
        };
      }
    );
}
