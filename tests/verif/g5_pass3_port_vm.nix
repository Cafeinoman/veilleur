# SPDX-License-Identifier: EUPL-1.2
# Third pass of the verifier of batch G5: does a configuration the assertion accepts really start? By hand, with KVM:
#   nix build --offline --impure --no-link -L --expr \
#     'import ./tests/verif/g5_pass3_port_vm.nix { root = "<worktree>"; port = 8443; settings = { ntfy.host = "ntfy.example.org"; }; }'
{
  root,
  port,
  settings ? { },
}:
let
  flake = builtins.getFlake "git+file://${root}";
  pkgs = flake.inputs.nixpkgs.legacyPackages.x86_64-linux;
in
pkgs.testers.runNixOSTest {
  name = "veilleur-verif-pass3-port-${toString port}";

  nodes.server = {
    imports = [ flake.nixosModules.default ];
    virtualisation.memorySize = 1024;
    networking.hosts."127.0.0.1" = [
      "watch.example.org"
      "ntfy.example.org"
    ];
    services.veilleur = {
      enable = true;
      publicHost = "watch.example.org";
      internalTls = true;
      inherit port;
    }
    // settings;
  };

  testScript = ''
    import time

    start_all()
    server.wait_for_unit("multi-user.target")
    time.sleep(45)

    units = "veilleur.service caddy.service"
    print(server.execute(f"systemctl show --property=Id,ActiveState,SubState,NRestarts {units}")[1])
    journal = "journalctl --no-pager --unit=veilleur.service --unit=caddy.service"
    print(server.execute(f"{journal} | grep -iE 'already in use|errno 98' | tail -n 8")[1])

    server.fail(f"{journal} | grep -qiE 'already in use|errno 98'")
    server.succeed("systemctl is-active veilleur.service")
    server.succeed("systemctl is-active caddy.service")
    server.succeed("test \"$(systemctl show --property=NRestarts --value veilleur.service)\" = 0")
    server.succeed("test \"$(systemctl show --property=NRestarts --value caddy.service)\" = 0")
    server.succeed("curl --silent --show-error --max-time 10 --output /dev/null http://127.0.0.1:${toString port}/")
  '';
}
