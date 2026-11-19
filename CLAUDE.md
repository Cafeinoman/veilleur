# Veilleur — consignes pour Claude

Serveur de veille auto-hébergé et générique : collecteurs branchables (RSS/Atom, API JSON, pages web, greffons), détection des changements, rapports signés et chiffrés livrés à des outils de réception (hors périmètre). Python 3.12+, SQLite, architecture hexagonale, installation NixOS. Licence EUPL-1.2. Dépôt public `github.com/Cafeinoman/veilleur`.

**Documents qui font foi** (les lire avant de décider) :
- `cahier_des_charges.MD` : quoi et comment ; il prime sur tout le reste ;
- `plan.md` : mode de travail, questions en attente, lots et état. **Reprendre au premier lot non terminé** ;
- `docs/{en,fr}/design.md` : présentation de la conception, qui suit le cahier ;
- `docs/{en,fr}/translating.md` : traductions.

Toute évolution met à jour le cahier d'abord, puis la documentation dans les deux langues.

## Questions et arrêts

- Un lot par session, clos par `/clear` puis `/livrer` (consignes communes).
- S'arrêter sur une **erreur qu'on ne sait pas résoudre** ou un **arbitrage impératif** :
  - un choix qui modifierait le cahier des charges ;
  - une contradiction entre documents ;
  - une action irréversible hors du plan (publication PyPI, suppression de données, réécriture de l'historique publié).
- Pour s'arrêter : écrire la question et sa recommandation dans « Questions en attente » de `plan.md`, la reprendre dans la PR en cours, et terminer.
- Au démarrage, lire « Questions en attente » : une question à laquelle l'utilisateur a répondu dans `plan.md` ou dans la PR est réglée ; reporter la décision dans le cahier (§10) et la retirer de la liste.
- **Ne jamais fusionner une PR** (`gh pr merge`) : la fusion revient à l'utilisateur.

## Règles

- **Projet générique** : aucune connaissance d'un domaine métier particulier dans le dépôt. Une source propre à un domaine est un greffon maintenu ailleurs.
- **Architecture** : `core` (domain, services, ports) ne dépend ni du stockage, ni du réseau, ni de la traduction, ni de `adapters` ou `apps` ; `lint-imports` le vérifie. Le cœur renvoie des codes stables, que les applications traduisent.
- **Langues** :
  - code, identifiants, commentaires, docstrings, messages de commit et descriptions de PR en **anglais** ;
  - tout texte lu par une personne passe par `_()` / `ngettext()` de `veilleur.i18n`, avec des textes sources en anglais et des paramètres nommés (`str.format`) ;
  - lancer ensuite `uv run python tools/i18n.py all`, puis traduire en français dans le `.po`. Les tests refusent un message non traduit, approximatif ou obsolète, et un `.mo` périmé ;
  - documentation : mêmes fichiers dans `docs/en/` et `docs/fr/` (un test vérifie la parité) ;
  - les documents de pilotage (`cahier_des_charges.MD`, `plan.md`, ce fichier) et les échanges avec l'utilisateur sont en **français**.
- **Licence** : la première ligne de chaque fichier Python est `# SPDX-License-Identifier: EUPL-1.2` (un test le vérifie). Une dépendance doit avoir une licence compatible avec l'EUPL-1.2, et en ajouter une se justifie : dépendances minimales, cryptographie par `pycryptodomex` seulement.
- **Sécurité** (cahier §6) :
  - jamais de corps de requête, d'en-tête d'authentification, de secret, de paramètre d'abonnement ni d'IP de membre dans les journaux ;
  - secrets dans le dossier d'état, jamais dans le dépôt, le *store* Nix ou la configuration ;
  - tout accès réseau d'un collecteur passe par le client HTTP du serveur (garde SSRF) ;
  - un lecteur de paquets vérifie tout avant de lire ;
  - toute modification du protocole met à jour sa spécification normative (en anglais), sa traduction et les vecteurs de test.
- **Tests sans réseau** : réponses enregistrées, application WSGI appelée directement, aucun port ouvert.
- **Données** : aucune donnée personnelle dans le dépôt ; les exemples utilisent des domaines réservés (`example.org`, `example.net`).

## Commandes (depuis la racine)

```bash
uv sync --locked
uv run pytest && uv run ruff check src tests tools protocol receiver && uv run mypy && uv run lint-imports
uv run python tools/i18n.py all          # extraire, fusionner, compiler les traductions
uv run python tools/protocol_vectors.py  # régénérer les vecteurs du protocole (--check pour comparer)
uv run python tools/check_vectors.py     # vérification indépendante des vecteurs (libsodium)
uv run veilleur --lang fr --help
```

Les quatre contrôles doivent passer avant tout commit. Sur le serveur de développement (NixOS), `uv`, `gh` et direnv sont installés ; à partir de G5, `nix develop` (ou direnv) fournit l'environnement.

Les commandes permises et interdites sont dans `.claude/settings.json`.

## Git et GitHub

- **Une branche par lot ou par fonctionnalité** : `claude/<lot>-<sujet>`, créée depuis `main` à jour. Pas de travail directement sur `main`, sauf le premier commit (G0-R). Ensuite, `main` est protégée sur GitHub, administrateurs compris.
- Accès GitHub : jeton à grain fin limité à ce dépôt (droits listés dans `plan.md`, G0-R étape 0). Une erreur 403 ou 404 signale un droit manquant : c'est un arrêt, et la question en attente nomme le droit, sans chercher à le contourner.
- Commits courts, à l'impératif, en anglais, terminés par la ligne `Co-Authored-By` demandée par l'environnement.
- Envoyer la branche, ouvrir la PR avec `gh pr create` (résumé, étapes du plan couvertes, vérifications faites), attendre la CI (`gh pr checks --watch`) et corriger jusqu'à ce qu'elle soit verte.
- **La fusion est faite par l'utilisateur.** Jamais de `--force` sur une branche partagée ; jamais de réécriture de `main`.
- Identité réglée **globalement** par l'utilisateur (15/11/2026) : `François Delalleau <Cafeinoman@users.noreply.github.com>`. La vérifier (`git config user.email`) avant de commiter ; ne pas la redéfinir dans le dépôt ni modifier la configuration globale.
- Étiquette par lot fusionné (`g0`, `g1`…), puis versions (`v0.1.0`), posée sur `main` après la fusion.
