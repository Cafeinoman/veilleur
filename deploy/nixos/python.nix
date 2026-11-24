# SPDX-License-Identifier: EUPL-1.2
# The Python environment of Veilleur, built from uv.lock by uv2nix with nixpkgs' Python (spec ENF-02).
{
  pkgs,
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
  workspaceRoot,
}:
let
  inherit (pkgs) lib;
  python = pkgs.python312;
  workspace = uv2nix.lib.workspace.loadWorkspace { inherit workspaceRoot; };

  # Wheels, whose hashes are in uv.lock: the source of google-re2 needs re2, abseil and pybind11 at matching versions.
  overlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };

  # The manylinux wheel of google-re2 links against the C++ runtime.
  nativeFixes = final: prev: {
    google-re2 = prev.google-re2.overrideAttrs (old: {
      buildInputs = (old.buildInputs or [ ]) ++ [ pkgs.stdenv.cc.cc.lib ];
    });
  };

  pythonSet =
    (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope
      (
        lib.composeManyExtensions [
          pyproject-build-systems.overlays.wheel
          overlay
          nativeFixes
        ]
      );
in
{
  inherit python pythonSet;
  server = pythonSet.mkVirtualEnv "veilleur-env" { veilleur = [ ]; };
  receiver = pythonSet.mkVirtualEnv "veilleur-receive-env" { veilleur-receive = [ ]; };
}
