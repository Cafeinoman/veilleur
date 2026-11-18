# SPDX-License-Identifier: EUPL-1.2
# Veilleur with proxy = "external", behind a Caddy that belongs to the host (cahier ENF-03b, ENF-06).
{
  pkgs,
  serviceModule,
  receiver,
}:
let
  host = "watch.example.org";
  plugin = import ./plugin.nix { inherit pkgs; };
in
pkgs.testers.runNixOSTest {
  name = "veilleur-external";

  nodes.server = {
    imports = [ serviceModule ];
    environment.etc."veilleur-vm/source.txt".text = "alpha\n";
    networking.firewall.allowedTCPPorts = [ 443 ];

    # The host's own front end, with the block given in the administration guide.
    services.caddy = {
      enable = true;
      virtualHosts.${host} = {
        logFormat = null;
        extraConfig = ''
          tls internal
          reverse_proxy 127.0.0.1:8470 {
            header_up -X-Forwarded-For
          }
        '';
      };
      virtualHosts."other.example.org".extraConfig = ''
        tls internal
        respond "another site of the host"
      '';
    };

    services.veilleur = {
      enable = true;
      publicHost = host;
      proxy = "external";
      ntfy.mode = "none";
      plugins = [ plugin ];
      subscriptions = [
        {
          name = "vm_team";
          collector = "vm_source";
          params.path = "/etc/veilleur-vm/source.txt";
          pairings = [ "desk 4" ];
          frequency = "every_round";
        }
      ];
    };
  };

  nodes.member =
    { nodes, ... }:
    {
      environment.systemPackages = [ receiver ];
      networking.hosts.${nodes.server.networking.primaryIPAddress} = [ host ];
    };

  testScript = ''
    import shlex

    start_all()
    server.wait_for_unit("veilleur.service")
    server.wait_for_unit("caddy.service")
    server.wait_for_open_port(443)

    with subtest("Veilleur adds nothing to the host's front end"):
        server.fail("systemctl cat ntfy-sh.service")
        server.succeed("ss -ltnH 'sport = :8470' | grep -q '127.0.0.1:8470'")

    code = next(
        line
        for line in server.succeed("veilleur-admin pairing new --label 'desk 4'").splitlines()
        if line.startswith("VEIL1:")
    )
    server.succeed("systemctl start veilleur-round.service")

    root = server.succeed("cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt")
    member.succeed(f"cat > /tmp/caddy-root.crt <<'CERT'\n{root}\nCERT")
    env = "SSL_CERT_FILE=/tmp/caddy-root.crt"
    member.succeed(f"printf '%s\\n' {shlex.quote(code)} | {env} veilleur-receive --state-dir /root/r pair")
    member.succeed(f"{env} veilleur-receive --state-dir /root/r pull --folder /root/reports")
    member.succeed("grep -rq alpha /root/reports --include=items.jsonl")
  '';
}
