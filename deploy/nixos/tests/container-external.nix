# SPDX-License-Identifier: EUPL-1.2
# The container behind the host's own front end: the API and the built-in ntfy are reachable from the host (ENF-03b).
{
  pkgs,
  containerModule,
}:
pkgs.testers.runNixOSTest {
  name = "veilleur-container-external";

  nodes.host = {
    imports = [ containerModule ];
    virtualisation.memorySize = 2048;
    # Private users need an idmapped /nix/store, which the 9p share of the test VM cannot provide.
    virtualisation.useNixStoreImage = true;
    virtualisation.writableStore = false;
    # Bound into every NixOS container, and absent from a VM with a read-only store.
    systemd.tmpfiles.rules = [
      "d /nix/var/nix/db 0755 root root"
      "d /nix/var/nix/daemon-socket 0755 root root"
    ];
    services.veilleur-container = {
      enable = true;
      publicHost = "watch.example.org";
      noAaaaRecord = true;
      proxy = "external";
      ntfy.publicUrl = "https://ntfy.example.org";
    };
  };

  testScript = ''
    start_all()
    host.wait_for_unit("container@veilleur.service")
    host.wait_until_succeeds("systemctl --machine=veilleur is-active veilleur.service", timeout=180)
    host.wait_until_succeeds("systemctl --machine=veilleur is-active ntfy-sh.service", timeout=180)

    curl = "${pkgs.curl}/bin/curl --silent --max-time 5"

    with subtest("the host's front end reaches the API and ntfy"):
        host.wait_until_succeeds(f"{curl} --output /dev/null http://10.233.50.2:8470/", timeout=60)
        host.wait_until_succeeds(f"{curl} http://10.233.50.2:2586/v1/health | grep -q healthy", timeout=60)

    with subtest("ntfy still refuses anonymous clients"):
        host.succeed(
            f"test \"$({curl} --output /dev/null --write-out '%{{http_code}}' -d hello http://10.233.50.2:2586/vmtopic)\" = 403"
        )
  '';
}
