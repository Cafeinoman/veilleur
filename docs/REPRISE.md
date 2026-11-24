# Veilleur — reprise au standard `/architecte`

> État des lieux du dépôt au 2026-11-19 (branche `main`, commit `0be164e`, après la PR #11) et **table de
> correspondance** entre les anciens documents de pilotage (`cahier_des_charges.MD`, `plan.md`, `CLAUDE.md`) et les
> nouveaux (`docs/SPEC.md`, `docs/adr/`, `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/DEPLOIEMENT.md`). Rien ne
> disparaît sans une ligne ici. Un test du lot J7-L1 vérifie que chaque identifiant de la colonne « ancien » a une
> destination qui existe (`docs/TEST-STRATEGY.md`, §4).

## 1. Inventaire de l'existant

| Domaine | État constaté |
|---|---|
| Version | 0.1.0 alpha, étiquette `v0.1.0`, release GitHub en préversion ; étiquettes de lot `g0` à `g6` |
| Paquets | espace de travail uv : `veilleur` (`src/`, ≈ 6 000 lignes), `veilleur-protocol` (`protocol/`), `veilleur-receive` (`receiver/`) ; même numéro de version |
| Dépendances d'exécution | `google-re2`, `veilleur-protocol` (qui dépend de `pycryptodomex`) |
| Architecture | hexagonale ; quatre contrats `lint-imports` (cœur isolé, couches, protocole autonome, récepteur sans serveur) |
| Greffons fournis | collecteurs `rss`, `json_api`, `page` (un module chacun) ; filtres `keywords`, `regex`, `dedup` (dans `adapters/filters/__init__.py`) ; rendus `markdown`, `html` (`adapters/renderers/__init__.py`) ; notificateurs `ntfy`, `webhook` (`adapters/notifiers/__init__.py`, hors *entry points*) |
| Stockage | SQLite, migrations `0001_initial.sql`, `0002_notification_topic.sql` |
| Tests | 1 314 tests collectés, dont 758 dans `tests/verif/` (vérificateurs de G0-R à G6) ; 39 `xfail` stricts, tous rattachés à une réserve (§4) |
| Contrôles | `uv run pytest`, `ruff check src tests tools protocol receiver`, `mypy` (strict), `lint-imports` ; `tools/check_vectors.py` (libsodium) et `nix flake check` en CI ; **pas de `justfile`** |
| CI | `.github/workflows/ci.yml` : matrice uv Python 3.12 et 3.13 (contrôles requis de `main`) ; travail Nix (`nix flake check -L`, VM) ; actions fixées par empreinte |
| Déploiement | `flake.nix`, `deploy/nixos/` (module, conteneur, ports, tests en VM), `deploy/systemd/` (repli) ; guide `docs/{en,fr}/admin-guide.md` |
| Documentation publique | `docs/{en,fr}/` : `design.md`, `protocol.md` (normatif en anglais), `threat-model.md`, `writing-a-collector.md`, `admin-guide.md`, `translating.md`, `release-notes.md` ; `README*.md`, `CONTRIBUTING*.md`, `SECURITY.md` |
| Pilotage | `cahier_des_charges.MD` (198 lignes, §1 à §10), `plan.md` (G0-R à G6 et réserves), `CLAUDE.md` du projet, `.claude/settings.json` |
| PR | #1 à #7 (lots G0-R à G6), #10 (étiquette 0.1.0), #11 (fin de l'enchaînement) fusionnées ; **ouvertes** : #8 (`actions/checkout` 4.4.0 → 7.0.1) et #9 (`setup-uv` 6.8.0 → 10.3.3), Dependabot |

## 2. Table de correspondance

Légende de la colonne « Destination » : `SPEC §x` = section de `docs/SPEC.md` ; `ADR-nnnn` = `docs/adr/` ; `Rnn` =
réserve de `docs/PLAN.md` ; `J<n>-L<m>` = lot de `docs/PLAN.md` ; `Dn` = question de `docs/DECISIONS.md`.

### 2.1 Cahier §1 à §4

| Ancien | Destination | Remarque |
|---|---|---|
| Préambule (document de référence, version 1) | SPEC, préambule | version 2 |
| §1 Objet | SPEC §1 | inchangé |
| §2 Acteurs | SPEC §2 | administrateur : politique `robots.txt`, limites par hôte, responsabilité des sources |
| §3 Périmètre | SPEC §3 | ajouts DV ; JavaScript et PyPI explicitement WON'T ; frontière authentification précisée (ADR-0024) |
| §4 Glossaire | SPEC §4 | trois termes ajoutés |

### 2.2 Exigences fonctionnelles (cahier §5)

| Ancien | Destination | Statut |
|---|---|---|
| EF-01 | SPEC §5.1, ADR-0013, ADR-0028 | livré |
| EF-02 | SPEC §5.1, ADR-0015 | livré (R17) |
| EF-03 | SPEC §5.1 | livré |
| EF-04 | SPEC §5.1 | livré (R18) |
| EF-05 | SPEC §5.1 | livré (R09) ; avertissements ajoutés à l'état |
| EF-06 | SPEC §5.1, ADR-0014, **ADR-0022** | **révisée** : « respect de `robots.txt` » retiré (devient `enforce`) ; `Retry-After` ajouté ; J9 |
| — (nouveau) | SPEC §5.1 EF-07, ADR-0022 | alerte au premier passage outre ; J9-L3 |
| EF-10 | SPEC §5.2, ADR-0010 | livré (R11, R16) |
| EF-11 | SPEC §5.2, ADR-0010 | livré |
| EF-12 | SPEC §5.2 | livré (R17) |
| EF-13 | SPEC §5.2 | livré |
| EF-14 | SPEC §5.2 | livré |
| EF-20 | SPEC §5.3, ADR-0015, ADR-0016 | livré (R13) |
| EF-21 | SPEC §5.3 | livré |
| EF-30 | SPEC §5.4 | livré |
| EF-31 | SPEC §5.4, ADR-0011 | livré ; expiration ajoutée (DV-06) |
| EF-32 | SPEC §5.4, ADR-0011 | livré |
| EF-40 | SPEC §5.5 | livré |
| EF-41 | SPEC §5.5 | livré |
| EF-42 | SPEC §5.5 | livré |
| EF-43 | SPEC §5.5, ADR-0018 | livré (R19) |
| EF-44 | SPEC §5.5 | livré |
| EF-45 | SPEC §5.5 | livré (R15) |
| EF-50 | SPEC §5.6 | livré |
| EF-51 | SPEC §5.6, ADR-0019 | livré (R15) |
| EF-52 | SPEC §5.6, ADR-0017 | livré (R06) ; compte `robots_ignored` ajouté |
| EF-60 | SPEC §5.7 | livré (R03, R14) |
| EF-61 | SPEC §5.7 | livré |
| EF-62 | SPEC §5.7 | livré |
| EF-70 | SPEC §5.8 | livré (R21) ; `sources` montre les avertissements |
| EF-71 | SPEC §5.8 | livré |
| EF-72 | SPEC §5.8, ADR-0004 | livré |
| EF-80 | SPEC §5.9, ADR-0005 | livré (R21) |
| EF-81 | SPEC §5.9, ADR-0005 | livré |
| EF-82 | SPEC §5.9 | livré ; étendu aux codes d'avertissement |

### 2.3 Exigences de sécurité (cahier §6)

| Ancien | Destination | Statut |
|---|---|---|
| ES-01 | SPEC §6 | livré |
| ES-02 | SPEC §6, ADR-0007 | livré |
| ES-03 | SPEC §6, ADR-0007, ADR-0008 | livré |
| ES-04 | SPEC §6, ADR-0008 | livré (R01) |
| ES-05 | SPEC §6, ADR-0019 | livré (R12, R15) |
| ES-06 | SPEC §6, ADR-0007 | livré (R04) |
| ES-07 | SPEC §6, ADR-0008 | livré (R02) |
| ES-08 | SPEC §6, ADR-0014 | livré (R05) ; étendu à POST et sessions |
| ES-09 | SPEC §6 | livré ; étendu (alerte sans adresse, corps, cookies) |
| ES-10 | SPEC §6 | livré (R07, R08) |
| ES-11 | SPEC §6 | livré (R04, R13) |
| ES-12 | SPEC §6 | livré |
| ES-13 | SPEC §6, ADR-0009 | livré (R22) |

### 2.4 Spécifications techniques (cahier §7)

| Ancien | Destination | Remarque |
|---|---|---|
| §7.1 Architecture | SPEC §7.1, ADR-0003 | surface publique de l'API des greffons ajoutée (ADR-0028) |
| §7.2 Stockage | SPEC §7.2, ADR-0004 | tables à venir annoncées |
| §7.3 Bibliothèque de protocole | SPEC §7.3, ADR-0008, ADR-0009 | protocole inchangé en 0.2.0 et 0.3.0 |
| §7.4 Interface HTTP `/v1` | SPEC §7.4, ADR-0012 | inchangée |
| §7.5 Tâches longues | SPEC §7.5 | remise à zéro du quota, plafond de tâches (R13) |
| — (nouveau) | SPEC §7.6 | tableau des réglages du client HTTP |

### 2.5 Exigences non fonctionnelles (cahier §8)

| Ancien | Destination | Statut |
|---|---|---|
| ENF-01 | SPEC §8, ADR-0006, ADR-0020, DEPLOIEMENT | livré (R20, R23) |
| ENF-02 | SPEC §8, ADR-0020 | livré |
| ENF-03 | SPEC §8 (texte et jetons identiques) | livré (R20) |
| ENF-03b | SPEC §8 (texte et jetons identiques), ADR-0006 | livré (R20) |
| ENF-04 | SPEC §8 | livré (R07) |
| ENF-05 | SPEC §8, DEPLOIEMENT | livré |
| ENF-06 | SPEC §8, ADR-0020 | livré ; tests du conteneur et du repli mentionnés |
| ENF-07 | SPEC §8 | livré, **non vérifié** (R23) |
| ENF-08 | SPEC §8, DEPLOIEMENT | livré |
| ENF-09 | SPEC §8, TEST-STRATEGY | livré |

### 2.6 Contraintes de développement (cahier §9)

| Ancien | Destination | Remarque |
|---|---|---|
| Licence, en-tête SPDX | SPEC §9, ADR-0001 | inchangé |
| Langues du code et des textes | SPEC §9, ADR-0005 | inchangé |
| Contrôles avant commit | SPEC §9, ADR-0029 | `just test` (J7-L1) |
| Dépôt public, CI, actions fixées | SPEC §9, ADR-0021, ADR-0029 | inchangé |
| Une branche par fonctionnalité, fusion par l'utilisateur | SPEC §9, ADR-0002 | branche `claude/<identifiant>-<sujet>` |

### 2.7 Décisions (cahier §10)

Chaque ligne de l'ancien §10 contient plusieurs décisions ; chacune a sa destination.

| Ancien (date, objet) | Décisions qu'elle contient | Destination |
|---|---|---|
| 2026-11-15, nom et licence | nom ; EUPL-1.2 ; bilingue ; GitHub | ADR-0001 |
| 2026-11-15, branches et PR | une branche et une PR par fonctionnalité ; fusion par l'utilisateur ; **enchaînement sans confirmation** | ADR-0002 ; l'enchaînement est **abandonné** (décision du 2026-11-19) |
| 2026-11-15, intégration NixOS | modules inertes ; frontal et ntfy au choix ; secrets et sauvegarde de l'hôte | ADR-0006 |
| 2026-11-15, langues | textes sources anglais ; un catalogue français ; `argparse` traduit | ADR-0005 |
| 2026-11-15, cryptographie | XChaCha20-Poly1305 plutôt que zip chiffré ; empreinte du corps signée ; rotation signée ; garde SSRF dans le client | ADR-0007 (garde : aussi ADR-0014) |
| 2026-11-17, protocole 1.0 | tailles de `key_id`/`uid` ; en-tête de 30 octets ; clé propre au jumelage ; numéro des `state`/`history` ; corps de `PUT` scellé ; ordre des contrôles ; JSON strict ; zip restreint ; fin de confiance à l'ancienne clé | ADR-0008 |
| 2026-11-17, seconde implémentation | PyNaCl en développement seulement ; portée de la règle `pycryptodomex` | ADR-0009 |
| 2026-11-17, cœur G2 | abonnement à un jumelage ; abonnement d'équipe N fois ; espace d'`uid` par jumelage ; pierres tombales | ADR-0010 |
| (même ligne) | `reported` ; `delta` contre `reported` ; premier `state` dès la première collecte ; `state`/`history` depuis `reported` | ADR-0011 |
| (même ligne) | document d'abonnement et codes fixés par le protocole §9 ; schémas sans dépendance ; autorisation par défaut des collecteurs | ADR-0012, ADR-0013, ADR-0010 |
| (même ligne) | 120 requêtes par minute ; `Accept-Language` ; `wsgiref` | ADR-0012, ADR-0005 |
| 2026-11-18, réponses G2 | `GET /v1/subscriptions` ; compléments G2 (`collectors allow|deny|default`, `key rotate`, `serve`, tables) | ADR-0012, ADR-0010, ADR-0004 |
| 2026-11-18, G3 | garde SSRF (une adresse interne suffit, IPv4 enfouie, Teredo, pas de seconde résolution) | ADR-0014 |
| (même ligne) | **`robots.txt` illisible refuse, absent autorise** | ADR-0014, **révisée par ADR-0022** (devient le comportement `enforce`) |
| (même ligne) | délai 1 s, quota 200 par hôte et par processus ; 5 Mo, 30 s, 5 redirections ; cache ; codes stables ; hors ligne | ADR-0014, révisés par ADR-0025, ADR-0026 |
| (même ligne) | `rss` jamais complet ; `page` ; sélecteurs sans dépendance ; expat sans DTD ; `dedup` | ADR-0015 |
| (même ligne) | `check_params` ; `select` | ADR-0013 |
| (même ligne) | notifications par jumelage, sujet aléatoire, `ntfy`, `webhook` ; notificateurs hors garde SSRF ; greffon notificateur utilisé | ADR-0017, ADR-0014 |
| 2026-11-18, filtre `regex` | RE2 ; syntaxe ; abandon de l'analyse statique sous `re` | ADR-0016 |
| 2026-11-18, G4 | rendus : valeurs hostiles, plafonds, paquet scellé sans rendus | ADR-0018 |
| (même ligne) | récepteur autonome ; `pair`, `pull` ; dépôt ; état en 600 ; trou couvert par un `state` ; ancienne clé remplacée par un `state` ; export pendant 90 jours ; **limite admise** ; adresse avec caractère de contrôle non liée | ADR-0019, ADR-0018 |
| 2026-11-18, G5 | uv2nix et *wheels* ; greffons par chemin de recherche ; `veilleur-admin` ; ntfy intégré ; copie cohérente ; conteneur `nftables` ; DNS publics ; identifiants systemd ; `noAaaaRecord` ; greffon de test ; deux tests en VM de plus ; périmètre de l'assertion de ports ; ntfy du conteneur ; échec si base absente | ADR-0020 |
| 2026-11-18, G6 | version commune 0.1.0 ; `gitleaks` ; notes de version ; `SECURITY.md` bilingue | ADR-0021 |
| 2026-11-18, réponses G6 | nom conservé ; pas de PyPI ; étiquette `v0.1.0` et release | ADR-0021, ADR-0001 |
| 2026-11-19, fin de l'enchaînement | un lot par session, `/clear` puis `/livrer` | ADR-0002 |

### 2.8 `plan.md`

| Ancien | Destination | Remarque |
|---|---|---|
| Mode de travail : arrêts | ADR-0002 ; `CLAUDE.md` réécrit (J7-L1) | questions dans `docs/DECISIONS.md` au lieu de « Questions en attente » |
| Mode de travail : une branche par lot, PR, CI verte, fusion par l'utilisateur | ADR-0002, CLAUDE.md (J7-L1) | PR ouverte par `/livrer` |
| Mode de travail : un lot par session, au plus 2 passages | ADR-0002 | inchangé |
| Mode de travail : avancer le lot suivant pendant qu'une PR attend | PLAN.md, « Règles du plan » | conservé |
| Mode de travail : mettre à jour le plan dans la branche du lot | PLAN.md, « Règles du plan » | statut changé par `/livrer` |
| Questions en attente (aucune) | DECISIONS.md | remplacée |
| Tableau d'état G0-R à G6 | PLAN.md `## Historique` | statut `fait`, étiquettes |
| G0-R, étapes 0 à 9 | PLAN.md `## Historique` ; droits du jeton GitHub (étape 0) → CLAUDE.md (J7-L1) | étapes non redécrites |
| G1 à G6, étapes cochées | PLAN.md `## Historique` | non redécrites |
| Réserves G1 à G6 | PLAN.md `## Réserves`, table §2.9 | toutes |

### 2.9 Réserves de `plan.md`

| Lot d'origine | Réserve (résumé) | Destination |
|---|---|---|
| G1 | correctifs du 7ᵉ passage (`a48c755`) non revus | R01 |
| G1 | `SECURITY.md` (ES-13) | levée en G6 |
| G1 | ordre des contrôles face à un `key_id` inconnu | levée en G2 |
| G2 | correctif B2 (`0e30a66`) non revu | R01 |
| G2 | EF-05 : liste paresseuse qui lève, code non textuel | R09 |
| G2 | déclaration d'équipe cassée | R10 |
| G2 | EF-10 : `sync_team` duplique un abonnement redéclaré | R16 |
| G2 | protocole §7.4 : empreinte après filtre | levée en G3 |
| G2 | ES-05 : rotation par un autre processus ; deux rotations en 90 jours | R12 |
| G2 | EF-12 : surrogate isolé → 500 | R17 |
| G2 | EF-70, EF-80 : noms de valeur non traduits | R21 |
| G2 (hors spéc.) | filtre et adresse invalide → `package_too_large` | R18 |
| G2 (hors spéc.) | `veilleur.db` en 0644 | R08 |
| G2 (hors spéc.) | requêtes non authentifiées non limitées, corps lu avant authentification | R04 |
| G2 (hors spéc.) | `history` sans plafond de tâches | R13 |
| G2 (hors spéc.) | `export` après purge redondant | R18 |
| G2 (hors spéc.) | `subscription show`/`export` par `uid` ambigus | R18 |
| G2 (hors spéc.) | `GET` avec corps accepté | R18 |
| G2 (hors spéc.) | faute dans `pairings` supprime l'abonnement | R11 |
| G2 (hors spéc.) | `1` et `1.0` : deux collectes | R18 |
| G3 | ES-08 : `304` sans contrôle du type | R05 |
| G3 | EF-12 : sélecteur de `page` non contrôlé à la réception | R17 |
| G3 | EF-02 : virgule entre guillemets dans un sélecteur | R17 |
| G3 (hors spéc.) | cache des motifs `regex` sans borne | R13 |
| G3 (hors spéc.) | motifs RE2 jusqu'à ≈ 4 s par champ | R13 |
| G3 (hors spéc.) | schéma de `pattern` muet sur RE2 | R17 |
| G3 (hors spéc.) | quota de 200 jamais remis à zéro dans `serve` | R26, fusionnée avec DV-03 (J10-L2) |
| G3 (hors spéc.) | webhook transmet le sujet ntfy | R06 |
| G3 (hors spéc.) | lecture du corps jusqu'à ≈ 2× le délai | R13 |
| G3 (hors spéc.) | course rare dans `cut` (`transport.py`) | R18 |
| G3 | empaqueter `google-re2` pour Nix | levée en G5 |
| G4 | limite admise (deux rotations et trou purgé) | R15 |
| G4 | inscription de la limite et passage en `xfail` non revus | R01 |
| G4 | export : pas de `state` entre la fin des 90 jours et le tour suivant | R15 |
| G4 | export : paquet jugé sur sa date, pas sur sa clé | R15 |
| G4 | rendus : U+061C ; adresses hors plafond ; texte de lien non abrégé | R19 |
| G4 | récepteur : code non UTF-8 → trace d'appels | R14 |
| G4 (hors spéc.) | deux rotations sans paquet intermédiaire | R15 |
| G4 (hors spéc.) | paquet forgé couvert par un `state` ignoré sans signalement | R02 |
| G4 (hors spéc.) | `state` reconstruit avant un `delta` lisible de même numéro | R15 |
| G4 (hors spéc.) | réponse JSON très profonde → `RecursionError` | R13 |
| G4 (hors spéc.) | code de jumelage en argument répété sur stderr | R03 |
| G5 | port 2019 accepté | R20 |
| G5 | `ntfy.listenAddress` IPv6 sans crochets | R20 |
| G5 | autres écritures de l'adresse joker | R20 |
| G5 | formes inutilisables de `publicHost` | R20 |
| G5 | `builtins.getFlake` sans `rev` dans le guide | R20 |
| G5 (hors spéc.) | unité socket, `defaultSSLListenPort`, `listenAddresses` de sshd non lus | R20 |
| G5 (hors spéc.) | faux positif sshd sur le port interne | R20 |
| G5 (hors spéc.) | unité des jetons ntfy en root | R07 |
| G5 (hors spéc.) | `backupPaths` non vide module désactivé | R20 |
| G5 (hors spéc.) | bloc de frontal ntfy (`proxy_buffering`, WebSocket) | R20 |
| G5 | non vérifié : ENF-07, Let's Encrypt réel, `aarch64-linux` | R23 |
| G6 | `CONTRIBUTING*.md` ne citent pas `tools/check_vectors.py` | R22 |
| G6 | recherche de marque limitée à l'INPI | R24 |
| G6 | exclusion `.gitleaks.toml` dépendante du dossier | R22 |
| brief §4.4 | PR Dependabot #8 et #9 | R25 |

### 2.10 `CLAUDE.md` du projet

| Ancien | Destination |
|---|---|
| Objet du projet | `CLAUDE.md` réécrit (J7-L1) |
| Documents qui font foi (cahier, plan, design, translating) | `CLAUDE.md` réécrit : `docs/SPEC.md`, `docs/adr/`, `docs/PLAN.md` ; `design.md` et `translating.md` gardés comme documentation |
| « Toute évolution met à jour le cahier d'abord » | `CLAUDE.md` réécrit : « `docs/SPEC.md` d'abord » |
| Questions et arrêts (via « Questions en attente » de `plan.md`) | ADR-0002 ; `docs/DECISIONS.md` |
| Ne jamais fusionner une PR | règle commune (`~/.claude/CLAUDE.md`), non recopiée |
| Règles : généricité, architecture, langues, licence, sécurité, tests sans réseau, données | `CLAUDE.md` réécrit (règles propres conservées) ; SPEC §3, §6, §7.1, §9 |
| Commandes | `CLAUDE.md` réécrit : `just test` ; outils `i18n.py`, `protocol_vectors.py`, `check_vectors.py` |
| Git : branche `claude/<lot>-<sujet>` | ADR-0002, ADR-0029 : `claude/<identifiant>-<sujet>` |
| Accès GitHub : droits listés dans `plan.md` G0-R | `CLAUDE.md` réécrit (tableau des droits du jeton) |
| Identité, commits, pas de `--force` | règles communes, non recopiées |
| Étiquette par lot fusionné, puis versions | D6 (qui pose les étiquettes, et lesquelles) |

## 3. Écarts constatés entre le code et la documentation

| # | Écart | Traitement |
|---|---|---|
| E1 | `urllib.robotparser` applique la première règle qui correspond, alors que le cahier §10 invoque RFC 9309 (règle la plus longue) [Certain : essai local] | ADR-0022, J9-L1 |
| E2 | La docstring de `adapters/http/client.py` dit `robots.txt` « read once per process » ; le code le relit après 24 h | J9-L1 |
| E3 | Un `robots.txt` illisible n'est pas mémorisé : chaque requête suivante vers l'hôte le redemande (et consomme du quota) | J9-L1 (ADR-0022, point 6) |
| E4 | `Retry-After` n'est pas lu, alors qu'il fait partie de la politesse attendue | ADR-0026, J9-L1 |
| E5 | DV-03 parle d'un quota « par tour » ; le code le compte par processus et `serve` ne le remet jamais à zéro | R26, ADR-0025, J10-L2 |
| E6 | La surface de l'API des greffons n'est déclarée nulle part ; le greffon externe importe quatre modules du cœur | ADR-0028, J7-L3 |
| E7 | `tests/verif/test_design_follows_spec.py` et `tests/verif/test_g6_release.py::test_the_specification_records_the_decisions_of_the_release` lisent `cahier_des_charges.MD` | J7-L2 (redirection vers SPEC et ADR-0021) |
| E8 | `docs/{en,fr}/design.md` s'ouvre sur « décrit ce que Veilleur sera… G2 existe aujourd'hui », périmé depuis 0.1.0 ; sa feuille de route s'arrête à G6 | J7-L2 |
| E9 | Les docstrings et en-têtes de tests citent « cahier » (EF, ES, §) | J7-L2 (« spec », identifiants inchangés) |
| E10 | `veilleur.db` créé en 0644 hors systemd ; atténué par le dossier d'état forcé en 0700 (`open_app`) et `UMask=0077` des unités [Certain : lecture du code] | R08 (rang abaissé dans P1, voir PLAN) |
| E11 | `.claude/settings.json` ne permet pas `just` | J7-L1 |
| E12 | `CONTRIBUTING*.md` ne citent pas `tools/check_vectors.py` | R22, J7-L1 |

Aucun écart n'a été trouvé entre `lint-imports` et SPEC §7.1, ni entre les routes de `wsgi.py` et SPEC §7.4 [Probable :
lecture des contrats et de la table de routes, sans exécution de chaque route].

## 4. Tests `xfail` stricts et réserves

| Réserve | Tests `xfail` (`tests/verif/`) |
|---|---|
| R01 | cas « accepted limit » de `test_g4_verif_pass3.py` (objet de la revue, voir R15) |
| R02 | `test_g4_verif_pass3.py::test_a_forged_package_is_reported_even_when_a_state_covers_it` |
| R03 | `test_g4_verif.py::test_a_code_given_as_an_argument_is_not_repeated` |
| R05 | `test_g3_verif.py::test_a_cached_answer_is_checked_against_the_expected_content_types` |
| R07 | `test_g5_verif.py::test_the_unit_that_draws_the_tokens_is_hardened` |
| R09 | `test_g2_core.py::test_lazy_collected_items_that_fail_do_not_stop_the_round`, `::test_collector_error_with_a_non_string_code_does_not_stop_the_round` |
| R10 | `test_g2_cli.py::test_a_broken_team_declaration_does_not_stop_the_other_subscriptions` |
| R12 | `test_g2_core.py::test_running_service_follows_a_key_rotation`, `::test_two_rotations_within_90_days_keep_receivers_following` |
| R13 | `test_g3_pass3.py::test_the_compiled_pattern_cache_is_bounded`, `test_g4_verif.py::test_a_very_deep_answer_is_a_refusal` |
| R14 | `test_g4_verif.py::test_a_pairing_code_that_is_not_text_is_refused_cleanly` |
| R15 | `test_g4_verif_pass3.py::test_a_member_back_after_a_purge_follows_two_rotations_from_a_folder`, `::test_a_member_back_after_a_purge_follows_two_rotations_over_http`, `::test_two_rotations_without_a_package_between_them_are_followed`, `::test_a_member_able_to_read_the_last_delta_still_gets_it`, `::test_an_export_just_after_the_window_with_packages_not_yet_purged` ; `test_g4_verif_pass2.py::test_a_package_signed_by_the_old_key_just_after_the_rotation_is_replaced_too` |
| R16 | `test_g2_core.py::test_team_subscription_removed_then_declared_again_exists_once` |
| R17 | `test_g2_api.py::test_lone_surrogate_in_parameters_is_a_400` ; `test_g3_verif.py::test_unsupported_page_selector_is_refused_on_reception`, `::test_quoted_attribute_value_with_a_comma` |
| R18 | `test_g2_pass2.py::test_filter_returning_a_bad_address_is_counted_as_a_filter_failure` |
| R19 | `test_g4_verif.py::test_the_arabic_letter_mark_is_removed`, `::test_addresses_count_against_the_cap_of_a_rendering`, `::test_the_text_of_a_link_is_shortened` ; `test_g4_verif_pass2.py::test_an_address_with_the_arabic_letter_mark_is_not_a_link` |
| R20 | `test_g5_pass3.py::test_the_internal_port_is_not_the_admin_port_of_caddy`, `::test_the_tls_default_port_of_nginx_is_reported`, `::test_a_port_given_in_the_listen_addresses_of_sshd_is_reported`, `::test_sshd_bound_to_another_address_is_accepted` ; `test_g5_pass2.py::test_an_ipv6_address_for_ntfy_is_refused_or_bracketed`, `::test_a_socket_unit_is_reported` ; `test_g5_verif.py::test_other_spellings_of_the_wildcard_are_refused`, `::test_a_public_host_that_is_not_a_host_is_refused`, `::test_the_documented_get_flake_reference_is_locked`, `::test_a_disabled_service_lists_nothing_to_back_up` |
| R21 | `test_g2_cli.py::test_french_help_has_no_english_placeholder` |
| R22 | `test_g6_release.py::test_the_guide_lists_every_check_of_the_ci` |

Total : 39 tests, soit tous les `xfail` de `tests/verif/` au 2026-11-19. R04, R06, R08, R11, R23 à R26 n'ont pas de test ;
le lot qui les lève en écrit un.

## Sources

- `cahier_des_charges.MD`, `plan.md`, `CLAUDE.md`, `.claude/settings.json`, `pyproject.toml`, `.github/workflows/ci.yml`,
  `src/`, `tests/`, `deploy/`, `docs/{en,fr}/` ; commit `0be164e`, consultés le 2026-11-19.
- `gh pr list --state all` sur `Cafeinoman/veilleur`, 2026-11-19.
- `uv run pytest --collect-only -q`, 2026-11-19.
