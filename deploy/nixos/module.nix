# SPDX-License-Identifier: EUPL-1.2
# `services.veilleur`: the watch server on the host (cahier ENF-01 to ENF-04, ENF-03b, ENF-08).
{ packages }:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.services.veilleur;
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

  stateDir = "/var/lib/veilleur";
  snapshotDir = "${stateDir}/snapshot";
  ntfySecretsDir = "/var/lib/veilleur-ntfy";
  ntfyPort = 2586;
  ntfyListen = "${cfg.ntfy.listenAddress}:${toString ntfyPort}";
  toml = pkgs.formats.toml { };

  # Without a value, the assertion below has to be the error the administrator sees.
  publicHost = if cfg.publicHost != null then cfg.publicHost else "public-host-is-not-set.invalid";

  builtinNtfy = cfg.ntfy.mode == "builtin";
  useCaddy = cfg.proxy == "caddy";

  # The address of ntfy behind Caddy: its own name, otherwise port 8443 of the public host.
  ntfySite = if cfg.ntfy.host != null then cfg.ntfy.host else "${publicHost}:8443";
  ntfyPublicUrl = if cfg.ntfy.publicUrl != null then cfg.ntfy.publicUrl else "https://${ntfySite}";

  ntfySettings =
    if builtinNtfy then
      {
        url = "http://${ntfyListen}";
        public_url = ntfyPublicUrl;
        token_file = "${ntfySecretsDir}/publish.token";
        client_token_file = "${ntfySecretsDir}/read.token";
      }
    else if cfg.ntfy.mode == "external" then
      {
        url = cfg.ntfy.url;
        public_url = ntfyPublicUrl;
      }
      // optionalAttrs (cfg.ntfy.tokenFile != null) { token_file = cfg.ntfy.tokenFile; }
      // optionalAttrs (cfg.ntfy.clientTokenFile != null) { client_token_file = cfg.ntfy.clientTokenFile; }
    else
      null;

  settings = {
    state_dir = stateDir;
    public_url = "https://${publicHost}";
    inherit (cfg) language offline port;
    listen = cfg.listenAddress;
    subscriptions = cfg.subscriptions;
  }
  // optionalAttrs (ntfySettings != null) { ntfy = ntfySettings; }
  // optionalAttrs (cfg.webhook.url != null) {
    webhook = {
      inherit (cfg.webhook) url;
    }
    // optionalAttrs (cfg.webhook.keyFile != null) { key_file = cfg.webhook.keyFile; };
  };

  configFile = toml.generate "veilleur-config.toml" settings;

  # Plugins join the read-only environment through the search path: nothing is installed at run time (ENF-02).
  package =
    if cfg.plugins == [ ] then
      cfg.package
    else
      pkgs.symlinkJoin {
        name = "veilleur-with-plugins";
        paths = [ cfg.package ];
        nativeBuildInputs = [ pkgs.makeWrapper ];
        postBuild = ''
          rm "$out/bin/veilleur"
          makeWrapper ${cfg.package}/bin/veilleur "$out/bin/veilleur" \
            --prefix PYTHONPATH : ${pkgs.python312.pkgs.makePythonPath cfg.plugins}
        '';
      };

  # Run the administration command as the service's user, on the same configuration.
  admin = pkgs.writeShellScriptBin "veilleur-admin" ''
    umask 077
    export VEILLEUR_LANG="''${VEILLEUR_LANG:-${cfg.language}}"
    exec ${pkgs.util-linux}/bin/runuser -u veilleur -- ${package}/bin/veilleur "$@"
  '';

  # ENF-04, shared by every unit that runs Veilleur's code or reads its state.
  hardening = {
    User = "veilleur";
    Group = "veilleur";
    StateDirectory = "veilleur";
    StateDirectoryMode = "0700";
    WorkingDirectory = stateDir;
    UMask = "0077";
    CapabilityBoundingSet = "";
    AmbientCapabilities = "";
    NoNewPrivileges = true;
    ProtectSystem = "strict";
    ProtectHome = true;
    PrivateTmp = true;
    PrivateDevices = true;
    PrivateUsers = true;
    PrivateMounts = true;
    DevicePolicy = "closed";
    ProtectClock = true;
    ProtectControlGroups = true;
    ProtectHostname = true;
    ProtectKernelLogs = true;
    ProtectKernelModules = true;
    ProtectKernelTunables = true;
    ProtectProc = "invisible";
    ProcSubset = "pid";
    RestrictNamespaces = true;
    RestrictRealtime = true;
    RestrictSUIDSGID = true;
    RestrictAddressFamilies = [
      "AF_INET"
      "AF_INET6"
      "AF_UNIX"
    ];
    LockPersonality = true;
    MemoryDenyWriteExecute = true;
    RemoveIPC = true;
    SystemCallArchitectures = "native";
    SystemCallFilter = [
      "@system-service"
      "~@privileged"
      "~@resources"
    ];
    SystemCallErrorNumber = "EPERM";
  };

  environment = {
    VEILLEUR_LANG = cfg.language;
  };

  # A consistent copy of what a restore needs, replaced in one step (ENF-08).
  snapshot = pkgs.writeShellScript "veilleur-snapshot" ''
    set -euo pipefail
    export PATH=${
      lib.makeBinPath [
        pkgs.coreutils
        pkgs.sqlite
      ]
    }
    # sqlite3 would create an empty database, and the last good copy would be replaced by it.
    if [ ! -s ${stateDir}/veilleur.db ]; then
      echo "veilleur-snapshot: no database in ${stateDir}, the previous copy is kept" >&2
      exit 1
    fi
    work=$(mktemp -d ${stateDir}/.snapshot.XXXXXX)
    trap 'rm -rf "$work"' EXIT
    sqlite3 ${stateDir}/veilleur.db ".backup '$work/veilleur.db'"
    test "$(sqlite3 "$work/veilleur.db" 'PRAGMA integrity_check;')" = ok
    for name in signing.key rotation.json rotation.sig webhook.key; do
      if [ -e "${stateDir}/$name" ]; then cp -p "${stateDir}/$name" "$work/$name"; fi
    done
    rm -rf ${snapshotDir}.old
    if [ -e ${snapshotDir} ]; then mv ${snapshotDir} ${snapshotDir}.old; fi
    mv "$work" ${snapshotDir}
    rm -rf ${snapshotDir}.old
  '';

  # ntfy's accounts and tokens, drawn once. Root owns them: the service only reads its two tokens.
  ntfySecrets = pkgs.writeShellScript "veilleur-ntfy-secrets" ''
    set -euo pipefail
    export PATH=${
      lib.makeBinPath [
        pkgs.coreutils
        config.services.ntfy-sh.package
      ]
    }
    umask 077
    dir=${ntfySecretsDir}
    random() { local s; s=$(head -c 4096 /dev/urandom | tr -dc 'a-z0-9'); printf '%s' "''${s:0:$1}"; }
    if [ ! -s "$dir/ntfy.env" ]; then
      publish="tk_$(random 29)"
      read="tk_$(random 29)"
      # Nobody logs in with these accounts: only their tokens are used.
      password=$(random 40)
      hash=$(printf '%s\n%s\n' "$password" "$password" | ntfy user hash 2>/dev/null)
      printf '%s' "$publish" > "$dir/publish.token.new"
      printf '%s' "$read" > "$dir/read.token.new"
      {
        printf "NTFY_AUTH_USERS='veilleur-publish:%s:user,veilleur-read:%s:user'\n" "$hash" "$hash"
        printf "NTFY_AUTH_TOKENS='veilleur-publish:%s:publish,veilleur-read:%s:read'\n" "$publish" "$read"
        printf "NTFY_AUTH_ACCESS='veilleur-publish:*:write-only,veilleur-read:*:read-only'\n"
      } > "$dir/ntfy.env.new"
      mv "$dir/publish.token.new" "$dir/publish.token"
      mv "$dir/read.token.new" "$dir/read.token"
      mv "$dir/ntfy.env.new" "$dir/ntfy.env"
    fi
    chown root:veilleur "$dir" "$dir/publish.token" "$dir/read.token"
    chmod 0710 "$dir"
    chmod 0640 "$dir/publish.token" "$dir/read.token"
    chmod 0600 "$dir/ntfy.env"
  '';

  # Web servers of nixpkgs that take ports 80 and 443 on their own (ENF-03b).
  conflictingServers = lib.filter (name: lib.attrByPath [ name "enable" ] false config.services) [
    "nginx"
    "httpd"
    "traefik"
    "haproxy"
    "lighttpd"
    "envoy"
  ];

  # Every port Veilleur takes, against those the rest of the configuration declares (ENF-03b).
  publicNtfyPort = optional (useCaddy && builtinNtfy && cfg.ntfy.host == null) 8443;
  publicTcpPorts = optionals useCaddy [
    80
    443
  ] ++ publicNtfyPort;
  portConflicts = (import ./ports.nix { inherit config lib; }).conflicts {
    tcp = publicTcpPorts;
    udp = optional useCaddy 443 ++ publicNtfyPort;
    internal = [
      {
        address = cfg.listenAddress;
        inherit (cfg) port;
      }
    ]
    ++ optional builtinNtfy {
      address = cfg.ntfy.listenAddress;
      port = ntfyPort;
    };
  };

  wildcardAddresses = [
    "0.0.0.0"
    "::"
    "[::]"
    "*"
  ];

  proxyBlock = upstream: ''
    reverse_proxy ${upstream} {
      header_up -X-Forwarded-For
    }
  '';
in
{
  options.services.veilleur = {
    enable = mkEnableOption "the Veilleur watch server";

    package = mkOption {
      type = types.package;
      default = packages.${pkgs.stdenv.hostPlatform.system}.veilleur;
      defaultText = lib.literalExpression "veilleur.packages.\${system}.veilleur";
      description = "The Python environment of the server.";
    };

    plugins = mkOption {
      type = types.listOf types.package;
      default = [ ];
      description = ''
        Python packages built for Python 3.12 that declare Veilleur entry points (collectors, filters,
        renderers, notifiers). They are added to the read-only environment.
      '';
    };

    publicHost = mkOption {
      type = types.nullOr types.str;
      default = null;
      example = "watch.example.org";
      description = ''
        Name (recommended) or address under which members reach the server, written into pairing codes.
        Changing it later means pairing every member again.
      '';
    };

    language = mkOption {
      type = types.enum [
        "en"
        "fr"
      ];
      default = "en";
      description = "Language of the server's messages.";
    };

    listenAddress = mkOption {
      type = types.str;
      default = "127.0.0.1";
      description = "Internal address of the HTTP service. It is never a wildcard address.";
    };

    port = mkOption {
      type = types.port;
      default = 8470;
      description = "Internal port of the HTTP service.";
    };

    proxy = mkOption {
      type = types.enum [
        "caddy"
        "external"
      ];
      default = "caddy";
      description = ''
        TLS front end. `caddy` takes ports 80 and 443 (and 8443 for ntfy without a name of its own).
        `external` only listens on `listenAddress`, behind the host's own reverse proxy.
      '';
    };

    acmeEmail = mkOption {
      type = types.nullOr types.str;
      default = null;
      example = "admin@example.org";
      description = "Contact address for the Let's Encrypt account (proxy = \"caddy\").";
    };

    internalTls = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Have Caddy use its own local certificate authority instead of Let's Encrypt. For tests and private
        networks: receiving tools must then trust that authority.
      '';
    };

    ntfy = {
      mode = mkOption {
        type = types.enum [
          "builtin"
          "external"
          "none"
        ];
        default = "builtin";
        description = "Notifications: a ntfy server set up here, an existing one, or none.";
      };

      host = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "ntfy.example.org";
        description = "Name of the built-in ntfy server. Without one, it is served on port 8443 of `publicHost`.";
      };

      listenAddress = mkOption {
        type = types.str;
        default = "127.0.0.1";
        description = "Internal address of the built-in ntfy server, on port 2586. It is never a wildcard address.";
      };

      url = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "https://ntfy.example.org";
        description = "Where the server publishes (mode = \"external\").";
      };

      publicUrl = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "https://ntfy.example.org";
        description = "The https address given in pairing codes. Required with `external`, in either setting.";
      };

      tokenFile = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "/run/secrets/veilleur-ntfy-publish";
        description = "File holding the token used to publish (mode = \"external\"), readable by user `veilleur`.";
      };

      clientTokenFile = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "/run/secrets/veilleur-ntfy-read";
        description = "File holding the token given in pairing codes (mode = \"external\"), readable by user `veilleur`.";
      };
    };

    webhook = {
      url = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "https://hooks.example.org/veilleur";
        description = "Address that receives the signed notification, if any.";
      };

      keyFile = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "/run/secrets/veilleur-webhook";
        description = "File holding the HMAC key, readable by user `veilleur`. Default: generated in the state directory.";
      };
    };

    offline = mkOption {
      type = types.bool;
      default = false;
      description = "Keep collectors off the network.";
    };

    roundSchedule = mkOption {
      type = types.str;
      default = "daily";
      example = "*-*-* 06:00:00";
      description = "When the collection round runs (systemd calendar event).";
    };

    subscriptions = mkOption {
      type = types.listOf toml.type;
      default = [ ];
      example = lib.literalExpression ''
        [ {
          name = "team_feed";
          collector = "rss";
          params.url = "https://example.org/feed.xml";
          pairings = [ "desk 3" ];
        } ]
      '';
      description = "Team subscriptions, as in the `[[subscriptions]]` tables of the configuration file.";
    };

    snapshotSchedule = mkOption {
      type = types.nullOr types.str;
      default = null;
      example = "daily";
      description = ''
        When to refresh the consistent copy of the state (systemd calendar event). Leave unset when the host's
        backup job starts `veilleur-snapshot.service` itself.
      '';
    };

    backupPaths = mkOption {
      type = types.listOf types.str;
      readOnly = true;
      default = [ snapshotDir ] ++ optionals builtinNtfy [ ntfySecretsDir "/var/lib/private/ntfy-sh" ];
      defaultText = lib.literalExpression ''[ "${snapshotDir}" ]'';
      description = ''
        Paths for the host's backup. Start `veilleur-snapshot.service` first: it writes the consistent copy.
      '';
    };
  };

  config = mkIf cfg.enable (mkMerge [
    {
      assertions = [
        {
          assertion = cfg.publicHost != null && builtins.match "[^/[:space:]]+" cfg.publicHost != null;
          message = "services.veilleur.publicHost must be set to a host name or address, without a scheme or path.";
        }
        {
          assertion = !useCaddy || conflictingServers == [ ];
          message =
            "services.veilleur.proxy = \"caddy\" needs ports 80 and 443, also used by: "
            + lib.concatStringsSep ", " conflictingServers
            + ". Use proxy = \"external\" and add Veilleur to that front end (see the administration guide).";
        }
        {
          assertion = portConflicts == [ ];
          message =
            "services.veilleur needs ports that the configuration also declares: "
            + lib.concatStringsSep ", " portConflicts
            + ".";
        }
        {
          # Caddy binds its public ports on every address, the internal one included.
          assertion = !builtins.elem cfg.port publicTcpPorts;
          message = "services.veilleur.port conflicts with the public ports of Caddy: ${
            lib.concatMapStringsSep ", " toString publicTcpPorts
          }.";
        }
        {
          assertion = !builtins.elem cfg.listenAddress wildcardAddresses;
          message = "services.veilleur.listenAddress must be an internal address, not a wildcard (cahier ES-09).";
        }
        {
          assertion = !builtinNtfy || !builtins.elem cfg.ntfy.listenAddress wildcardAddresses;
          message = "services.veilleur.ntfy.listenAddress must be an internal address, not a wildcard (cahier ES-09).";
        }
        {
          assertion = !builtinNtfy || cfg.port != ntfyPort;
          message = "services.veilleur.port conflicts with the built-in ntfy server (port 2586).";
        }
        {
          assertion = !(builtinNtfy && !useCaddy) || cfg.ntfy.publicUrl != null;
          message = "services.veilleur.ntfy.publicUrl is required with the built-in ntfy behind proxy = \"external\".";
        }
        {
          assertion = cfg.ntfy.mode != "external" || (cfg.ntfy.url != null && cfg.ntfy.publicUrl != null);
          message = "services.veilleur.ntfy.url and ntfy.publicUrl are required with ntfy.mode = \"external\".";
        }
        {
          assertion = cfg.ntfy.publicUrl == null || lib.hasPrefix "https://" cfg.ntfy.publicUrl;
          message = "services.veilleur.ntfy.publicUrl must be an https address.";
        }
      ];

      users.users.veilleur = {
        isSystemUser = true;
        group = "veilleur";
        home = stateDir;
      };
      users.groups.veilleur = { };

      environment.etc."veilleur/config.toml".source = configFile;
      environment.systemPackages = [ admin ];

      systemd.services.veilleur = {
        description = "Veilleur watch server";
        wantedBy = [ "multi-user.target" ];
        after = [ "network.target" ] ++ optional builtinNtfy "veilleur-ntfy-secrets.service";
        requires = optional builtinNtfy "veilleur-ntfy-secrets.service";
        restartTriggers = [ configFile ];
        inherit environment;
        serviceConfig = hardening // {
          ExecStart = "${package}/bin/veilleur serve";
          Restart = "on-failure";
          RestartSec = "5s";
        };
      };

      systemd.services.veilleur-round = {
        description = "Veilleur collection round";
        wants = [ "network-online.target" ];
        after = [
          "network-online.target"
          "veilleur.service"
        ];
        inherit environment;
        serviceConfig = hardening // {
          Type = "oneshot";
          ExecStart = "${package}/bin/veilleur round";
        };
      };

      systemd.timers.veilleur-round = {
        description = "Veilleur collection round";
        wantedBy = [ "timers.target" ];
        timerConfig = {
          OnCalendar = cfg.roundSchedule;
          Persistent = true;
          RandomizedDelaySec = "10min";
        };
      };

      systemd.services.veilleur-snapshot = {
        description = "Consistent copy of the Veilleur state";
        after = [ "veilleur.service" ];
        serviceConfig = hardening // {
          Type = "oneshot";
          ExecStart = snapshot;
          RestrictAddressFamilies = "none";
          PrivateNetwork = true;
        };
      };
    }

    (mkIf (cfg.snapshotSchedule != null) {
      systemd.timers.veilleur-snapshot = {
        description = "Consistent copy of the Veilleur state";
        wantedBy = [ "timers.target" ];
        timerConfig = {
          OnCalendar = cfg.snapshotSchedule;
          Persistent = true;
        };
      };
    })

    (mkIf useCaddy {
      services.caddy = {
        enable = true;
        email = lib.mkIf (cfg.acmeEmail != null) cfg.acmeEmail;
        virtualHosts.${publicHost} = {
          # No access log: members' addresses are never written down (ES-09).
          logFormat = null;
          extraConfig =
            lib.optionalString cfg.internalTls "tls internal\n" + proxyBlock "${cfg.listenAddress}:${toString cfg.port}";
        };
      };
      networking.firewall.allowedTCPPorts = [
        80
        443
      ];
      networking.firewall.allowedUDPPorts = [ 443 ];
    })

    (mkIf (useCaddy && builtinNtfy) {
      services.caddy.virtualHosts.${ntfySite} = {
        logFormat = null;
        extraConfig = lib.optionalString cfg.internalTls "tls internal\n" + proxyBlock ntfyListen;
      };
      networking.firewall.allowedTCPPorts = optional (cfg.ntfy.host == null) 8443;
      networking.firewall.allowedUDPPorts = optional (cfg.ntfy.host == null) 8443;
    })

    (mkIf builtinNtfy {
      services.ntfy-sh = {
        enable = true;
        environmentFile = "${ntfySecretsDir}/ntfy.env";
        settings = {
          base-url = ntfyPublicUrl;
          listen-http = ntfyListen;
          behind-proxy = true;
          auth-default-access = "deny-all";
          enable-signup = false;
          enable-login = false;
          web-root = "disable";
          # Above this level, ntfy writes visitors' addresses (ES-09).
          log-level = "error";
        };
      };

      systemd.services.veilleur-ntfy-secrets = {
        description = "Accounts and tokens of the Veilleur ntfy server";
        before = [ "ntfy-sh.service" ];
        requiredBy = [ "ntfy-sh.service" ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          StateDirectory = "veilleur-ntfy";
          StateDirectoryMode = "0710";
          UMask = "0077";
          ExecStart = ntfySecrets;
        };
      };
    })
  ]);
}
