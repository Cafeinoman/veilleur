# SPDX-License-Identifier: EUPL-1.2
# The collector of the NixOS tests, packaged like any plugin given to `services.veilleur.plugins`.
{ pkgs }:
pkgs.python312Packages.buildPythonPackage {
  pname = "veilleur-vm-source";
  version = "0.1.0";
  pyproject = true;
  src = ./plugin;
  build-system = [ pkgs.python312Packages.hatchling ];
  # Veilleur itself comes from the environment the plugin is added to.
  dontCheckRuntimeDeps = true;
  doCheck = false;
}
