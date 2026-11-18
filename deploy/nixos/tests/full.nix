# SPDX-License-Identifier: EUPL-1.2
# Complete installation behind Caddy: pairing, round on a local source, fetching a package (cahier ENF-06).
{
  pkgs,
  serviceModule,
  receiver,
}:
let
  host = "watch.example.org";
  ntfyHost = "ntfy.example.org";
  plugin = import ./plugin.nix { inherit pkgs; };
in
pkgs.testers.runNixOSTest {
  name = "veilleur-full";

  nodes.server = {
    imports = [ serviceModule ];
    virtualisation.memorySize = 1024;
    environment.etc."veilleur-vm/source.txt".text = "first second\n";
    environment.systemPackages = [
      pkgs.curl
      pkgs.sqlite
    ];
    networking.hosts."127.0.0.1" = [
      host
      ntfyHost
    ];
    services.veilleur = {
      enable = true;
      publicHost = host;
      internalTls = true;
      language = "fr";
      plugins = [ plugin ];
      ntfy.host = ntfyHost;
      subscriptions = [
        {
          name = "vm_team";
          collector = "vm_source";
          params.path = "/etc/veilleur-vm/source.txt";
          pairings = [ "desk 3" ];
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
    server.wait_for_unit("ntfy-sh.service")
    server.wait_for_open_port(8470, "127.0.0.1")
    server.wait_for_open_port(443)

    with subtest("the service only listens on the loopback address"):
        server.succeed("ss -ltnH 'sport = :8470' | grep -q '127.0.0.1:8470'")
        server.fail("ss -ltnH 'sport = :8470' | grep -vq '127.0.0.1:8470'")

    with subtest("the units are hardened"):
        exposure = server.succeed("systemd-analyze security --no-pager veilleur.service | tail -n 1")
        score = float(exposure.split("exposure level for veilleur.service:")[1].split()[0])
        assert score <= 2.0, f"exposure too high: {exposure}"
        for setting in ("NoNewPrivileges=yes", "UMask=0077", "ProtectSystem=strict"):
            server.succeed(f"systemctl show veilleur.service | grep -qx {shlex.quote(setting)}")
        # What the running process really holds, rather than what the unit file says.
        pid = server.succeed("systemctl show -p MainPID --value veilleur.service").strip()
        for field in ("CapBnd", "CapEff", "CapAmb"):
            server.succeed(f"grep -Eq '^{field}:[[:space:]]+0+$' /proc/{pid}/status")

    with subtest("the state and the secrets are private"):
        server.succeed("test \"$(stat -c '%a %U' /var/lib/veilleur)\" = '700 veilleur'")
        server.succeed("test \"$(stat -c '%a %U %G' /var/lib/veilleur-ntfy/publish.token)\" = '640 root veilleur'")
        server.succeed("test \"$(stat -c '%a %U' /var/lib/veilleur-ntfy/ntfy.env)\" = '600 root'")
        server.fail("grep -rq tk_ /etc/veilleur/")

    with subtest("pairing"):
        output = server.succeed("veilleur-admin pairing new --label 'desk 3'")
        code = next(line for line in output.splitlines() if line.startswith("VEIL1:"))

    with subtest("a round on a local source"):
        server.succeed("systemctl start veilleur-round.service")
        server.succeed("veilleur-admin sources | grep -q vm_source")

    with subtest("the member fetches and checks a package"):
        root = server.succeed("cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt")
        member.succeed(f"cat > /tmp/caddy-root.crt <<'CERT'\n{root}\nCERT")
        env = "SSL_CERT_FILE=/tmp/caddy-root.crt"
        member.succeed(f"printf '%s\\n' {shlex.quote(code)} | {env} veilleur-receive --state-dir /root/r pair")
        member.succeed(f"{env} veilleur-receive --state-dir /root/r pull --folder /root/reports")
        member.succeed("grep -rq first /root/reports --include=items.jsonl")

    with subtest("a change reaches the member as a new package"):
        server.succeed("rm /etc/veilleur-vm/source.txt && echo 'first second third' > /etc/veilleur-vm/source.txt")
        server.succeed("systemctl start veilleur-round.service")
        env = "SSL_CERT_FILE=/tmp/caddy-root.crt"
        member.succeed(f"{env} veilleur-receive --state-dir /root/r pull --folder /root/reports")
        member.succeed("grep -rq third /root/reports --include=items.jsonl")

    with subtest("ntfy refuses anonymous clients and accepts the service's token"):
        ca = "--cacert /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt"
        url = "https://${ntfyHost}/vmtopic"
        server.succeed(f"test \"$(curl -s -o /dev/null -w '%{{http_code}}' {ca} -d hello {url})\" = 403")
        server.succeed(
            f"curl -sf {ca} -H \"Authorization: Bearer $(cat /var/lib/veilleur-ntfy/publish.token)\" -d hello {url}"
        )

    with subtest("no access log, no member address, no secret in the journal"):
        server.fail("ls /var/log/caddy/access-* 2>/dev/null | grep -q .")
        member_ip = member.succeed("ip -4 -o addr show eth1 | awk '{print $4}' | cut -d/ -f1").strip()
        server.fail(f"journalctl -u veilleur -u caddy -u ntfy-sh | grep -qF {shlex.quote(member_ip)}")
        server.fail("journalctl -u veilleur -u veilleur-round | grep -q 'VEIL1:'")

    with subtest("a consistent copy of the state"):
        server.succeed("systemctl start veilleur-snapshot.service")
        server.succeed("test \"$(sqlite3 /var/lib/veilleur/snapshot/veilleur.db 'PRAGMA integrity_check;')\" = ok")
        server.succeed("test -s /var/lib/veilleur/snapshot/signing.key")
  '';
}
