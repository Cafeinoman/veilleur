# SPDX-License-Identifier: EUPL-1.2
# Example: Veilleur inside an existing host configuration (cahier ENF-03, ENF-03b).
#
# Copy this file next to your configuration, then import it:
#
#   imports = [ (import ./veilleur/host-module.nix { }) ];
#
# or, when the host is a flake with `inputs.veilleur.url = "github:Cafeinoman/veilleur/<tag>"`:
#
#   imports = [ (import ./veilleur/host-module.nix { veilleur = inputs.veilleur; }) ];
#
# The settings live in a separate file. Without it the module stays inert, so the host configuration evaluates on any
# machine. No secret belongs in that file.
{
  # Set `tag` and `narHash` (`nix flake metadata github:Cafeinoman/veilleur/<tag>` prints the hash).
  tag ? "v0.1.0",
  narHash ? "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
  veilleur ? builtins.getFlake "github:Cafeinoman/veilleur/${tag}?narHash=${narHash}",
  settingsFile ? ./veilleur-settings.nix,
}:
{ lib, ... }:
let
  settings = {
    enable = false;
    publicHost = null;
    ntfyHost = null;
    acmeEmail = null;
    memoryMax = "1G";
    externalInterface = null;
    noAaaaRecord = false;
  }
  // lib.optionalAttrs (builtins.pathExists settingsFile) (import settingsFile);
in
{
  imports = [ veilleur.nixosModules.container ];

  services.veilleur-container = {
    inherit (settings)
      enable
      publicHost
      acmeEmail
      memoryMax
      externalInterface
      noAaaaRecord
      ;
    ntfy.host = settings.ntfyHost;
  };
}
