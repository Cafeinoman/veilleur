# SPDX-License-Identifier: EUPL-1.2
# The units of deploy/systemd, as another distribution would install them (spec ENF-05).
{
  pkgs,
  server,
}:
let
  snapshot = pkgs.runCommand "veilleur-snapshot.sh" { } ''
    install -m 755 ${../../systemd/veilleur-snapshot.sh} "$out"
    patchShebangs "$out"
  '';
  units = pkgs.runCommand "veilleur-fallback-units" { nativeBuildInputs = [ pkgs.systemd ]; } ''
    mkdir -p "$out/lib/systemd/system"
    for unit in veilleur.service veilleur-round.service veilleur-round.timer veilleur-snapshot.service; do
      sed -e 's|/opt/veilleur/env|${server}|' -e 's|/opt/veilleur/veilleur-snapshot.sh|${snapshot}|' \
        ${../../systemd}/"$unit" > "$out/lib/systemd/system/$unit"
    done
  '';
in
pkgs.testers.runNixOSTest {
  name = "veilleur-fallback";

  nodes.machine = {
    users.users.veilleur = {
      isSystemUser = true;
      group = "veilleur";
    };
    users.groups.veilleur = { };
    environment.etc."veilleur/config.toml".text = ''
      state_dir = "/var/lib/veilleur"
      public_url = "https://watch.example.org"
    '';
    environment.systemPackages = [ server ];
    systemd.packages = [ units ];
    systemd.services.veilleur.wantedBy = [ "multi-user.target" ];
    systemd.timers.veilleur-round.wantedBy = [ "timers.target" ];
    systemd.services.veilleur-snapshot.path = [
      pkgs.coreutils
      pkgs.sqlite
    ];
  };

  testScript = ''
    machine.wait_for_unit("veilleur.service")
    machine.wait_for_open_port(8470, "127.0.0.1")
    machine.succeed("systemctl list-timers | grep -q veilleur-round")
    machine.succeed("test \"$(stat -c '%a %U' /var/lib/veilleur)\" = '700 veilleur'")
    machine.succeed("runuser -u veilleur -- veilleur pairing new --label 'desk 6' | grep -q VEIL1:")
    machine.succeed("systemctl start veilleur-round.service")
    machine.succeed("systemctl start veilleur-snapshot.service")
    machine.succeed("test -s /var/lib/veilleur/snapshot/veilleur.db")
    machine.succeed("test -s /var/lib/veilleur/snapshot/signing.key")
    score = machine.succeed("systemd-analyze security --no-pager veilleur.service | tail -n 1")
    assert float(score.split("exposure level for veilleur.service:")[1].split()[0]) <= 2.0, score
  '';
}
