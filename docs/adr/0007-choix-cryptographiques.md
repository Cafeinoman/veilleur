# ADR-0007 — Choix cryptographiques : enveloppe AEAD, requêtes signées, rotation signée, garde SSRF

- **Statut :** Accepté
- **Date :** 2026-11-15
- **Nature :** ADR rétrospective
- **Origine :** cahier ES-02 à ES-08, ES-12, §10 (2026-11-15, 5ᵉ ligne) ; PR #2

## Contexte

Les rapports transitent par HTTPS ou par un dossier copié à la main ; ils doivent rester confidentiels, authentiques
et liés à leur abonnement et à leur numéro. Les requêtes des outils de réception doivent être authentifiées sans
comptes ni mots de passe.

## Options considérées

- Paquets : **zip chiffré** (AES de zip : métadonnées visibles, implémentations inégales) ; **enveloppe
  XChaCha20-Poly1305** autour d'un zip en clair ; format maison chiffré fichier par fichier.
- Requêtes : jeton porteur ; **HMAC-SHA256 sur méthode, chemin, horodatage et empreinte du corps** ; TLS client.
- Clé du serveur : rejumelage à chaque changement ; **rotation signée par la clé sortante**.
- SSRF : pare-feu seul ; **garde dans le client HTTP**, pare-feu en seconde barrière.

## Décision

- Enveloppe XChaCha20-Poly1305 (nonce de 24 octets, données associées = en-tête + `uid` + numéro + genre) ;
  signature Ed25519 du manifeste ; clés dérivées par HKDF-SHA256 (sel par abonnement, étiquette par usage).
- Signature des requêtes avec l'empreinte du corps (ES-06), tolérance de 5 minutes.
- Rotation : la clé sortante signe la clé entrante ; déclaration jointe 90 jours (ES-05).
- Garde SSRF dans le client HTTP (ES-08), après résolution DNS et à chaque redirection.
- Pas de confidentialité persistante, assumé et documenté (ES-12).

## Conséquences

- Le format exact est figé par le protocole 1.0 (ADR-0008) ; la garde SSRF est détaillée par l'ADR-0014.

## Sources

- `cahier_des_charges.MD` §6, §10 ; `docs/en/protocol.md`, `docs/en/threat-model.md`, commit `0be164e`.
