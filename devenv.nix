{ config,pkgs, ... }:

{
  name = "bento";

  languages = {
    python = {
      enable = true;
      package = pkgs.python312;
      poetry = {
        enable = true;
        activate.enable = true;
        install.enable = true;
      };
    };
  };

  pre-commit.hooks = {
    black.enable = true;
    isort.enable = true;
    flake8 = {
      enable = true;
      args = [
        "--max-line-length=88" # black default
      ];
    };
  };
}
