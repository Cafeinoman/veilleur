# SPDX-License-Identifier: EUPL-1.2
# Third pass of the verifier of batch G5: the internal port against Caddy's, and the scope of cahier section 10.
# Read by tests/verif/test_g5_pass3.py.
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
  ownName.ntfy.host = "ntfy.example.org";
  noNtfy.ntfy.mode = "none";
  otherNtfy.ntfy = {
    mode = "external";
    url = "https://ntfy.example.org";
    publicUrl = "https://ntfy.example.org";
  };
  external = {
    proxy = "external";
    ntfy.mode = "none";
  };
  externalWithNtfy = {
    proxy = "external";
    ntfy.publicUrl = "https://ntfy.example.org";
  };

  serviceConfig =
    settings: extra:
    evaluate [
      flake.nixosModules.default
      extra
      { services.veilleur = named // settings; }
    ];
  containerConfig =
    settings: extra:
    evaluate [
      flake.nixosModules.container
      extra
      { services.veilleur-container = boxed // settings; }
    ];
  service = settings: extra: failures (serviceConfig settings extra);
  # The host's assertions and those of the system inside the container.
  container =
    settings: extra:
    let
      config = containerConfig settings extra;
    in
    failures config ++ failures config.containers.veilleur.config;

  sshd = ports: {
    services.openssh = {
      enable = true;
      inherit ports;
    };
  };
  nginxOn = settings: site: {
    services.nginx = {
      enable = true;
      virtualHosts.other = site;
    }
    // settings;
  };
in
{
  # B5: the internal port on a public port Caddy really takes.
  refusedPort = {
    "service: 80" = service { port = 80; } { };
    "service: 443" = service { port = 443; } { };
    "service: 8443" = service { port = 8443; } { };
    "service, ntfy with its own name: 80" = service (ownName // { port = 80; }) { };
    "service, ntfy with its own name: 443" = service (ownName // { port = 443; }) { };
    "service, no ntfy: 80" = service (noNtfy // { port = 80; }) { };
    "service, no ntfy: 443" = service (noNtfy // { port = 443; }) { };
    "service, external ntfy: 443" = service (otherNtfy // { port = 443; }) { };
    "container: 80" = container { port = 80; } { };
    "container: 443" = container { port = 443; } { };
    "container: 8443" = container { port = 8443; } { };
    "container, ntfy with its own name: 443" = container (ownName // { port = 443; }) { };
    "container, no ntfy: 80" = container (noNtfy // { port = 80; }) { };
  };

  # The same numbers, where Caddy does not take them.
  acceptedPort = {
    "service, ntfy with its own name: 8443" = service (ownName // { port = 8443; }) { };
    "service, no ntfy: 8443" = service (noNtfy // { port = 8443; }) { };
    "service, external ntfy: 8443" = service (otherNtfy // { port = 8443; }) { };
    "service, external proxy: 80" = service (external // { port = 80; }) { };
    "service, external proxy: 443" = service (external // { port = 443; }) { };
    "service, external proxy: 8443" = service (external // { port = 8443; }) { };
    "service, external proxy and built-in ntfy: 8443" = service (externalWithNtfy // { port = 8443; }) { };
    "service: 79" = service { port = 79; } { };
    "service: 81" = service { port = 81; } { };
    "service: 442" = service { port = 442; } { };
    "service: 444" = service { port = 444; } { };
    "service: 8442" = service { port = 8442; } { };
    "service: 8444" = service { port = 8444; } { };
    "container, ntfy with its own name: 8443" = container (ownName // { port = 8443; }) { };
    "container, no ntfy: 8443" = container (noNtfy // { port = 8443; }) { };
    "container, external proxy: 443" = container (external // { port = 443; }) { };
    "container, external proxy: 8443" = container (external // { port = 8443; }) { };
  };

  # What section 10 lists, in the forms added by this correction.
  reportedForm = {
    "sshd on 80" = service { } (sshd [ 80 ]);
    "sshd on 443" = service { } (sshd [ 443 ]);
    "sshd on 8443" = service { } (sshd [ 8443 ]);
    "sshd on the second of its ports" = service { } (sshd [ 22 443 ]);
    "sshd on the internal port" = service external (sshd [ 8470 ]);
    "sshd on the port of the built-in ntfy" = service externalWithNtfy (sshd [ 2586 ]);
    "container: sshd on 443" = container { } (sshd [ 443 ]);
    "container: sshd on 8443" = container { } (sshd [ 8443 ]);
    "nginx default port on the internal port" = service external (
      nginxOn { defaultHTTPListenPort = 8470; } { }
    );
    "nginx default port on the port of the built-in ntfy" = service externalWithNtfy (
      nginxOn { defaultHTTPListenPort = 2586; } { }
    );
    "nginx default port on the internal address" = service external (
      nginxOn { defaultHTTPListenPort = 8470; } { listenAddresses = [ "127.0.0.1" ]; }
    );
    "nginx default port on IPv6 wildcard only" = service external (
      nginxOn {
        defaultHTTPListenPort = 8470;
        defaultListenAddresses = [ "[::0]" ];
      } { }
    );
  };

  acceptedForm = {
    "sshd on its usual port" = service { } (sshd [ 22 ]);
    "sshd disabled on 443" = service { } { services.openssh.ports = [ 443 ]; };
    "sshd on 443 behind an external proxy" = service external (sshd [ 443 ]);
    "sshd on 8443, ntfy with its own name" = service ownName (sshd [ 8443 ]);
    "sshd on 8443, no ntfy" = service noNtfy (sshd [ 8443 ]);
    "container: sshd on its usual port" = container { } (sshd [ 22 ]);
    "container: sshd on 443 behind an external proxy" = container external (sshd [ 443 ]);
    "nginx in front on its usual ports" = service external (nginxOn { } { });
    "nginx in front, built-in ntfy" = service externalWithNtfy (nginxOn { } { });
    "nginx default port on another address of the site" = service external (
      nginxOn { defaultHTTPListenPort = 8470; } { listenAddresses = [ "192.0.2.10" ]; }
    );
    "nginx default port replaced by an explicit entry" = service external (
      nginxOn { defaultHTTPListenPort = 8470; } {
        listen = [
          {
            addr = "0.0.0.0";
            port = 8080;
          }
        ];
      }
    );
    "nginx default port without any site" = service external {
      services.nginx = {
        enable = true;
        defaultHTTPListenPort = 8470;
      };
    };
    "nginx disabled on the internal port" = service external {
      services.nginx = {
        defaultHTTPListenPort = 8470;
        virtualHosts.other = { };
      };
    };
  };

  # Outside section 10: what the assertion still does not read, or reads too widely.
  outside = {
    "caddy admin port" = service { port = 2019; } { };
    "nginx TLS default port" = service external (
      nginxOn { defaultSSLListenPort = 8470; } {
        onlySSL = true;
        sslCertificate = "/run/example/cert.pem";
        sslCertificateKey = "/run/example/key.pem";
      }
    );
    "sshd listenAddresses port" = service external {
      services.openssh = {
        enable = true;
        listenAddresses = [
          {
            addr = "127.0.0.1";
            port = 8470;
          }
        ];
      };
    };
  };
  # sshd bound elsewhere does not take the internal address.
  sshdElsewhere = service external {
    services.openssh = {
      enable = true;
      ports = [ 8470 ];
      listenAddresses = [ { addr = "192.0.2.10"; } ];
    };
  };

  # What an administrator meets: the build itself has to stop.
  hostBuild = {
    service = (serviceConfig { port = 8443; } { }).system.build.toplevel.drvPath;
    container = (containerConfig { port = 8443; } { }).system.build.toplevel.drvPath;
  };
}
