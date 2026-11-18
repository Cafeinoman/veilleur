# SPDX-License-Identifier: EUPL-1.2
# Example: a VPS dedicated to Veilleur. Replace the tag, then adapt configuration.nix.
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    veilleur.url = "github:Cafeinoman/veilleur/v0.1.0";
  };

  outputs =
    { nixpkgs, veilleur, ... }:
    {
      nixosConfigurations.veilleur = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [
          veilleur.nixosModules.default
          ./configuration.nix
        ];
      };
    };
}
