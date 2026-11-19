# Veilleur — stratégie de tests

> Ce qui existe (0.1.0), ce que la reprise ajoute, ce que la CI lance. Développement entièrement assisté par IA : les
> tests sont la seule mémoire fiable d'une session à l'autre.

## 1. Principes

- **Sans réseau** (ENF-09) : réponses enregistrées, transport et résolveur factices, application WSGI appelée
  directement, horloge et `sleep` injectés. Aucun port ouvert, aucune attente réelle.
- **L'auteur n'est pas le vérificateur** : `tests/verif/` est écrit par l'agent `verificateur` à partir de
  `docs/SPEC.md`, `docs/PLAN.md` et des ADR, jamais à partir du raisonnement de l'auteur.
- **Un écart non bloquant = un `xfail` strict** rattaché à une réserve de `docs/PLAN.md` ; il passe en vert quand la
  réserve est levée (le lot retire le marqueur, jamais le test).
- **Un test existant ne s'affaiblit pas en silence** : toute modification d'assertion est dite dans la PR.
- **Une bibliothèque tierce peut servir d'oracle** en développement (PyNaCl pour les vecteurs, ADR-0009 ; Protego
  pour `robots.txt` si D8 est accepté), jamais en exécution.

## 2. Niveaux existants (0.1.0)

| Niveau | Où | Ce qu'il couvre |
|---|---|---|
| Protocole | `protocol/tests/` | primitives, paquets, échanges ; refus (altération, autre abonnement, autre numéro, signature, archives piégées, horodatage) ; données aléatoires du lecteur (ES-13) |
| Vecteurs | `tests/test_protocol_vectors.py`, `tools/protocol_vectors.py --check`, `tools/check_vectors.py` | vecteurs régénérés identiques ; seconde implémentation libsodium |
| Serveur | `tests/server/` | cœur, stockage, API, CLI d'administration, client HTTP (SSRF, redirections, limites, cache, `robots.txt`), collecteurs sur réponses enregistrées, filtres, rendus, notificateurs |
| Bout en bout | `tests/receiver/test_end_to_end.py`, `tests/server/test_cli_admin.py::test_end_to_end_without_network` | jumelage → tour → récupération par HTTP et par dossier |
| Dépôt | `tests/test_repository.py`, `tests/test_i18n.py`, `tests/test_cli.py`, `tests/test_deploy.py` | en-têtes SPDX, actions fixées, parité de la documentation, catalogues complets, version commune |
| Déploiement | `deploy/nixos/tests/` via `nix flake check` | évaluation (assertions, ports), VM : installation complète, `proxy = "external"`, conteneur avec et sans `nftables`, repli systemd |
| Vérification | `tests/verif/` | 758 tests des vérificateurs de G0-R à G6, dont 39 `xfail` stricts |

Total au 2026-11-19 : 1 314 tests collectés par `pytest`.

## 3. Ce que la reprise ajoute

| Test | Lot | Rôle |
|---|---|---|
| `tests/test_pilot_documents.py` | J7-L1, J7-L2 | cohérence des documents de pilotage (§4) |
| `tests/test_plugin_api.py` | J7-L3 | surface publique de l'API des greffons (ADR-0028) ; toute modification est visible en PR |
| Tests de l'analyseur `robots.txt` | J9-L1 | exemples de RFC 9309 ; règle la plus longue ; groupes ; `*` et `$` ; limite de 500 Kio ; différentiel contre Protego sur un corpus (D8) |
| Tests de rythme | J9-L1 | `Crawl-delay`, `Retry-After`, attente hors des 30 s, avec horloge simulée |
| Tests de politique et d'alerte | J9-L3 | `warn`/`enforce` par instance et par hôte ; une alerte pour deux tours ; réalerte après changement ; **absence de fuite** (§5) |
| Tests du POST | J10-L1 | corps, redirections, quota, hors ligne, absence du corps dans les journaux |
| Tests des sessions | J12-L1 | cookies liés à l'hôte, redirection vers un autre hôte, isolement des sessions, fermeture après exception, aucun fichier écrit |
| Tests de migration | J9-L2, J9-L3, J12-L2 | une base 0.1.0 (puis 0.2.0) fixée dans `tests/server/fixtures/` est migrée, avec sauvegarde, sans perte |
| Test de charge `slow` | J14-L3 | ENF-07 : 300 abonnements, un tour, mémoire et durée |

## 4. Cohérence des documents de pilotage

`tests/test_pilot_documents.py` (J7-L1, référence changée en J7-L2) vérifie, sans réseau :

1. chaque identifiant `EF-nn`, `ES-nn` et `ENF-nn` de la colonne « ancien » de `docs/REPRISE.md` (§2.2 à
   §2.5) figure dans `docs/SPEC.md` ; en J7-L1, aussi chaque identifiant de `cahier_des_charges.MD` ;
2. chaque `ADR-nnnn` cité dans `docs/SPEC.md`, `docs/REPRISE.md` et `docs/PLAN.md` a son fichier `docs/adr/nnnn-*.md`,
   et chaque ADR a un statut `Proposé`, `Accepté` ou `Rejeté` ;
3. chaque `Rnn` cité dans `docs/REPRISE.md` est une ligne de la section `## Réserves` de `docs/PLAN.md` ;
4. chaque test marqué `xfail` dans `tests/verif/` est cité, par son nom, dans la section `## Réserves` de
   `docs/PLAN.md` ;
5. chaque lot de `docs/PLAN.md` a un identifiant `J<n>-L<m>` unique, les rubriques du gabarit (objectif, critères
   d'acceptation, références, effort, statut) et un statut `à faire` ou `fait`.

C'est la vérification par test demandée par le brief (§3, point 2) ; le vérificateur de J7-L1 relit en plus la table
de correspondance contre `cahier_des_charges.MD`.

## 5. Scénarios critiques

| # | Scénario | Niveau | Lot |
|---|---|---|---|
| S1 | Une adresse interdite par `robots.txt` est collectée en `warn`, refusée en `enforce` | serveur | J9-L3 |
| S2 | L'adresse collectée (chemin et requête, jeton unique) n'apparaît dans **aucun** journal capturé (`caplog`, toutes sources), événement, sortie de `veilleur sources`, notification `ntfy` ou `webhook` | serveur | J9-L3 |
| S3 | Une alerte pour deux tours successifs (deux processus, même base) ; une nouvelle après changement de `robots.txt` | serveur | J9-L3 |
| S4 | Le corps d'un POST et les cookies d'une session n'apparaissent dans aucun journal ni exception | serveur | J10-L1, J12-L1 |
| S5 | POST vers un nom qui résout vers une adresse privée, directement ou après `307` : `address_refused`, aucune connexion | serveur | J10-L1 |
| S6 | Un greffon de la version 0.1.0 (exemple du dépôt et greffon de test en VM) fonctionne sans modification sur 0.2.0 et 0.3.0 | serveur, VM | J9 à J12 |
| S7 | Une base 0.1.0 migrée en 0.2.0 garde abonnements, état des collectes et paquets ; la sauvegarde existe | serveur | J9-L2 |
| S8 | Un collecteur qui lève après une requête de session ferme sa session ; aucune donnée ne reste d'une collecte à l'autre | serveur | J12-L1 |
| S9 | Un tour avec `Crawl-delay: 15` sur 10 requêtes dure 135 s simulées, sans `timeout` | serveur | J9-L1 |
| S10 | Les tests existants de `robots_disallowed`/`robots_unavailable` passent, assertions inchangées, en `enforce` | serveur | J9-L3 |

## 6. Outillage

- `pytest` (avec `caplog` et capture des sorties), `ruff`, `mypy` strict, `import-linter`, Babel pour les catalogues,
  PyNaCl pour la seconde implémentation, `gitleaks` dans l'environnement de développement.
- Ajouts proposés : `just` (commande unique), Protego en dépendance de développement (D8), marqueur `slow` (J14-L3).
- Faux du client HTTP (`tests/server/http_fakes.py`) étendus : POST, sessions, `Retry-After`, horloge simulée.

## 7. Ce que la CI lance

| Travail | Commande | Quand |
|---|---|---|
| Matrice uv, Python 3.12 et 3.13 (contrôles requis de `main`) | `uv sync --locked`, puis pytest, `check_vectors.py`, ruff, mypy, lint-imports | chaque PR et `main` |
| **`just test`** (nouveau, J7-L1) | `nix develop -c just test` (mêmes contrôles plus `protocol_vectors.py --check`) | chaque PR et `main` |
| Nix | `nix flake check -L` (évaluation et VM) | chaque PR et `main` |

Les tests `slow` ne tournent pas en CI par défaut [Suppose].

## Sources

- `pyproject.toml`, `.github/workflows/ci.yml`, `tests/`, `protocol/tests/`, `deploy/nixos/tests/`, commit `0be164e`,
  consultés le 2026-11-19 ; `uv run pytest --collect-only -q`, 2026-11-19.
