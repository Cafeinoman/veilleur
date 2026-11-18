# SPDX-License-Identifier: EUPL-1.2
# Second pass of the verifier of batch G5: what the port assertion says. Read by tests/verif/test_g5_pass2.py.
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

  named = {
    enable = true;
    publicHost = "watch.example.org";
  };
  boxed = named // {
    externalInterface = "eth0";
    noAaaaRecord = true;
  };
  external = {
    proxy = "external";
    ntfy.mode = "none";
  };

  service =
    settings: extra:
    failures (evaluate [
      flake.nixosModules.default
      extra
      { services.veilleur = named // settings; }
    ]);
  # The host's assertions and those of the system inside the container.
  container =
    settings: extra:
    let
      config = evaluate [
        flake.nixosModules.container
        extra
        { services.veilleur-container = boxed // settings; }
      ];
    in
    failures config ++ failures config.containers.veilleur.config;

  nat = sourcePort: proto: {
    networking.nat = {
      enable = true;
      externalInterface = "eth0";
      forwardPorts = [
        {
          inherit sourcePort proto;
          destination = "10.1.1.2:9000";
        }
      ];
    };
  };
  oci = ports: {
    virtualisation.oci-containers.containers.web = {
      image = "example.org/web:1";
      inherit ports;
    };
  };
  nspawn = hostPort: {
    containers.other.forwardPorts = [ { inherit hostPort; } ];
  };
  nginx = listen: {
    services.nginx = {
      enable = true;
      virtualHosts.other.listen = listen;
    };
  };
  httpd = listen: {
    services.httpd = {
      enable = true;
      adminAddr = "admin@example.org";
      virtualHosts.other.listen = listen;
    };
  };
in
{
  # Each of these configurations declares the same port twice.
  reported = {
    "NAT range over 443" = service { } (nat "440:450" "tcp");
    "NAT on 443/udp (HTTP/3)" = service { } (nat 443 "udp");
    "NAT on 80" = service { } (nat 80 "tcp");
    "nspawn container on 443" = service { } (nspawn 443);
    "OCI on loopback IPv6" = service { } (oci [ "[::1]:443:443" ]);
    "OCI on 443/udp" = service { } (oci [ "443:443/udp" ]);
    "OCI range over 443" = service { } (oci [ "440-450:440-450" ]);
    "OCI on the internal port" = service external (oci [ "127.0.0.1:8470:80" ]);
    "OCI on the internal port, any address" = service external (oci [ "8470:80" ]);
    "Apache on the internal port" = service external (
      httpd [
        {
          ip = "*";
          port = 8470;
        }
      ]
    );
    "nginx on the port of the built-in ntfy" =
      service
        {
          proxy = "external";
          ntfy.publicUrl = "https://ntfy.example.org";
        }
        (
          nginx [
            {
              addr = "0.0.0.0";
              port = 2586;
            }
          ]
        );
    "container: NAT on 8443" = container { } (nat 8443 "tcp");
    "container: OCI on 443" = container { } (oci [ "443:443" ]);
    "container: nspawn container on 80" = container { } (nspawn 80);
  };

  # Veilleur's own options: the internal service against the public ports Caddy takes on every address.
  ownPorts = {
    "service: port 8443" = service { port = 8443; } { };
    "service: port 443" = service { port = 443; } { };
    "service: port 80" = service { port = 80; } { };
    "container: port 8443" = container { port = 8443; } { };
    "container: port 443" = container { port = 443; } { };
  };

  # Declared on the host, on a port Veilleur needs, in a form the assertion does not read.
  otherForms = {
    "sshd on 443" = service { } { services.openssh = { enable = true; ports = [ 443 ]; }; };
    "socket unit on 443" = service { } {
      systemd.sockets.other = {
        wantedBy = [ "sockets.target" ];
        listenStreams = [ "443" ];
      };
    };
    "nginx default port on the internal port" = service external {
      services.nginx = {
        enable = true;
        defaultHTTPListenPort = 8470;
        virtualHosts.other = { };
      };
    };
  };

  # Nothing conflicts in these.
  accepted = {
    "service alone" = service { } { };
    "external proxy, NAT on 443" = service external (nat 443 "tcp");
    "external proxy, OCI on 443" = service external (oci [ "443:443" ]);
    "external proxy, nspawn on 443" = service external (nspawn 443);
    "ntfy with its own name, OCI on 8443" = service { ntfy.host = "ntfy.example.org"; } (oci [ "8443:8443" ]);
    "ntfy none, OCI on 2586" = service { ntfy.mode = "none"; } (oci [ "2586:2586" ]);
    "OCI on a drawn host port" = service { } (oci [ "127.0.0.1::443" ]);
    "OCI on the container's port only" = service { } (oci [ "443" ]);
    "OCI on 443 of the container" = service { } (oci [ "8080:443" ]);
    "NAT next to the public ports" = service { } (nat "444:450" "tcp");
    "OCI on the internal port of another address" = service external (oci [ "192.0.2.10:8470:80" ]);
    "a disabled nginx" = service { } {
      services.nginx.virtualHosts.other.listen = [
        {
          addr = "0.0.0.0";
          port = 443;
        }
      ];
    };
    "container alone" = container { } { };
    "container behind the host's proxy" = container {
      proxy = "external";
      ntfy.publicUrl = "https://ntfy.example.org";
    } { };
    "container behind the host's proxy, NAT on 443" = container {
      proxy = "external";
      ntfy.publicUrl = "https://ntfy.example.org";
    } (nat 443 "tcp");
    "container, ntfy with its own name, OCI on 8443" = container { ntfy.host = "ntfy.example.org"; } (
      oci [ "8443:8443" ]
    );
  };

  # What the built-in ntfy is told to listen on, and where Veilleur publishes.
  ntfyOnIpv6 =
    let
      config = evaluate [
        flake.nixosModules.default
        {
          services.veilleur = named // {
            ntfy.listenAddress = "::1";
          };
        }
      ];
    in
    {
      listen = config.services.ntfy-sh.settings.listen-http;
      failures = failures config;
    };

  # Where the host's front end has to go, and that Veilleur publishes to the same place.
  behindProxy =
    let
      inner =
        (evaluate [
          flake.nixosModules.container
          {
            services.veilleur-container = boxed // {
              proxy = "external";
              ntfy.publicUrl = "https://ntfy.example.org";
            };
          }
        ]).containers.veilleur.config;
    in
    {
      listen = inner.services.ntfy-sh.settings.listen-http;
      config = builtins.readFile inner.environment.etc."veilleur/config.toml".source;
    };
}
