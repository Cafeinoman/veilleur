# ADR-0009 — Seconde implémentation des vecteurs avec libsodium, en développement seulement

- **Statut :** Accepté
- **Date :** 2026-11-17
- **Nature :** ADR rétrospective
- **Origine :** cahier ES-13, §10 (2026-11-17, 2ᵉ ligne) ; `plan.md` G1 ; PR #2

## Contexte

ES-13 demande des vecteurs de test vérifiés par une seconde implémentation indépendante. Réutiliser
`pycryptodomex` ne donnerait pas d'indépendance.

## Options considérées

- Seconde implémentation avec `pycryptodomex` (même bibliothèque, erreurs communes possibles) ; avec `cryptography`
  (pas de XChaCha20) ; **avec libsodium (PyNaCl, Apache-2.0)**.

## Décision

- `tools/check_vectors.py`, avec PyNaCl, **dépendance de développement seulement** ; la règle « cryptographie par
  `pycryptodomex` seulement » vaut pour les dépendances d'exécution. La CI l'exécute.

## Conséquences

- Précédent réutilisé par l'ADR-0022 : une bibliothèque tierce peut servir d'oracle de test en développement sans
  devenir une dépendance d'exécution.
- Réserve R22 : les guides de contribution ne citent pas ce script.

## Sources

- `cahier_des_charges.MD` §10 ; `tools/check_vectors.py` ; `.github/workflows/ci.yml`, commit `0be164e`.
