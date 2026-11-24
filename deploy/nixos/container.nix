# SPDX-License-Identifier: EUPL-1.2
# `services.veilleur-container`: the watch server in a systemd-nspawn container with private users and a private
# network, reaching the Internet only (spec ENF-01, ENF-03b).
{ serviceModule }:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.veilleur-container;
  inherit (lib)
    mkEnableOption
    mkIf
    mkMerge
    mkOption
    optional
    optionalAttrs
    optionals
    types
    ;

  name = "veilleur";
  interface = "ve-${name}";
  unit = "container@${name}.service";
  containerRoot = "/var/lib/nixos-containers/${name}";
  secretsDir = "/run/veilleur-secrets";
  useCaddy = cfg.proxy == "caddy";
  builtinNtfy = cfg.ntfy.mode == "builtin";

  # Files of the host handed to the container as systemd credentials: its private users cannot read host files.
  credentials = lib.filterAttrs (_: path: path != null) {
    ntfy-token = cfg.ntfy.tokenFile;
    ntfy-client-token = cfg.ntfy.clientTokenFile;
    webhook-key = cfg.webhook.keyFile;
  };
  secretPath = id: if credentials ? ${id} then "${secretsDir}/${id}" else null;

  forwardedTcp = optionals useCaddy (
    [
      80
      443
    ]
    ++ optional (builtinNtfy && cfg.ntfy.host == null) 8443
  );
  forwardedUdp = optionals useCaddy ([ 443 ] ++ optional (builtinNtfy && cfg.ntfy.host == null) 8443);

  # Everything that is not the public Internet (ES-08: the second barrier, behind the HTTP client's guard).
  blockedIpv4 = [
    "0.0.0.0/8"
    "10.0.0.0/8"
    "100.64.0.0/10"
    "127.0.0.0/8"
    "169.254.0.0/16"
    "172.16.0.0/12"
    "192.0.0.0/24"
    "192.0.2.0/24"
    "192.168.0.0/16"
    "198.18.0.0/15"
    "198.51.100.0/24"
    "203.0.113.0/24"
    "224.0.0.0/4"
    "240.0.0.0/4"
  ];

  rules = ''
    set blocked_ipv4 {
      type ipv4_addr
      flags interval
      elements = { ${lib.concatStringsSep ", " blockedIpv4} }
    }

    chain forward {
      type filter hook forward priority filter - 10; policy accept;
      iifname "${interface}" ct state established,related accept
      iifname "${interface}" meta nfproto ipv6 drop
      iifname "${interface}" ip daddr @blocked_ipv4 drop
      iifname "${interface}" tcp dport 25 drop
    }

    chain input {
      type filter hook input priority filter - 10; policy accept;
      iifname "${interface}" ct state established,related accept
      iifname "${interface}" drop
    }
  '';

  ruleset = pkgs.writeText "veilleur-container.nft" ''
    table inet veilleur_container {}
    delete table inet veilleur_container
    table inet veilleur_container {
    ${rules}
    }
  '';

  # Web servers of nixpkgs that take ports 80 and 443 on the host (ENF-03b).
  conflictingServers = lib.filter (server: lib.attrByPath [ server "enable" ] false config.services) [
    "caddy"
    "nginx"
    "httpd"
    "traefik"
    "haproxy"
    "lighttpd"
    "envoy"
  ];

  # The public ports forwarded to the container, against those the rest of the configuration declares (ENF-03b).
  portConflicts = (import ./ports.nix { inherit config lib; }).conflicts {
    tcp = forwardedTcp;
    udp = forwardedUdp;
    ownAddress = cfg.containerAddress;
  };

  # Behind the host's front end, the services have to be reachable on the container's private link.
  internalAddress = if useCaddy then "127.0.0.1" else cfg.containerAddress;

  admin = pkgs.writeShellScriptBin "veilleur-admin" ''
    exec ${config.systemd.package}/bin/systemd-run --quiet --pipe --wait --machine=${name} \
      /run/current-system/sw/bin/veilleur-admin "$@"
  '';

  snapshot = pkgs.writeShellScript "veilleur-container-snapshot" ''
    exec ${config.systemd.package}/bin/systemctl --machine=${name} start --wait veilleur-snapshot.service
  '';
in
{
  options.services.veilleur-container = {
    enable = mkEnableOption "the Veilleur watch server in an isolated container";

    publicHost = mkOption {
      type = types.nullOr types.str;
      default = null;
      example = "watch.example.org";
      description = "Name under which members reach the server. It must have no AAAA record: see `noAaaaRecord`.";
    };

    noAaaaRecord = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Confirms that `publicHost` has no AAAA record. Ports are forwarded to the container in IPv4 only:
        with an AAAA record, Let's Encrypt and IPv6 clients would fail.
      '';
    };

    externalInterface = mkOption {
      type = types.nullOr types.str;
      default = null;
      example = "eth0";
      description = "The host's interface towards the Internet.";
    };

    hostAddress = mkOption {
      type = types.str;
      default = "10.233.50.1";
      description = "Address of the host on the container's private link.";
    };

    containerAddress = mkOption {
      type = types.str;
      default = "10.233.50.2";
      description = "Address of the container on its private link.";
    };

    nameservers = mkOption {
      type = types.listOf types.str;
      default = [
        "9.9.9.9"
        "149.112.112.112"
      ];
      description = "Public DNS resolvers of the container, which may reach neither the host nor private networks.";
    };

    memoryMax = mkOption {
      type = types.str;
      default = "1G";
      description = "Memory ceiling of the container (systemd `MemoryMax`).";
    };

    tasksMax = mkOption {
      type = types.ints.positive;
      default = 512;
      description = "Ceiling on the container's processes and threads (systemd `TasksMax`).";
    };

    proxy = mkOption {
      type = types.enum [
        "caddy"
        "external"
      ];
      default = "caddy";
      description = ''
        `caddy` runs the TLS front end in the container and forwards ports 80 and 443 to it. `external` leaves TLS
        to the host's reverse proxy, which reaches `containerAddress` on `port`.
      '';
    };

    port = mkOption {
      type = types.port;
      default = 8470;
      description = "Internal port of the HTTP service.";
    };

    acmeEmail = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Contact address for the Let's Encrypt account.";
    };

    internalTls = mkOption {
      type = types.bool;
      default = false;
      description = "Use Caddy's local certificate authority instead of Let's Encrypt (tests, private networks).";
    };

    language = mkOption {
      type = types.enum [
        "en"
        "fr"
      ];
      default = "en";
      description = "Language of the server's messages.";
    };

    plugins = mkOption {
      type = types.listOf types.package;
      default = [ ];
      description = "Python packages built for Python 3.12 that declare Veilleur entry points.";
    };

    roundSchedule = mkOption {
      type = types.str;
      default = "daily";
      description = "When the collection round runs (systemd calendar event).";
    };

    snapshotSchedule = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "When to refresh the consistent copy of the state (systemd calendar event).";
    };

    subscriptions = mkOption {
      type = types.listOf (pkgs.formats.toml { }).type;
      default = [ ];
      description = "Team subscriptions, as in the `[[subscriptions]]` tables of the configuration file.";
    };

    ntfy = {
      mode = mkOption {
        type = types.enum [
          "builtin"
          "external"
          "none"
        ];
        default = "builtin";
        description = "Notifications: a ntfy server in the container, an existing one, or none.";
      };

      host = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Name of the built-in ntfy server. Without one, it is served on port 8443 of `publicHost`.";
      };

      url = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Where the server publishes (mode = \"external\"). It must be reachable from the Internet side.";
      };

      publicUrl = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "The https address given in pairing codes.";
      };

      tokenFile = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "File of the host holding the token used to publish.";
      };

      clientTokenFile = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "File of the host holding the token given in pairing codes.";
      };
    };

    webhook = {
      url = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Address that receives the signed notification, if any.";
      };

      keyFile = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "File of the host holding the HMAC key. Default: generated in the container's state directory.";
      };
    };

    backupPaths = mkOption {
      type = types.listOf types.str;
      readOnly = true;
      # The container only exists once enabled, and a host may wire its backup to this option unconditionally.
      default = lib.optionals cfg.enable (
        map (path: "${containerRoot}${path}") config.containers.${name}.config.services.veilleur.backupPaths
      );
      defaultText = lib.literalExpression ''[ "${containerRoot}/var/lib/veilleur/snapshot" ]'';
      description = "Paths for the host's backup. Start `veilleur-container-snapshot.service` first.";
    };
  };

  config = mkIf cfg.enable (mkMerge [
    {
      assertions = [
        {
          assertion = cfg.publicHost != null;
          message = "services.veilleur-container.publicHost must be set.";
        }
        {
          assertion = cfg.noAaaaRecord;
          message = ''
            services.veilleur-container forwards ports in IPv4 only: publicHost must have no AAAA record, or
            Let's Encrypt and IPv6 clients will fail. Remove the record, then set noAaaaRecord = true.
          '';
        }
        {
          assertion = !useCaddy || cfg.externalInterface != null;
          message = "services.veilleur-container.externalInterface is required with proxy = \"caddy\".";
        }
        {
          # The host may import this module alone.
          assertion = !(lib.attrByPath [ "services" "veilleur" "enable" ] false config);
          message = "services.veilleur and services.veilleur-container cannot be enabled together.";
        }
        {
          assertion = !useCaddy || conflictingServers == [ ];
          message = ''
            services.veilleur-container.proxy = "caddy" forwards ports 80 and 443 to the container, also used by:
            ${lib.concatStringsSep ", " conflictingServers}. Use proxy = "external" and add Veilleur to that front end.
          '';
        }
        {
          assertion = portConflicts == [ ];
          message =
            "services.veilleur-container forwards ports that the configuration also declares: "
            + lib.concatStringsSep ", " portConflicts
            + ".";
        }
      ];

      containers.${name} = {
        autoStart = true;
        privateNetwork = true;
        privateUsers = "pick";
        inherit (cfg) hostAddress;
        localAddress = cfg.containerAddress;
        extraFlags = lib.mapAttrsToList (id: path: "--load-credential=${id}:${path}") credentials;

        config = {
          imports = [ serviceModule ];

          services.veilleur = {
            enable = true;
            inherit (cfg)
              publicHost
              proxy
              port
              acmeEmail
              internalTls
              language
              plugins
              roundSchedule
              snapshotSchedule
              subscriptions
              ;
            listenAddress = internalAddress;
            ntfy = {
              inherit (cfg.ntfy)
                mode
                host
                url
                publicUrl
                ;
              listenAddress = internalAddress;
              tokenFile = secretPath "ntfy-token";
              clientTokenFile = secretPath "ntfy-client-token";
            };
            webhook = {
              inherit (cfg.webhook) url;
              keyFile = secretPath "webhook-key";
            };
          };

          networking.useHostResolvConf = lib.mkForce false;
          networking.nameservers = cfg.nameservers;
          networking.firewall.allowedTCPPorts = optionals (!useCaddy) ([ cfg.port ] ++ optional builtinNtfy 2586);

          systemd.services = optionalAttrs (credentials != { }) {
            veilleur-credentials = {
              description = "Secrets given by the host to Veilleur";
              before = [
                "veilleur.service"
                "veilleur-round.service"
              ];
              requiredBy = [
                "veilleur.service"
                "veilleur-round.service"
              ];
              serviceConfig = {
                Type = "oneshot";
                RemainAfterExit = true;
                ImportCredential = builtins.attrNames credentials;
                RuntimeDirectory = "veilleur-secrets";
                RuntimeDirectoryMode = "0750";
                RuntimeDirectoryPreserve = true;
                Group = "veilleur";
                UMask = "0027";
                ExecStart = pkgs.writeShellScript "veilleur-credentials" ''
                  set -eu
                  for id in ${lib.escapeShellArgs (builtins.attrNames credentials)}; do
                    ${pkgs.coreutils}/bin/install -m 0640 -g veilleur "$CREDENTIALS_DIRECTORY/$id" ${secretsDir}/"$id"
                  done
                '';
              };
            };
          };

          system.stateVersion = "26.05";
        };
      };

      systemd.services."container@${name}" = {
        requires = [ "veilleur-container-firewall.service" ];
        after = [ "veilleur-container-firewall.service" ];
        serviceConfig = {
          MemoryMax = cfg.memoryMax;
          TasksMax = lib.mkForce cfg.tasksMax;
        };
      };

      # Loaded apart from `networking.nftables`, so that the host keeps the firewall backend it has chosen.
      systemd.services.veilleur-container-firewall = {
        description = "Outbound firewall of the Veilleur container";
        wantedBy = [ "multi-user.target" ];
        before = [ unit ];
        after = optional config.networking.nftables.enable "nftables.service";
        # Reloading the host's nftables flushes every table: this one has to come back with it.
        partOf = optional config.networking.nftables.enable "nftables.service";
        unitConfig.ReloadPropagatedFrom = optional config.networking.nftables.enable "nftables.service";
        restartTriggers = [ ruleset ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          ExecStart = "${pkgs.nftables}/bin/nft -f ${ruleset}";
          ExecReload = "${pkgs.nftables}/bin/nft -f ${ruleset}";
          ExecStop = "${pkgs.nftables}/bin/nft delete table inet veilleur_container";
        };
      };

      systemd.services.veilleur-container-snapshot = {
        description = "Consistent copy of the state of the Veilleur container";
        after = [ unit ];
        requires = [ unit ];
        serviceConfig = {
          Type = "oneshot";
          ExecStart = snapshot;
        };
      };

      environment.systemPackages = [ admin ];

      networking.nat = {
        enable = true;
        internalInterfaces = [ interface ];
        externalInterface = lib.mkIf (cfg.externalInterface != null) cfg.externalInterface;
        forwardPorts =
          map (port: {
            sourcePort = port;
            proto = "tcp";
            destination = "${cfg.containerAddress}:${toString port}";
          }) forwardedTcp
          ++ map (port: {
            sourcePort = port;
            proto = "udp";
            destination = "${cfg.containerAddress}:${toString port}";
          }) forwardedUdp;
      };
    }
  ]);
}
