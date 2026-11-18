# Veilleur — plan de travail

> Ce qu'il reste à faire, lot par lot, et où on en est. Le **quoi** et le **comment** sont dans `cahier_des_charges.MD`, qui fait foi ; ce plan le suit. Cocher une étape quand elle est faite et vérifiée ; noter les décisions prises en route dans le cahier (§10), pas ici.

## Mode de travail

- Claude **enchaîne les étapes sans demander de confirmation**. Il ne s'arrête que sur une **erreur qu'il ne sait pas résoudre** ou un **arbitrage impératif** : choix qui modifierait le cahier des charges, contradiction entre documents, action irréversible hors de ce plan.
- Dans ce cas, il écrit la question dans la section « Questions en attente » ci-dessous, avec sa recommandation, et la reprend dans la description de la *pull request* en cours, puis s'arrête.
- **Une branche par lot ou par fonctionnalité** : `claude/<lot>-<sujet>` (par exemple `claude/g1-protocol-spec`), créée depuis `main` à jour.
- **Un lot = une ou plusieurs *pull requests*.** Claude pousse la branche et ouvre la PR avec `gh pr create`. La description, en anglais, contient le résumé, les étapes du plan couvertes et ce qui a été vérifié. Claude attend que la CI soit verte et corrige si besoin. **La fusion est faite par l'utilisateur.**
- **Un lot par session.** Quand le code d'un lot est écrit, contrôlé et commité, Claude s'arrête et demande à l'utilisateur de lancer `/clear` puis `/livrer` (au plus 2 passages du vérificateur ; les écarts non bloquants deviennent des réserves, notées sous le lot).
- Tant qu'une PR attend sa fusion, Claude peut avancer le lot suivant (dans une nouvelle session) sur une nouvelle branche, si celui-ci n'en dépend pas. Sinon, il crée sa branche depuis la branche en attente et le signale dans la PR.
- Ce plan est mis à jour dans la même branche que le travail qu'il décrit : étapes cochées, état du lot.

## Questions en attente

1. **G3, filtre `regex` (écart bloquant B2', 2ᵉ passage du vérificateur).** Le refus statique des motifs à retour arrière catastrophique (cahier §10, 2026-11-18) ne tient pas : `.{0,100}` répété, `(?:.{0,50}){4}=`, classes hors latin (`[α-ω]+[α-ω]+[α-ω]+=`) passent et bloquent le tour plus de 10 s. Une analyse statique du moteur `re` restera incomplète, et le tour n'a pas de délai par filtre. Options :
   - (a) **moteur en temps linéaire `google-re2`** (BSD-3, compatible EUPL) : plus de retour arrière du tout ; on perd références arrière et assertions avant/arrière ; nouvelle dépendance d'exécution, à inscrire au cahier ;
   - (b) module `regex` (Apache-2.0) avec délai par recherche : syntaxe Python conservée, mais coût borné seulement par délai × nombre d'éléments ;
   - (c) garder `re` et durcir l'analyse (bornes, intervalles de points de code) : sans dépendance, mais sans garantie ;
   - (d) livrer G3 tel quel, B2' en réserve pour G4.

   **Recommandation : (a)**, seule garantie réelle ; décision au cahier §10 et doc du filtre (syntaxe RE2).

## État

| Lot | Objet | État |
|---|---|---|
| G0-R | Dépôt git, environnement, contrôles, création du dépôt GitHub | fait |
| G1 | Protocole 1.0 et `veilleur-protocol` | fait, avec réserves (étiquette `g1`) |
| G2 | Cœur, stockage, administration, service HTTP | fait, avec réserves (PR à fusionner, puis étiquette `g2`) |
| G3 | Client HTTP sûr, collecteurs, filtres, notificateurs | écrit, à livrer (branche `claude/g3-collectors`) |
| G4 | Rendus, récepteur de référence | à faire |
| G5 | Déploiement NixOS et repli systemd | à faire |
| G6 | Publication 0.1.0 | à faire |

## G0-R — Mise en route du dépôt

Le squelette (G0) est en place : licence, traduction, CI, documentation bilingue, tests. Ce lot a créé le dépôt GitHub et l'a publié.

- [x] **0. Accès GitHub (préalable, fait par l'utilisateur).** Le `gh` du serveur est connecté avec un jeton à grain fin limité à un autre dépôt. Avant de lancer Claude :
  1. Sur GitHub, créer le dépôt **vide** `Cafeinoman/veilleur`, public, sans README, licence ni `.gitignore`.
  2. Dans *Settings → Developer settings → Fine-grained tokens*, modifier le jeton existant ou en créer un nouveau. Ajouter `Cafeinoman/veilleur` à ses dépôts (« Only select repositories »), avec ces droits :

     | Droit | Niveau | Pour |
     |---|---|---|
     | Contents | Read and write | envoyer les branches et les étiquettes |
     | Pull requests | Read and write | ouvrir et mettre à jour les PR |
     | Workflows | Read and write | envoyer `.github/workflows/` (sans ce droit, tout envoi qui touche la CI est refusé) |
     | Actions | Read | suivre la CI (`gh run watch`, `gh pr checks`) |
     | Commit statuses | Read | état des contrôles |
     | Administration | Read and write | sujets, protection de `main`, signalement privé des failles |
     | Metadata | Read | obligatoire, ajouté d'office |

  3. Nouveau jeton seulement : `gh auth login --with-token < fichier_du_jeton`, puis effacer le fichier.

  **Vérification par Claude** : `gh auth status` et `gh api repos/Cafeinoman/veilleur --jq '.full_name, .size'` doivent répondre, avec une taille de 0. Si une erreur 403 ou 404 survient ici ou plus loin, faute d'un droit du tableau, c'est un arrêt : la question en attente nomme le droit manquant.
- [x] **1. Historique.** S'il existe un dossier `.git`, le supprimer : le dépôt repart d'un historique neuf. Puis `git init -b main`.
  L'identité `François Delalleau <Cafeinoman@users.noreply.github.com>` est réglée globalement par l'utilisateur (15/11/2026, voir `CLAUDE.md`) : la vérifier, ne pas la redéfinir dans le dépôt.
- [x] **2. Environnement.** `uv` et `gh` doivent être présents (sous NixOS : paquets système, ou `nix shell nixpkgs#uv nixpkgs#gh`). Lancer ensuite :
  ```bash
  uv python install 3.12
  uv sync --locked
  ```
  Si `uv.lock` ne correspond plus à `pyproject.toml`, comprendre pourquoi avant de le régénérer.
- [x] **3. Contrôles.** Tous doivent passer :
  ```bash
  uv run pytest && uv run ruff check src tests tools protocol && uv run mypy && uv run lint-imports
  uv run veilleur --lang fr --help
  uv run veilleur --lang fr version && uv run veilleur --lang en version
  ```
  Attendu : tests verts ; aide et erreurs entièrement en français avec `--lang fr`.
- [x] **4. Cohérence documentaire.** Relire `docs/en/design.md` et `docs/fr/design.md` contre `cahier_des_charges.MD`, en particulier ENF-03 et ENF-03b (intégration NixOS) et §9 (branches et PR). Le cahier prime : corriger les écarts dans les deux langues.
- [x] **5. Premier commit sur `main`**, avec tous les fichiers. C'est le seul commit fait directement sur `main`. Message :
  ```
  Project skeleton: licence, bilingual messages and documentation, CI
  ```
  Il se termine par la ligne `Co-Authored-By` demandée par l'environnement. Vérifier ensuite que `git log --format='%an <%ae>'` ne montre que l'identité ci-dessus.
- [x] **6. Envoi sur GitHub.** Le dépôt a été créé vide à l'étape 0. S'il n'est pas vide, c'est un arrêt avec une question en attente. Sinon :
  ```bash
  git remote add origin https://github.com/Cafeinoman/veilleur.git
  git push -u origin main
  gh repo edit Cafeinoman/veilleur \
    --description "Self-hosted watch server: pluggable collectors, signed and encrypted reports"
  ```
  C'est le **seul envoi direct sur `main`** ; l'étape 7 l'interdit ensuite.
- [x] **7. Réglages GitHub** (par `gh api` ou `gh repo edit`) :
  - sujets du dépôt : `watch`, `rss`, `self-hosted`, `nixos`, `encryption` ;
  - protection de `main` :
    - *pull request* obligatoire, sans approbation exigée (l'utilisateur fusionne lui-même ses PR) ;
    - CI verte obligatoire : les deux contrôles de la matrice, avec leurs noms tels qu'ils apparaissent après l'étape 8 ;
    - ni *force push* ni suppression ;
    - **règles appliquées aussi aux administrateurs** (`enforce_admins`), pour que le jeton de Claude ne puisse plus envoyer directement sur `main` ;
  - signalement privé des failles activé.

  Les contrôles requis ne peuvent être nommés qu'une fois la CI passée : faire l'étape 8 avant de régler la protection.
- [x] **8. CI.** Attendre la fin de la première exécution de GitHub Actions sur `main` (`gh run watch`). Elle doit être verte pour Python 3.12 et 3.13.
- [x] **9. Clôture**, sur la branche `claude/g0r-close` : passer G0-R à « fait » dans le tableau d'état, ouvrir la PR. L'étiquette `g0` sera posée après la fusion.

Fini quand : dépôt public avec la seule identité `François Delalleau <Cafeinoman@users.noreply.github.com>`, `main` protégée, CI verte.

## G1 — Protocole 1.0 (cahier ES-02 à ES-07, ES-13, §7.3)

- [x] Spécification `docs/en/protocol.md` (normative) et `docs/fr/protocol.md` (informative) :
  - code de jumelage `VEIL1:` ;
  - dérivation des clés (étiquettes `info` : `veilleur-report`, `veilleur-subscription`, `veilleur-auth`) ;
  - enveloppe (magie, version, nonce, données associées) ;
  - manifeste et signature ;
  - signature des requêtes ;
  - déclaration de rotation de clé ;
  - limites du lecteur ;
  - genres de paquets et fichiers qu'ils contiennent.
- [x] Paquet `protocol/` (`veilleur-protocol`), dépendance unique `pycryptodomex`, dans un espace de travail uv avec le serveur.
- [x] Vecteurs de test (`protocol/vectors/*.json`) : secrets, `uid`, clés dérivées, paquets scellés, requêtes signées, rotation.
- [x] Seconde implémentation, indépendante, de la vérification des vecteurs : un script court, avec une autre bibliothèque cryptographique si possible, exécuté dans la CI. Fait avec libsodium (PyNaCl, dépendance de développement) : `tools/check_vectors.py`.
- [x] Tests des refus : paquet altéré, autre abonnement, autre numéro, signature fausse, archive piégée (chemins, trop de fichiers, trop gros), horodatage hors tolérance.
- [x] Modèle de menace `docs/{en,fr}/threat-model.md`.

Fini quand : vecteurs vérifiés par les deux implémentations ; tous les refus testés.

Réserves à la livraison (7 passages du vérificateur ; le 8ᵉ, interrompu, n'a pas rendu de verdict) :
- [ ] Les correctifs du 7ᵉ passage (`a48c755` : clés publiques d'ordre faible refusées, §6.1, §8 et §10.1 précisés, seconde implémentation alignée) n'ont pas été revus par un vérificateur indépendant. À faire lors d'une prochaine vérification, limitée au diff depuis `383b9ca`.
- [ ] `SECURITY.md` (ES-13) : prévu en G6.
- [x] Ordre des contrôles du §8 face à un `key_id` inconnu : vérifié en G2 par le service WSGI (`tests/server/test_api.py`).

## G2 — Cœur, stockage, administration, service (EF-01 à EF-14, EF-30 à EF-45, EF-60 à EF-72, §7)

- [x] Domaine : `Item`, `Subscription`, `Collection`, `Report`, `Pairing`, codes d'erreur stables (`core/domain`).
- [x] Ports : `Collector`, `Filter`, `Renderer`, `Notifier`, `Store`, `Sealer`, `HttpClient`, horloge (`core/ports`).
- [x] Services :
  - jumelage ;
  - abonnements (validation par schéma, versions) ;
  - collecte mutualisée ;
  - détection des changements ;
  - production des paquets (`delta`, `state`, `history`) ;
  - purge à 90 jours ;
  - tour ;
  - tâches longues.
- [x] SQLite : WAL, migrations SQL numérotées, sauvegarde avant migration.
- [x] Ligne de commande d'administration (EF-70), entièrement traduite.
- [x] Service WSGI `/v1` (§7.4) et fil de travail ; tests qui appellent l'application directement. Repris de la vérification de G1 :
  - router sur le chemin **brut**, celui que signe le client (portée de la clé d'authentification, protocole §8), sans normalisation préalable ;
  - `key_id` inconnu : contrôler l'en-tête, la date et la péremption **avant** la recherche du secret, sans renvoyer `bad_authorization` plus tôt (protocole §8) ;
  - versions d'abonnement qui continuent de croître après un `DELETE`, pour qu'un `DELETE` ou une création rejoués dans la fenêtre de 5 minutes n'aient pas d'effet (modèle de menace §4).
- [x] Abonnements d'équipe déclarés en TOML (EF-10) ; autorisations de collecteurs par jumelage (EF-11).
- [x] Spécification du protocole complétée (§9 : document d'abonnement, paquets d'un abonnement, codes d'erreur de l'API), en anglais et en français ; modèle de menace §4 mis à jour.

Fini quand : un tour complet sur un collecteur factice, du jumelage à la récupération d'un paquet par l'API, sans réseau (`tests/server/test_cli_admin.py::test_end_to_end_without_network`).

Réserves à la livraison (2 passages du vérificateur ; B1 corrigé avant le 2ᵉ, B2 corrigé après lui sur décision de l'utilisateur, sans 3ᵉ passage). Chaque écart a son test en `xfail` strict dans `tests/verif/test_g2_*.py` :
- [ ] Le correctif de B2 (`0e30a66` : élément trop profond pour être haché écarté comme `bad_item`) n'a pas été revu par un vérificateur indépendant.
- [ ] EF-05, autres arrêts du tour par un greffon qui viole son contrat : liste d'éléments paresseuse qui lève une exception (`_normalise` hors du `try`), `CollectorError` dont le code n'est pas une chaîne. Piste : un garde-fou autour de chaque collecte dans `run_round`.
- [ ] Une déclaration d'équipe cassée (greffon absent) fait échouer `veilleur round` et `serve` avant toute collecte, au lieu de `collector_missing`.
- [ ] EF-10 : `sync_team` peut dupliquer un abonnement d'équipe supprimé puis redéclaré dans la même seconde (pierre tombale qui masque la ligne vivante).
- [x] (corrigé en G3) Protocole §7.4 : quand un filtre modifie les champs en place, `_current_view` garde l'empreinte stockée ; le `hash` publié ne correspond plus aux `fields`.
- [ ] ES-05 : le service en marche ne suit pas un `key rotate` lancé par un autre processus ; deux rotations en moins de 90 jours : la seconde remplace la première déclaration.
- [ ] EF-12 : un surrogate isolé dans les paramètres d'un `PUT` donne `500 internal_error` au lieu d'un 400.
- [ ] EF-70, EF-80 : noms de valeur `LABEL`, `LIMIT`, `AFTER`, `LISTEN`, `PORT` non traduits dans l'aide française ; argument `collecteur` sans aide.
- [ ] Hors spécification (en G3, l'adresse invalide renvoyée par un filtre donne `filter_failed`) : un filtre qui renvoie une adresse invalide est compté `package_too_large` au lieu de `filter_failed` (`adapters/sealer.py`) ; `veilleur.db` en 0644 (0600 suggéré) ; requêtes non authentifiées non limitées en débit et corps lu avant l'authentification ; `history` sans plafond de jobs ; `export` après purge redondant ; `subscription show`/`export` par `uid` ambigus entre jumelages ; `GET` avec corps accepté ; une faute dans `pairings` d'une déclaration d'équipe supprime l'abonnement ; `1` et `1.0` donnent deux collectes distinctes (EF-04).

Reste hors de G2, prévu plus loin : client HTTP réel (G3 ; G2 fournit le mode hors ligne), notificateurs `ntfy` et `webhook` et leur configuration (G3), rendus `markdown` et `html` (G4).

## G3 — Client HTTP, collecteurs, filtres, notificateurs (EF-02 à EF-06, EF-20, EF-52, ES-08)

- [x] Client HTTP :
  - cache, délais, quotas par hôte ;
  - `robots.txt`, `User-Agent` ;
  - mode hors ligne ;
  - **garde SSRF** : résolution DNS puis contrôle de chaque adresse, à chaque redirection, en IPv4 et IPv6.
- [x] Collecteurs `rss`, `json_api`, `page`, avec leurs schémas ; tests sur réponses enregistrées.
- [x] Filtres : mots-clés, expressions régulières, dédoublonnage.
- [x] Notificateurs `ntfy` et `webhook` (signé).
- [x] `GET /v1/subscriptions` (réponse à la question 1 de G2), spécification du protocole en anglais et en français.
- [x] Guide « écrire un collecteur » (`docs/{en,fr}/writing-a-collector.md`) et greffon d'exemple hors du paquet principal.

Fini quand : tentatives SSRF (adresses privées, DNS piégé, redirection) refusées par les tests ; les trois collecteurs passent sur leurs réponses enregistrées.

## G4 — Rendus et récepteur de référence (EF-43, cahier §5)

- [ ] Rendus `markdown` et `html` dans les deux langues (gabarits sans JavaScript ni ressource externe).
- [ ] Récepteur de référence `veilleur-receive` : collage du code de jumelage, `pull --folder`, vérification, dépôt des rapports ; lecture d'un dossier exporté (EF-51).

Fini quand : test de bout en bout serveur → récepteur, par HTTP (application WSGI) et par dossier.

## G5 — Déploiement (ENF-01 à ENF-08)

- [ ] `flake.nix` :
  - paquet, construit par uv2nix d'après `uv.lock` ;
  - `nixosModules.default` et `nixosModules.container` ;
  - `devShells.default` (uv, Python 3.12, gh) et `.envrc` (`use flake`) pour direnv.
- [ ] Module de service (`services.veilleur`) :
  - inerte si `enable = false` ;
  - service et minuterie du tour, durcissement systemd ;
  - `proxy = "caddy" | "external"` : Caddy sans journal d'accès, ou adresse d'écoute interne ;
  - ntfy intégré, externe ou aucun ;
  - secrets fournis par chemins (sops-nix, agenix) ou générés ;
  - `backupPaths` et service de copie cohérente de la base ;
  - options des greffons et de la langue.
- [ ] Assertions :
  - `publicHost` obligatoire ;
  - conflit de ports avec un autre service de l'hôte qui écoute sur 80 ou 443 ;
  - rappel IPv4 seulement en mode conteneur.
- [ ] Module conteneur (`services.veilleur-container`) :
  - `systemd-nspawn` à utilisateurs privés ;
  - réseau privé et redirection des ports ;
  - pare-feu sortant : ni hôte, ni réseaux privés, ni 100.64/10, port 25 fermé ;
  - `memoryMax`, plafond de processus.
- [ ] Exemple d'intégration dans une configuration d'hôte existante (`deploy/nixos/examples/`) :
  - fichier de réglages (`enable`, `publicHost`, `ntfyHost`, `acmeEmail`, `memoryMax`) ;
  - chargement par entrée de flake `github:Cafeinoman/veilleur/<étiquette>`, ou par `builtins.getFlake` avec `narHash` ;
  - l'exemple **s'évalue sur n'importe quelle machine**.
- [ ] Exemple de VPS dédié (`deploy/nixos/examples/vps/`).
- [ ] Tests en VM NixOS dans `nix flake check` (installation complète ; mode `proxy = "external"` derrière un Caddy d'hôte), ajoutés à la CI.
- [ ] Repli pour les autres distributions : unités systemd, `Caddyfile`, extrait ntfy dans `deploy/systemd/`.
- [ ] Guide d'administration `docs/{en,fr}/admin-guide.md` :
  - installation sur VPS et en conteneur ;
  - intégration dans une configuration d'hôte ;
  - choix de `publicHost` (nom plutôt qu'IP, pas d'AAAA en mode conteneur) ;
  - jumelage, sauvegarde, mise à jour, retour arrière.

Fini quand : `nix flake check` et les tests en VM sont verts, en local et dans la CI.

## G6 — Publication 0.1.0

- [ ] Actions GitHub fixées par empreinte de commit ; Dependabot pour les actions et `uv.lock`.
- [ ] `SECURITY.md` (signalement privé par GitHub), `CONTRIBUTING.md` et `CONTRIBUTING.fr.md` (branches, PR, traductions, contrôles).
- [ ] Recherche de secrets dans tout l'historique (`gitleaks`).
- [ ] Vérification du nom sur PyPI, et de l'absence de marque déposée.
- [ ] Version 0.1.0 : étiquette `v0.1.0`, notes de version bilingues, release GitHub. La publication sur PyPI est un arbitrage de l'utilisateur, à poser en question en attente.
