# SPDX-License-Identifier: EUPL-1.2
# What the verifier of batch G5 asks of the NixOS modules. Read by tests/verif/test_g5_verif.py.
{ root }:
let
  flake = builtins.getFlake "git+file://${root}";
  inherit (flake.inputs.nixpkgs) lib;

  base = {
    boot.loader.grub.enable = false;
    fileSystems."/" = {
      device = "/dev/vda";
      fsType = "ext4";
    };
    system.stateVersion = "26.05";
  };
  evaluate =
    modules:
    (lib.nixosSystem {
      system = "x86_64-linux";
      modules = [ base ] ++ modules;
    }).config;
  failures = config: map (a: a.message) (lib.filter (a: !a.assertion) config.assertions);

  service = flake.nixosModules.default;
  container = flake.nixosModules.container;
  named = {
    enable = true;
    publicHost = "watch.example.org";
  };
  boxed = named // {
    externalInterface = "eth0";
    noAaaaRecord = true;
  };
  withService =
    settings: extra:
    evaluate [
      service
      extra
      { services.veilleur = named // settings; }
    ];
  withContainer =
    settings: extra:
    evaluate [
      container
      extra
      { services.veilleur-container = boxed // settings; }
    ];
  forward = port: {
    networking.nat = {
      enable = true;
      externalInterface = "eth0";
      forwardPorts = [
        {
          sourcePort = port;
          proto = "tcp";
          destination = "10.1.1.2:${toString port}";
        }
      ];
    };
  };

  plain = withService { } { };
  behindProxy = withContainer {
    proxy = "external";
    ntfy.publicUrl = "https://ntfy.example.org";
  } { };
  inner = behindProxy.containers.veilleur.config;
  units = lib.genAttrs [ "veilleur" "veilleur-round" "veilleur-snapshot" ] (
    name: plain.systemd.services.${name}.serviceConfig
  );
in
{
  report = {
    conflicts = {
      "nginx on 443 (control)" = failures (withService { } { services.nginx.enable = true; });
      "another NAT forward on 443" = failures (withService { } (forward 443));
      "another NAT forward on 443, container" = failures (withContainer { } { networking.nat.forwardPorts = (forward 443).networking.nat.forwardPorts; });
      "an OCI container on 443" = failures (
        withService { } {
          virtualisation.oci-containers.containers.web = {
            image = "example.org/web:1";
            ports = [ "443:443" ];
          };
        }
      );
      "another NAT forward on 8443" = failures (withService { } (forward 8443));
      "nginx on the internal port" = failures (
        withService
          {
            proxy = "external";
            ntfy.mode = "none";
          }
          {
            services.nginx = {
              enable = true;
              virtualHosts.other.listen = [
                {
                  addr = "127.0.0.1";
                  port = 8470;
                }
              ];
            };
          }
      );
    };

    containerBehindProxy = {
      ntfyListen = inner.services.ntfy-sh.settings.listen-http;
      openPorts = inner.networking.firewall.allowedTCPPorts;
      failures = failures behindProxy ++ failures inner;
    };

    wildcards = lib.genAttrs [ "0.0.0.0" "::" "0" "::0" "0:0:0:0:0:0:0:0" ] (
      address: failures (withService { listenAddress = address; } { })
    );

    publicHosts = lib.genAttrs [ "watch.example.org" "192.0.2.10" "2001:db8::1" "watch.example.org:8443" "user@watch.example.org" ] (
      host: failures (withService { publicHost = host; } { })
    );

    hardening = lib.mapAttrs (
      _: unit: {
        inherit (unit)
          User
          UMask
          CapabilityBoundingSet
          AmbientCapabilities
          NoNewPrivileges
          ProtectSystem
          PrivateTmp
          PrivateDevices
          PrivateUsers
          RestrictNamespaces
          SystemCallFilter
          RestrictAddressFamilies
          ;
      }
    ) units;
    secretsUnit = builtins.attrNames plain.systemd.services.veilleur-ntfy-secrets.serviceConfig;

    roundTimer = plain.systemd.timers.veilleur-round.timerConfig.OnCalendar;
    configText = builtins.readFile plain.environment.etc."veilleur/config.toml".source;
    ntfyDefaultAccess = plain.services.ntfy-sh.settings.auth-default-access;
    accessLogs = lib.mapAttrs (_: site: site.logFormat) plain.services.caddy.virtualHosts;

    disabledServiceBackupPaths = (evaluate [ service ]).services.veilleur.backupPaths;
  };

  # The host of the guide (§8) wires its backup to the option, while the example of the guide (§5) stays inert.
  inertHostBackupPaths =
    (evaluate [
      (import (/. + "${root}/deploy/nixos/examples/host-module.nix") {
        veilleur = flake;
        settingsFile = /. + "${root}/deploy/nixos/examples/no-such-settings.nix";
      })
    ]).services.veilleur-container.backupPaths;
}
