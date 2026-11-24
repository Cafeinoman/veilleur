# SPDX-License-Identifier: EUPL-1.2
# What can be decided without booting a machine: inert modules, assertions, examples (spec ENF-03, ENF-03b).
{
  nixpkgs,
  self,
  serviceModule,
  containerModule,
}:
let
  inherit (nixpkgs) lib;
  pkgs = nixpkgs.legacyPackages.x86_64-linux;

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
  refused = needle: config: lib.any (lib.hasInfix needle) (failures config);
  accepted = config: failures config == [ ];
  built = config: builtins.unsafeDiscardStringContext config.system.build.toplevel.drvPath != "";

  service = settings: evaluate [ serviceModule { services.veilleur = { enable = true; } // settings; } ];
  named = settings: service ({ publicHost = "watch.example.org"; } // settings);
  container =
    settings:
    evaluate [
      containerModule
      {
        services.veilleur-container = {
          enable = true;
          publicHost = "watch.example.org";
          externalInterface = "eth0";
          noAaaaRecord = true;
        }
        // settings;
      }
    ];

  inert = evaluate [
    serviceModule
    containerModule
  ];

  # The service next to something else the host declares.
  withHost =
    host: settings:
    evaluate [
      serviceModule
      host
      {
        services.veilleur = {
          enable = true;
          publicHost = "watch.example.org";
        }
        // settings;
      }
    ];
  natOn443 = {
    networking.nat = {
      enable = true;
      externalInterface = "eth0";
      forwardPorts = [
        {
          sourcePort = 443;
          proto = "tcp";
          destination = "10.1.1.2:443";
        }
      ];
    };
  };

  hostExample =
    settingsFile:
    evaluate [
      (import ../examples/host-module.nix {
        veilleur = self;
        inherit settingsFile;
      })
    ];
  # A complete machine of its own: it brings its file systems and boot loader.
  vpsExample =
    (lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        serviceModule
        ../examples/vps/configuration.nix
      ];
    }).config;

  configText = config: builtins.readFile config.environment.etc."veilleur/config.toml".source;

  checks = {
    "disabled modules add no service" =
      !(inert.systemd.services ? veilleur)
      && !(inert.systemd.services ? "container@veilleur")
      && !(inert.systemd.services ? veilleur-container-firewall);
    "disabled modules add no user, proxy or ntfy" =
      !(inert.users.users ? veilleur) && !inert.services.caddy.enable && !inert.services.ntfy-sh.enable;
    "disabled modules leave the network alone" =
      !inert.networking.nat.enable && inert.networking.firewall.allowedTCPPorts == [ ];
    "disabled modules build" = built inert;

    "publicHost is required" = refused "publicHost" (service { });
    "publicHost takes no scheme" = refused "publicHost" (service { publicHost = "https://watch.example.org"; });
    "a complete service is accepted" = accepted (named { }) && built (named { });
    "a wildcard address is refused" = refused "wildcard" (named { listenAddress = "0.0.0.0"; });

    "another web server conflicts with Caddy" = refused "ports 80 and 443" (
      evaluate [
        serviceModule
        {
          services.nginx.enable = true;
          services.veilleur = {
            enable = true;
            publicHost = "watch.example.org";
          };
        }
      ]
    );
    "another web server is fine behind an external proxy" = accepted (
      evaluate [
        serviceModule
        {
          services.nginx.enable = true;
          services.veilleur = {
            enable = true;
            publicHost = "watch.example.org";
            proxy = "external";
            ntfy.mode = "none";
          };
        }
      ]
    );

    "an external proxy takes no public port" =
      let
        config = named {
          proxy = "external";
          ntfy.mode = "none";
        };
      in
      !config.services.caddy.enable && config.networking.firewall.allowedTCPPorts == [ ];
    "built-in ntfy behind an external proxy needs its address" = refused "ntfy.publicUrl" (
      named { proxy = "external"; }
    );
    "external ntfy needs its addresses" = refused "ntfy.url" (named { ntfy.mode = "external"; });
    "ntfy without a name takes port 8443" = builtins.elem 8443 (named { }).networking.firewall.allowedTCPPorts;
    "ntfy with a name takes no extra port" =
      !(builtins.elem 8443 (named { ntfy.host = "ntfy.example.org"; }).networking.firewall.allowedTCPPorts);
    "no ntfy means no ntfy service" = !(named { ntfy.mode = "none"; }).services.ntfy-sh.enable;

    "Caddy keeps no access log" =
      (named { }).services.caddy.virtualHosts."watch.example.org".logFormat == null
      && (named { }).services.caddy.virtualHosts."watch.example.org:8443".logFormat == null;

    "secrets are given by path" =
      let
        text = configText (named {
          ntfy = {
            mode = "external";
            url = "https://ntfy.example.org";
            publicUrl = "https://ntfy.example.org";
            tokenFile = "/run/secrets/ntfy-publish";
          };
          webhook = {
            url = "https://hooks.example.org/veilleur";
            keyFile = "/run/secrets/webhook";
          };
        });
      in
      lib.hasInfix "/run/secrets/ntfy-publish" text && lib.hasInfix "/run/secrets/webhook" text;

    "backupPaths names the consistent copy" = builtins.elem "/var/lib/veilleur/snapshot" (named { }).services.veilleur.backupPaths;
    "backupPaths names ntfy's state when built in" = builtins.elem "/var/lib/veilleur-ntfy" (named { }).services.veilleur.backupPaths;
    "backupPaths leaves out ntfy when absent" =
      (named { ntfy.mode = "none"; }).services.veilleur.backupPaths == [ "/var/lib/veilleur/snapshot" ];

    "a redirection of a public port conflicts" = refused "443/tcp (networking.nat.forwardPorts)" (
      withHost natOn443 { }
    );
    "an OCI container on a public port conflicts" = refused "443/tcp (virtualisation.oci-containers" (
      withHost { virtualisation.oci-containers.containers.web = { image = "example.org/web:1"; ports = [ "127.0.0.1:443:443" ]; }; } { }
    );
    "an OCI container on another port is fine" = accepted (
      withHost { virtualisation.oci-containers.containers.web = { image = "example.org/web:1"; ports = [ "8080:80" "443" ]; }; } { }
    );
    "a site on the internal port conflicts" = refused "8470/tcp (services.nginx" (
      withHost {
        services.nginx = {
          enable = true;
          virtualHosts.other.listen = [ { addr = "127.0.0.1"; port = 8470; } ];
        };
      } { proxy = "external"; ntfy.mode = "none"; }
    );
    "a site on the same port of another address is fine" = accepted (
      withHost {
        services.nginx = {
          enable = true;
          virtualHosts.other.listen = [ { addr = "192.0.2.10"; port = 8470; } ];
        };
      } { proxy = "external"; ntfy.mode = "none"; }
    );
    "the internal port cannot be a public port of Caddy" =
      refused "public ports of Caddy" (named { port = 443; })
      && refused "public ports of Caddy" (named { port = 8443; })
      && refused "public ports of Caddy" (container { port = 8443; }).containers.veilleur.config;
    "port 8443 is free when ntfy has its own name" = accepted (
      named {
        port = 8443;
        ntfy.host = "ntfy.example.org";
      }
    );
    "port 8443 is free without the built-in ntfy" = accepted (
      named {
        port = 8443;
        ntfy.mode = "none";
      }
    );
    "sshd on a public port conflicts" = refused "443/tcp (services.openssh.ports)" (
      withHost {
        services.openssh = {
          enable = true;
          ports = [ 443 ];
        };
      } { }
    );
    "sshd on its usual port is fine" = accepted (withHost { services.openssh.enable = true; } { });
    "the default port of nginx on the internal port conflicts" = refused "8470/tcp (services.nginx.defaultHTTPListenPort)" (
      withHost {
        services.nginx = {
          enable = true;
          defaultHTTPListenPort = 8470;
          virtualHosts.other = { };
        };
      } { proxy = "external"; ntfy.mode = "none"; }
    );
    "the default port of nginx on another address is fine" = accepted (
      withHost {
        services.nginx = {
          enable = true;
          defaultHTTPListenPort = 8470;
          defaultListenAddresses = [ "192.0.2.10" ];
          virtualHosts.other = { };
        };
      } { proxy = "external"; ntfy.mode = "none"; }
    );
    "the container reports a redirection of a public port" = refused "443/tcp (networking.nat.forwardPorts)" (
      evaluate [
        containerModule
        natOn443
        {
          services.veilleur-container = {
            enable = true;
            publicHost = "watch.example.org";
            externalInterface = "eth0";
            noAaaaRecord = true;
          };
        }
      ]
    );
    "a disabled container lists nothing to back up" = inert.services.veilleur-container.backupPaths == [ ];
    "the built-in ntfy is reachable from the host's front end" =
      let
        config = container {
          proxy = "external";
          ntfy.publicUrl = "https://ntfy.example.org";
        };
        inner = config.containers.veilleur.config;
      in
      accepted config
      && inner.services.ntfy-sh.settings.listen-http == "10.233.50.2:2586"
      && builtins.elem 2586 inner.networking.firewall.allowedTCPPorts;
    "the built-in ntfy stays private behind the container's Caddy" =
      let
        inner = (container { }).containers.veilleur.config;
      in
      inner.services.ntfy-sh.settings.listen-http == "127.0.0.1:2586"
      && !(builtins.elem 2586 inner.networking.firewall.allowedTCPPorts);

    "the container is accepted" = accepted (container { }) && built (container { });
    "the container reminds of the AAAA record" = refused "AAAA" (container { noAaaaRecord = false; });
    "the container needs the external interface" = refused "externalInterface" (container { externalInterface = null; });
    "the container needs publicHost" = refused "publicHost" (container { publicHost = null; });
    "the container has private users" = (container { }).containers.veilleur.privateUsers == "pick";
    "the container has a private network" = (container { }).containers.veilleur.privateNetwork;
    "the container is capped" =
      let
        unit = (container { memoryMax = "800M"; }).systemd.services."container@veilleur".serviceConfig;
      in
      unit.MemoryMax == "800M" && unit.TasksMax == 512;
    "the container refuses a web server of the host" = refused "ports 80 and 443" (
      evaluate [
        containerModule
        {
          services.nginx.enable = true;
          services.veilleur-container = {
            enable = true;
            publicHost = "watch.example.org";
            externalInterface = "eth0";
            noAaaaRecord = true;
          };
        }
      ]
    );
    "both modules cannot be enabled together" = refused "cannot be enabled together" (
      evaluate [
        serviceModule
        containerModule
        {
          services.veilleur = {
            enable = true;
            publicHost = "watch.example.org";
            proxy = "external";
            ntfy.mode = "none";
          };
          services.veilleur-container = {
            enable = true;
            publicHost = "watch.example.org";
            externalInterface = "eth0";
            noAaaaRecord = true;
          };
        }
      ]
    );

    "the host example is inert without its settings" =
      let
        config = hostExample ./does-not-exist.nix;
      in
      !config.services.veilleur-container.enable && built config;
    "the host example works with its settings" =
      let
        config = hostExample ../examples/veilleur-settings.example.nix;
      in
      config.services.veilleur-container.enable && accepted config && built config;
    "the VPS example is accepted" = accepted vpsExample && built vpsExample;
  };

  wrong = builtins.attrNames (lib.filterAttrs (_: passed: !passed) checks);
in
assert lib.assertMsg (wrong == [ ]) "failed: ${lib.concatStringsSep "; " wrong}";
pkgs.runCommand "veilleur-eval-checks" { } ''
  echo ${toString (builtins.length (builtins.attrNames checks))} checks passed > "$out"
''
