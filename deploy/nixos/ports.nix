# SPDX-License-Identifier: EUPL-1.2
# The ports that the rest of the host's configuration declares, to report conflicts with Veilleur's (cahier ENF-03b).
{ config, lib }:
let
  # "443", "8000-8010" or "8000:8010".
  range =
    text:
    let
      bounds = map lib.toInt (lib.splitString "-" (builtins.replaceStrings [ ":" ] [ "-" ] (toString text)));
    in
    {
      first = builtins.head bounds;
      last = lib.last bounds;
    };

  # Redirections take a public port, whatever the address: they are matched against public ports only.
  natForwards = map (
    forward:
    range forward.sourcePort
    // {
      inherit (forward) proto destination;
      origin = "networking.nat.forwardPorts";
    }
  ) (lib.attrByPath [ "networking" "nat" "forwardPorts" ] [ ] config);

  containerForwards = lib.concatLists (
    lib.mapAttrsToList (
      name: container:
      map (
        forward:
        range forward.hostPort
        // {
          proto = forward.protocol;
          destination = "";
          origin = "containers.${name}.forwardPorts";
        }
      ) (container.forwardPorts or [ ])
    ) (config.containers or { })
  );

  # "[address:]host:container[/protocol]". A host port left out is drawn at run time and cannot conflict.
  ociListener =
    name: spec:
    let
      parts = lib.splitString "/" spec;
      found = builtins.match "((.*):)?([0-9-]*):([0-9-]+)" (builtins.head parts);
      hostPort = if found == null then "" else builtins.elemAt found 2;
    in
    lib.optional (hostPort != "") (
      range hostPort
      // {
        address = if found == null then null else builtins.elemAt found 1;
        proto = if builtins.length parts > 1 then builtins.elemAt parts 1 else "tcp";
        origin = "virtualisation.oci-containers.containers.${name}.ports";
      }
    );

  ociListeners = lib.concatLists (
    lib.mapAttrsToList (name: container: lib.concatMap (ociListener name) (container.ports or [ ])) (
      lib.attrByPath [ "virtualisation" "oci-containers" "containers" ] { } config
    )
  );

  # Explicit `listen` entries of the virtual hosts of a web server, when it is enabled.
  webListeners =
    server: addressOf:
    let
      settings = lib.attrByPath [ "services" server ] { } config;
    in
    lib.optionals (settings.enable or false) (
      lib.concatLists (
        lib.mapAttrsToList (
          name: site:
          map (listen: {
            first = listen.port;
            last = listen.port;
            address = addressOf listen;
            proto = "tcp";
            origin = "services.${server}.virtualHosts.${name}.listen";
          }) (lib.filter (listen: (listen.port or null) != null) (site.listen or [ ]))
        ) (settings.virtualHosts or { })
      )
    );

  listeners =
    ociListeners
    ++ webListeners "nginx" (listen: listen.addr or null)
    ++ webListeners "httpd" (listen: listen.ip or null);

  anyAddress = [
    null
    ""
    "*"
    "0.0.0.0"
    "::"
    "[::]"
  ];

  covers = port: entry: entry.first <= port && port <= entry.last;
  describe = port: proto: entry: "${toString port}/${proto} (${entry.origin})";

  publicConflicts =
    entries: proto: port:
    map (describe port proto) (lib.filter (entry: entry.proto == proto && covers port entry) entries);

  internalConflicts =
    { address, port }:
    map (describe port "tcp") (
      lib.filter (
        entry: entry.proto == "tcp" && covers port entry && builtins.elem entry.address (anyAddress ++ [ address ])
      ) listeners
    );
in
{
  # `tcp` and `udp` are the public ports Veilleur takes, `internal` the { address, port } it listens on.
  # Redirections towards `ownAddress` are Veilleur's own.
  conflicts =
    {
      tcp ? [ ],
      udp ? [ ],
      internal ? [ ],
      ownAddress ? null,
    }:
    let
      foreign = lib.filter (
        forward: ownAddress == null || !lib.hasPrefix "${ownAddress}:" forward.destination
      ) natForwards;
      entries = foreign ++ containerForwards ++ listeners;
    in
    lib.unique (
      lib.concatMap (publicConflicts entries "tcp") tcp
      ++ lib.concatMap (publicConflicts entries "udp") udp
      ++ lib.concatMap internalConflicts internal
    );
}
