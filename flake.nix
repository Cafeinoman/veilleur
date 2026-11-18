# SPDX-License-Identifier: EUPL-1.2
{
  description = "Veilleur: self-hosted watch server with signed and encrypted reports";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
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

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      built = forAllSystems (
        system:
        import ./deploy/nixos/python.nix {
          inherit uv2nix pyproject-nix pyproject-build-systems;
          pkgs = nixpkgs.legacyPackages.${system};
          workspaceRoot = ./.;
        }
      );
      serviceModule = import ./deploy/nixos/module.nix { packages = self.packages; };
      containerModule = {
        imports = [ (import ./deploy/nixos/container.nix { inherit serviceModule; }) ];
      };
    in
    {
      packages = forAllSystems (system: {
        default = built.${system}.server;
        veilleur = built.${system}.server;
        veilleur-receive = built.${system}.receiver;
      });

      nixosModules = {
        default = serviceModule;
        container = containerModule;
      };

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.uv
              pkgs.python312
              pkgs.gh
            ];
            env = {
              UV_PYTHON_DOWNLOADS = "never";
              UV_PYTHON = "${pkgs.python312}/bin/python3.12";
            };
          };
        }
      );

      # The virtual machines need KVM: they run on x86_64 only, in the CI and locally.
      checks.x86_64-linux =
        let
          pkgs = nixpkgs.legacyPackages.x86_64-linux;
          receiver = built.x86_64-linux.receiver;
        in
        {
          vm-full = import ./deploy/nixos/tests/full.nix { inherit pkgs serviceModule receiver; };
          vm-external = import ./deploy/nixos/tests/external.nix { inherit pkgs serviceModule receiver; };
          vm-container = import ./deploy/nixos/tests/container.nix { inherit pkgs containerModule; };
          vm-container-nftables = import ./deploy/nixos/tests/container.nix {
            inherit pkgs containerModule;
            nftables = true;
          };
          vm-container-external = import ./deploy/nixos/tests/container-external.nix {
            inherit pkgs containerModule;
          };
          vm-fallback = import ./deploy/nixos/tests/fallback.nix {
            inherit pkgs;
            server = built.x86_64-linux.server;
          };
          eval = import ./deploy/nixos/tests/eval.nix {
            inherit
              nixpkgs
              self
              serviceModule
              containerModule
              ;
          };
        };
    };
}
