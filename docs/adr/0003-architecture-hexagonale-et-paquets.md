# ADR-0003 — Architecture hexagonale, Python, trois paquets, dépendances minimales

- **Statut :** Accepté
- **Date :** 2026-11-15 (cahier version 1), précisée le 2026-11-17 (G1, G4)
- **Nature :** ADR rétrospective
- **Origine :** cahier §7.1, §7.3, §9 ; §10 (2026-11-17, seconde implémentation ; 2026-11-18, G4 récepteur) ; PR #2, #3, #5

## Contexte

Un serveur maintenu par une seule personne assistée par IA, qui doit accueillir des greffons, rester testable sans
réseau et garder la cryptographie isolée.

## Options considérées

- Langage : Python (écosystème de greffons par *entry points*, gettext, bibliothèque standard riche) ; [Suppose] Go ou
  Rust auraient donné un binaire unique mais un modèle de greffons plus lourd.
- Structure : application monolithique en couches ; **hexagonale** (`core/domain`, `core/services`, `core/ports`,
  `adapters`, `apps`) vérifiée par un outil.
- Découpage : un seul paquet ; **trois paquets** dans un espace de travail uv : `veilleur` (`src/`),
  `veilleur-protocol` (`protocol/`, sans dépendance au serveur), `veilleur-receive` (`receiver/`, ne dépend que du
  protocole).
- Cryptographie : `cryptography` (pyca) ; PyNaCl ; **`pycryptodomex`** seul en dépendance d'exécution.

## Décision

- Python 3.12 ou plus récent ; architecture hexagonale ; le cœur ne dépend ni du stockage, ni du réseau, ni de la
  traduction, ni de la cryptographie, ni de `adapters` ou `apps`. `lint-imports` le vérifie (contrats de
  `pyproject.toml`), ainsi que l'indépendance de `veilleur_protocol` et de `veilleur_receive`.
- Trois paquets, même numéro de version (ADR-0021).
- Dépendances d'exécution minimales, sous licence compatible EUPL-1.2 ; cryptographie par `pycryptodomex` seulement
  (la règle vaut pour l'exécution, pas pour le développement : ADR-0009). Seule autre dépendance d'exécution :
  `google-re2` (ADR-0016).
- Contrôles obligatoires : `pytest`, `ruff`, `mypy` (strict), `lint-imports`.

## Conséquences

- Tout accès au réseau, au disque ou à la traduction passe par un port ; les tests appellent l'application WSGI
  directement (ENF-09).
- L'API des greffons vit dans `veilleur.core` (ports et modèle) : sa stabilité est l'objet de l'ADR-0028.

## Sources

- `cahier_des_charges.MD` §7.1, §7.3, §9 ; `pyproject.toml` (contrats `importlinter`), commit `0be164e`.
