# ADR-0020 — Déploiement NixOS : environnement uv2nix, conteneur, secrets, copie cohérente

- **Statut :** Accepté
- **Date :** 2026-11-18
- **Nature :** ADR rétrospective
- **Origine :** cahier ENF-01 à ENF-08, §10 (2026-11-18, G5) ; PR #6 (3 passages du vérificateur)

## Contexte

Réalisation de l'ADR-0006. `google-re2` a une partie native ; le conteneur ne doit joindre ni l'hôte ni les réseaux
privés ; les tests en VM ne peuvent pas atteindre une source locale à cause de la garde SSRF.

## Options considérées

- Construire `google-re2` depuis ses sources (re2, abseil, pybind11 natifs) ; **utiliser les *wheels* de `uv.lock`**.
- Pare-feu du conteneur dans la configuration de l'hôte (impose un moteur) ; **table `nftables` propre**, chargée à
  part et rétablie quand l'hôte recharge le sien.
- Source locale des tests en VM : exception à la garde SSRF (affaiblit la garde) ; **greffon de test qui lit un
  fichier**.

## Décision

- Environnement construit par uv2nix avec les *wheels* de `uv.lock`, pour `x86_64-linux` et `aarch64-linux` ;
  greffons ajoutés par le chemin de recherche Python.
- `veilleur-admin` lance l'administration sous l'utilisateur du service, sur l'hôte et depuis l'hôte vers le
  conteneur.
- ntfy intégré : accès anonyme refusé, un compte qui publie, un qui lit ; jetons tirés une fois dans
  `/var/lib/veilleur-ntfy`.
- `veilleur-snapshot.service` : copie cohérente (base, clé de signature, déclaration de rotation, clé de webhook)
  dans `/var/lib/veilleur/snapshot`, seul chemin listé par `backupPaths` ; échoue si la base est absente.
- Conteneur : `nftables` propre, résolveurs DNS publics, secrets transmis comme identifiants systemd, assertion AAAA
  confirmée par `noAaaaRecord = true`.
- Assertion de conflits de ports limitée à ce que l'évaluation voit (périmètre arrêté le 2026-11-18).
- Tests en VM : installation complète, `proxy = "external"`, conteneur (avec et sans `nftables` sur l'hôte), unités
  de repli.

## Conséquences

- Réserves R07 (unité des jetons ntfy en root), R20 (déploiement), R23 (non vérifié : charge, Let's Encrypt réel,
  `aarch64-linux`).

## Sources

- `flake.nix`, `deploy/nixos/`, `docs/{en,fr}/admin-guide.md`, `plan.md` G5, commit `0be164e`.
