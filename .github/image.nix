let
  flake = builtins.getFlake (toString ../.);
  system = builtins.currentSystem;
  mkDockerImage = flake.lib.${system}.dockerImage;

  githubRepository = builtins.getEnv "GITHUB_REPOSITORY";
in
mkDockerImage {
  extraConfig = {
    Labels = {
      "org.opencontainers.image.source" = "https://github.com/${githubRepository}";
      "org.opencontainers.image.description" = "A personal finance management system built with Beancount and Fava, providing automated transaction imports and classification.";
      "org.opencontainers.image.licenses" = "MIT";
    };
  };
}
