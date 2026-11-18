# SPDX-License-Identifier: EUPL-1.2
# Example settings for host-module.nix: copy to `veilleur-settings.nix` and adapt.
{
  enable = true;
  # A name rather than an address: it is written into the pairing codes.
  publicHost = "watch.example.org";
  ntfyHost = "ntfy.example.org";
  acmeEmail = "admin@example.org";
  memoryMax = "1G";
  externalInterface = "eth0";
  # Ports are forwarded in IPv4 only: confirm that publicHost has no AAAA record.
  noAaaaRecord = true;
}
