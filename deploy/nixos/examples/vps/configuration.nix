# SPDX-License-Identifier: EUPL-1.2
# Example: a VPS dedicated to Veilleur, with Caddy and ntfy on the machine itself.
{
  # Replace with the output of `nixos-generate-config` for your VPS.
  boot.loader.grub.device = "/dev/vda";
  fileSystems."/" = {
    device = "/dev/vda1";
    fsType = "ext4";
  };

  networking.hostName = "veilleur";
  services.openssh = {
    enable = true;
    settings.PasswordAuthentication = false;
  };

  services.veilleur = {
    enable = true;
    publicHost = "watch.example.org";
    acmeEmail = "admin@example.org";
    language = "en";
    ntfy.host = "ntfy.example.org";
    roundSchedule = "*-*-* 06:00:00";
    snapshotSchedule = "*-*-* 05:30:00";
  };

  system.stateVersion = "26.05";
}
