# Veilleur — consignes pour Claude

Serveur de veille auto-hébergé et générique : collecteurs branchables (RSS/Atom, API JSON, pages web, greffons),
détection des changements, rapports signés et chiffrés livrés à des outils de réception (hors périmètre). Python 3.12+,
SQLite, architecture hexagonale, installation NixOS. Licence EUPL-1.2. Dépôt public `github.com/Cafeinoman/veilleur`.

Les règles communes (`~/.claude/CLAUDE.md`) s'appliquent ; ce fichier ne les recopie pas.

## Documents qui font foi

- `docs/SPEC.md` : quoi (exigences `EF`, `ES`, `ENF`) ; il prime sur tout le reste ;
- `docs/adr/` : décisions et leurs raisons ;
- `docs/PLAN.md` : lots, critères d'acceptation, réserves. **Reprendre au premier lot `à faire`** ;
- `docs/DECISIONS.md` : questions ouvertes et réponses de l'utilisateur.

`docs/REPRISE.md` trace la correspondance avec les anciens documents. `cahier_des_charges.MD` et `plan.md` ne font
plus foi (renvois, lot J7-L2). Toute évolution met à jour `docs/SPEC.md` (ou un ADR) d'abord, puis la documentation
publique dans les deux langues.

## Lots et questions

- Un lot = un identifiant `J<n>-L<m>` de `docs/PLAN.md`, sur une branche `claude/<identifiant>-<sujet>`.
- S'arrêter sur une erreur qu'on ne sait pas résoudre ou un arbitrage impératif (choix qui modifierait la
  spécification, contradiction entre documents, action irréversible hors du plan) : écrire la question et sa
  recommandation dans `docs/DECISIONS.md`, la reprendre dans la PR en cours, et terminer.
- Une question répondue dans `docs/DECISIONS.md` est réglée : reporter la décision dans l'ADR ou la spécification.
- Étiquettes : versions seulement (`v0.2.0`…), posées par l'utilisateur, ou par Claude sur sa demande explicite.
  Plus d'étiquette par lot (D6).

## Contrôle

```bash
just test        # tous les contrôles, ceux de la CI (dans nix develop, ou direnv)
just fmt         # formatage
just vm          # modules NixOS et machines virtuelles (nix flake check -L)
just ci-load     # durée de la CI sous les seuils (D16)
uv run python tools/i18n.py all          # extraire, fusionner, compiler les traductions
uv run python tools/protocol_vectors.py  # régénérer les vecteurs du protocole
uv run veilleur --lang fr --help
```

`just test` doit passer avant tout commit. Les commandes permises et interdites sont dans `.claude/settings.json`.

## Règles propres

- **Projet générique** : aucune connaissance d'un domaine métier particulier dans le dépôt. Une source propre à un
  domaine est un greffon maintenu ailleurs (exemple : `veilleur-marches`).
- **Architecture** : `core` (domain, services, ports) ne dépend ni du stockage, ni du réseau, ni de la traduction, ni de
  `adapters` ou `apps` ; `lint-imports` le vérifie. Le cœur renvoie des codes stables, que les applications traduisent.
  La surface publique de l'API des greffons est celle de l'ADR-0028 : ne la changer qu'avec des défauts.
- **Langues** :
  - code, identifiants, commentaires, docstrings, messages de commit et descriptions de PR en **anglais** ;
  - tout texte lu par une personne passe par `_()` / `ngettext()` de `veilleur.i18n`, avec des textes sources en
    anglais et des paramètres nommés (`str.format`) ;
  - lancer ensuite `uv run python tools/i18n.py all`, puis traduire en français dans le `.po`. Les tests refusent un
    message non traduit, approximatif ou obsolète, et un `.mo` périmé ;
  - documentation publique : mêmes fichiers dans `docs/en/` et `docs/fr/` (un test vérifie la parité) ;
  - documents de pilotage (`docs/SPEC.md`, `docs/PLAN.md`, `docs/adr/`, ce fichier) et échanges avec l'utilisateur en
    **français**.
- **Licence** : la première ligne de chaque fichier Python est `# SPDX-License-Identifier: EUPL-1.2` (un test le
  vérifie). Une dépendance doit avoir une licence compatible avec l'EUPL-1.2, et en ajouter une se justifie :
  dépendances minimales, cryptographie par `pycryptodomex` seulement.
- **Sécurité** (SPEC, exigences `ES`) :
  - jamais de corps de requête, d'en-tête d'authentification, de secret, de paramètre d'abonnement ni d'IP de membre
    dans les journaux ;
  - secrets dans le dossier d'état, jamais dans le dépôt, le *store* Nix ou la configuration ;
  - tout accès réseau d'un collecteur passe par le client HTTP du serveur (garde SSRF) ;
  - un lecteur de paquets vérifie tout avant de lire ;
  - toute modification du protocole met à jour sa spécification normative (en anglais), sa traduction et les vecteurs
    de test.
- **Tests sans réseau** : réponses enregistrées, application WSGI appelée directement, aucun port ouvert.
- **Tests du vérificateur** : `tests/verif/` ; un écart non bloquant y est un `xfail` strict cité dans une réserve de
  `docs/PLAN.md` (`tests/test_pilot_documents.py` le vérifie) ; le lot qui lève la réserve retire le marqueur, jamais
  le test. Nouveaux fichiers : `tests/verif/test_<lot>_*.py`.
- **Données** : aucune donnée personnelle dans le dépôt ; les exemples utilisent des domaines réservés (`example.org`,
  `example.net`).

## GitHub

- `main` est protégée, administrateurs compris : contrôles requis = les deux travaux de la matrice uv. Le travail
  `just test (nix develop)` et le travail Nix tournent aussi sur chaque PR.
- Après l'ouverture de la PR, attendre la CI (`gh pr checks --watch`) et corriger jusqu'à ce qu'elle soit verte.
- Accès : jeton à grain fin limité à ce dépôt. Une erreur 403 ou 404 signale un droit manquant : c'est un arrêt, et la
  question dans `docs/DECISIONS.md` nomme le droit, sans chercher à le contourner. Droits du jeton :

  | Droit | Niveau | Pour |
  |---|---|---|
  | Contents | Read and write | envoyer les branches et les étiquettes |
  | Pull requests | Read and write | ouvrir et mettre à jour les PR |
  | Workflows | Read and write | envoyer `.github/workflows/` (sans ce droit, tout envoi qui touche la CI est refusé) |
  | Actions | Read | suivre la CI (`gh run watch`, `gh pr checks`, `just ci-load`) |
  | Commit statuses | Read | état des contrôles |
  | Administration | Read and write | sujets, protection de `main`, signalement privé des failles |
  | Metadata | Read | obligatoire, ajouté d'office |
