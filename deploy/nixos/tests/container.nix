# SPDX-License-Identifier: EUPL-1.2
# The isolated container: private users, limits, and an outbound firewall that lets the Internet through only.
{
  pkgs,
  containerModule,
  # Whether the host uses nftables as its firewall backend, whose reload flushes every table.
  nftables ? false,
}:
let
  plugin = import ./plugin.nix { inherit pkgs; };
  # Not a reserved range: in this test it stands for the Internet.
  internetAddress = "45.33.0.10";
  hostInternetAddress = "45.33.0.1";
  tailnetAddress = "100.64.0.10";
  lanAddress = "192.168.77.10";
  listeners = pkgs.writeShellScript "listeners" ''
    for port in 25 8080; do
      ${pkgs.python312}/bin/python3 -m http.server --bind 0.0.0.0 "$port" &
    done
    wait
  '';
in
pkgs.testers.runNixOSTest {
  name = if nftables then "veilleur-container-nftables" else "veilleur-container";

  nodes.outside = {
    networking.firewall.enable = false;
    networking.interfaces.eth1.ipv4.addresses = [
      {
        address = internetAddress;
        prefixLength = 24;
      }
      {
        address = tailnetAddress;
        prefixLength = 10;
      }
      {
        address = lanAddress;
        prefixLength = 24;
      }
    ];
    systemd.services.listeners = {
      wantedBy = [ "multi-user.target" ];
      serviceConfig.ExecStart = listeners;
    };
  };

  nodes.host = {
    imports = [ containerModule ];
    networking.nftables.enable = nftables;
    virtualisation.memorySize = 2048;
    # Private users need an idmapped /nix/store, which the 9p share of the test VM cannot provide.
    virtualisation.useNixStoreImage = true;
    virtualisation.writableStore = false;
    # Bound into every NixOS container, and absent from a VM with a read-only store.
    systemd.tmpfiles.rules = [
      "d /nix/var/nix/db 0755 root root"
      "d /nix/var/nix/daemon-socket 0755 root root"
    ];
    networking.interfaces.eth1.ipv4.addresses = [
      {
        address = hostInternetAddress;
        prefixLength = 24;
      }
      {
        address = "100.64.0.1";
        prefixLength = 10;
      }
      {
        address = "192.168.77.1";
        prefixLength = 24;
      }
    ];
    networking.firewall.allowedTCPPorts = [ 9000 ];
    environment.etc."veilleur-vm/webhook.key".text = "fictional-webhook-key";
    systemd.services.host-listener = {
      wantedBy = [ "multi-user.target" ];
      serviceConfig.ExecStart = "${pkgs.python312}/bin/python3 -m http.server --bind 0.0.0.0 9000";
    };
    services.veilleur-container = {
      enable = true;
      publicHost = "watch.example.org";
      noAaaaRecord = true;
      externalInterface = "eth1";
      internalTls = true;
      memoryMax = "900M";
      tasksMax = 400;
      plugins = [ plugin ];
      ntfy.mode = "none";
      webhook = {
        url = "https://hooks.example.org/veilleur";
        keyFile = "/etc/veilleur-vm/webhook.key";
      };
    };
  };

  testScript = ''
    start_all()
    outside.wait_for_unit("listeners.service")
    outside.wait_for_open_port(8080)
    host.wait_for_unit("container@veilleur.service")
    host.wait_until_succeeds("systemctl --machine=veilleur is-active veilleur.service", timeout=180)

    curl = "${pkgs.curl}/bin/curl --silent --output /dev/null --max-time 5"

    def inside(command):
        return f"systemd-run --quiet --pipe --wait --machine=veilleur {command}"

    with subtest("the container has private users and its limits"):
        # The container's root is an unprivileged user of the host.
        leader = host.succeed("machinectl show veilleur --property=Leader --value").strip()
        host.succeed(f"test \"$(stat -c %u /proc/{leader})\" -gt 65535")
        host.succeed("systemctl show container@veilleur.service | grep -qx MemoryMax=943718400")
        host.succeed("systemctl show container@veilleur.service | grep -qx TasksMax=400")

    with subtest("the Internet is reachable"):
        host.succeed(inside(f"{curl} http://${internetAddress}:8080/"))

    with subtest("port 25 is closed"):
        host.fail(inside(f"{curl} http://${internetAddress}:25/"))

    with subtest("private networks, the tailnet and the host are not reachable"):
        host.fail(inside(f"{curl} http://${lanAddress}:8080/"))
        host.fail(inside(f"{curl} http://${tailnetAddress}:8080/"))
        host.succeed("curl --silent --output /dev/null --max-time 5 http://127.0.0.1:9000/")
        host.fail(inside(f"{curl} http://10.233.50.1:9000/"))
        host.fail(inside(f"{curl} http://${hostInternetAddress}:9000/"))

    ${pkgs.lib.optionalString nftables ''
      with subtest("the rules survive a reload of the host's firewall"):
          host.succeed("systemctl reload nftables.service")
          host.wait_until_succeeds("nft list table inet veilleur_container", timeout=30)
          host.fail(inside(f"{curl} http://${lanAddress}:8080/"))
    ''}
    with subtest("the secret given by the host is readable by the service only"):
        host.succeed(inside("/run/current-system/sw/bin/runuser -u veilleur -- /run/current-system/sw/bin/test -s /run/veilleur-secrets/webhook-key"))
        host.fail(inside("/run/current-system/sw/bin/runuser -u nobody -- /run/current-system/sw/bin/cat /run/veilleur-secrets/webhook-key"))

    with subtest("administration from the host, and a consistent copy"):
        host.succeed("veilleur-admin pairing new --label 'desk 5' | grep -q VEIL1:")
        host.succeed("systemctl start veilleur-container-snapshot.service")
        host.succeed("test -s /var/lib/nixos-containers/veilleur/var/lib/veilleur/snapshot/veilleur.db")
  '';
}
