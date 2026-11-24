# Brief — `veilleur` : reprise au standard architecte, politique `robots.txt`, demandes et réserves

## 1. Objectif

Veilleur existe : version 0.1.0 publiée (étiquette `v0.1.0`, release GitHub en préversion), lots G0-R à G6
livrés avec réserves. Il a été construit **avant** le standard `/architecte` : son pilotage tient dans
`cahier_des_charges.MD` et `plan.md` à la racine, dans un format propre. Cette phase d'architecture ne repart
pas de zéro : elle **reprend l'existant** pour trois objectifs.

a) **Mise au standard.** Réécrire la documentation de pilotage au format `/architecte` (`docs/SPEC.md`,
   `docs/adr/`, `docs/PLAN.md`, `docs/RISKS.md`, `docs/TEST-STRATEGY.md`, `docs/DECISIONS.md`,
   `docs/DEPLOIEMENT.md`) **sans rien perdre** du cahier ni du plan, et planifier la remise au propre de
   l'organisation du code et du dépôt pour qu'elle corresponde à ces documents, sans changer le comportement.

b) **`robots.txt`.** Retirer des exigences fonctionnelles le respect de `robots.txt` par Veilleur, et le
   remplacer par une **alerte au premier passage outre** un `robots.txt` par un collecteur.

c) **Évolutions.** Intégrer les demandes DV-01 à DV-06 du projet `veilleur-marches`
   (`~/projects/veilleur-marches/docs/DEMANDES-VEILLEUR.md`), et planifier la levée des réserves des PR de
   Veilleur, **de la plus importante à la moins importante**.

## 2. Contexte confirmé (ne pas reposer ces questions)

### 2.1 Le dépôt

- `~/projects/veilleur`, dépôt **public** `github.com/Cafeinoman/veilleur`, licence EUPL-1.2. `main` protégée
  (PR obligatoire, CI verte, administrateurs compris).
- Python 3.12+, SQLite, architecture hexagonale vérifiée par `lint-imports` (`core` ne dépend ni de `adapters`,
  ni de `apps`, ni du stockage, du réseau, de la traduction ou de la cryptographie). Trois paquets dans un
  espace de travail uv : `veilleur` (`src/`), `veilleur-protocol` (`protocol/`), `veilleur-receive`
  (`receiver/`). Environ 6 000 lignes dans `src/`.
- Déploiement NixOS fait (G5) : `flake.nix`, `nixosModules.default` et `.container`, tests en VM dans la CI,
  repli systemd. `docs/DEPLOIEMENT.md` résume l'existant (`docs/{en,fr}/admin-guide.md`, `deploy/`) ; ne pas
  le reconcevoir.
- Contrôles : `uv run pytest && uv run ruff check src tests tools protocol receiver && uv run mypy && uv run
  lint-imports`, plus `tools/check_vectors.py` et `nix flake check` dans la CI. **Pas de `justfile`.**
- `tests/verif/` existe déjà (tests des vérificateurs, écarts mineurs en `xfail` strict).
- Documentation publique bilingue `docs/en/` et `docs/fr/` (parité vérifiée par `tests/test_repository.py`) :
  `design.md`, `protocol.md` (normative en anglais), `threat-model.md`, `writing-a-collector.md`,
  `admin-guide.md`, `translating.md`, `release-notes.md`.
- PR Dependabot ouvertes : #8 (`actions/checkout` 4 → 7) et #9 (`setup-uv` 6 → 10), deux sauts de version
  majeure.

### 2.2 Documents à reprendre

- `cahier_des_charges.MD` : objet, acteurs, périmètre, glossaire, EF-01 à EF-82, ES-01 à ES-13, §7
  (architecture, stockage, protocole, API `/v1`, tâches longues), ENF-01 à ENF-09, §9 (contraintes), **§10
  (décisions datées, très denses : chacune contient plusieurs décisions structurantes)**.
- `plan.md` : mode de travail, état G0-R à G6, étapes cochées, **réserves sous chaque lot**.
- `CLAUDE.md` du projet : règles propres (généricité, i18n, licence, sécurité, tests sans réseau).
  L'enchaînement des lots sans confirmation est abandonné (cahier §10, 19/11/2026) : un lot par session,
  `/clear` puis `/livrer`.

### 2.3 Ce qui reste vrai

- Projet **générique** : aucune connaissance d'un domaine métier. Les demandes DV sont rédigées de façon
  générique et doivent le rester.
- Code, identifiants, commits, PR en anglais ; documents de pilotage en français ; tout texte lu par une
  personne traduit en français et en anglais.
- Pas de publication PyPI (décision du 18/11/2026).
- Le greffon `veilleur-marches` (projet distinct, en phase d'architecture) dépend de l'API des greffons
  (`veilleur.collectors`, ports, `Collected`, `CollectedItem`, client HTTP). **Toute réorganisation du code
  garde cette API stable**, ou la versionne avec une période de compatibilité.

## 3. À traiter en premier (parties les plus risquées)

1. **Changement de politique `robots.txt`.** C'est la seule décision qui change un engagement public du projet
   (README, guide, cahier §10 du 18/11/2026, critères de DV-01 et DV-02). À établir avant toute ligne de code :
   - [Probable] RFC 9309 s'adresse aux *crawlers* en général, pas seulement aux indexeurs ; l'argument le
     plus solide pour Veilleur est qu'il ne **découvre** pas de pages : il lit des adresses choisies par un
     humain, comme un lecteur de flux ou un récupérateur déclenché par l'utilisateur. Vérifier sur le web la
     pratique documentée de récupérateurs comparables (lecteurs RSS, récupérateurs « déclenchés par
     l'utilisateur » des grands moteurs) et la citer.
   - [Probable] En droit de l'Union (directive 2019/790, art. 4 ; en France, CPI art. L. 122-5-3), un titulaire
     peut s'opposer à la fouille de textes et de données « par des procédés lisibles par machine », et
     `robots.txt` est couramment invoqué comme tel. Passer outre peut priver l'administrateur de l'exception
     de fouille pour les contenus protégés. Cela ne bloque pas le changement, mais l'ADR le dit, et le guide
     d'administration renvoie la responsabilité à l'administrateur.
   - Le reste de la politesse reste dû : `User-Agent` honnête, délai et quota par hôte, `Retry-After`,
     `Crawl-delay` (DV-04). Aucun contournement d'une protection technique (401, 403, 429, défi anti-robot) :
     le périmètre §3 « contournement de protections anti-robots » reste hors périmètre.
2. **Mise au standard sans perte.** Le risque est d'oublier une décision du §10 ou une réserve en
   redécoupant. Produire une **table de correspondance** ancien → nouveau (chaque EF/ES/ENF, chaque décision
   du §10, chaque réserve) et la faire vérifier par un test ou une relecture du vérificateur.
3. **Stabilité de l'API des greffons** pendant la réorganisation du code (§2.3).

## 4. Exigences

### 4.1 Objectif a : mise au standard

**Documentation.**
- `docs/SPEC.md` reprend le cahier entier. **Les identifiants EF-xx, ES-xx, ENF-xx sont conservés** :
  commits, PR, tests et `docs/{en,fr}/design.md` y renvoient. Priorités MUST / SHOULD / COULD / WON'T : ce qui
  est livré en 0.1.0 est MUST ; les demandes DV et la levée des réserves sont priorisées.
- Une ADR par décision structurante du §10, au statut **`Accepté`**, datée de la décision d'origine, avec la
  mention « ADR rétrospective » (le contexte et les options écartées se reconstituent depuis le cahier,
  l'historique git et les PR #1 à #10). Seules les ADR nouvelles (§4.2, §4.3) sont `Proposé`.
- `docs/PLAN.md` au format du gabarit. Les lots G0-R à G6 y figurent comme **historique**, statut `fait`, avec
  leur étiquette git, sans être redécrits étape par étape. Les nouveaux lots suivent le format `J<n>-L<m>`.
  [Suppose] Numérotation : jalons nouveaux à partir de `J7` pour ne pas se confondre avec G0-G6 ; à trancher
  dans `DECISIONS.md` si une autre convention est préférable.
- Section `## Réserves` de `PLAN.md` : toutes les réserves de `plan.md`, chacune avec son lot d'origine et son
  test `xfail` éventuel, **dans l'ordre de priorité du §4.4**.
- `cahier_des_charges.MD` et `plan.md` ne sont pas supprimés dans la phase d'architecture : un lot les
  remplace par un renvoi vers `docs/` après la fusion de la PR `claude/architecture`.
- `docs/{en,fr}/design.md` restent des présentations publiques qui suivent `SPEC.md` ; seule leur référence
  (« le cahier ») change.
- `docs/DEPLOIEMENT.md` est un résumé qui renvoie au guide d'administration, pas une copie.

**Dépôt et code** (lots à planifier, pas à faire pendant l'architecture) :
- `CLAUDE.md` du projet réécrit au format de `/nouveau-projet` : documents qui font foi = `docs/PLAN.md`,
  `docs/SPEC.md`, `docs/adr/` ; règle « un lot = un identifiant `J<n>-L<m>`, branche
  `claude/<identifiant>-<sujet>` » ; règles propres conservées.
- `justfile` : `test` (tous les contrôles, y compris `check_vectors.py`), `fmt`, et ce qu'exige le standard ;
  la CI lance `nix develop -c just test` en plus de `nix flake check`.
- Organisation du code : l'architecte inventorie les écarts entre le code et `SPEC.md` §7.1 et propose une
  remise au propre **sans changement de comportement**, vérifiée par les tests existants inchangés. Pistes
  relevées, à confirmer [Suppose] : greffons fournis écrits dans des `__init__.py` (`adapters/filters`,
  `adapters/renderers`, `adapters/notifiers`) au lieu d'un module par greffon ; réglages HTTP dans
  `apps/server/context.py` ; `tests/verif/` découpé par passage (`test_protocol_g1_round2` à `round7`) plutôt
  que par exigence ; fichiers de pilotage à la racine (`cahier_des_charges.MD` en `.MD`). Ne pas proposer de
  réorganisation que rien ne justifie.

### 4.2 Objectif b : `robots.txt`

- **Retirer** de EF-06 le « respect de `robots.txt` », et des critères de DV-01 et DV-02 le refus
  `robots_disallowed`. Réviser la décision du 18/11/2026 (`robots.txt` illisible = refus) par une ADR.
- Le client HTTP **continue de lire** `robots.txt` (une fois par jour et par origine) : il en a besoin pour
  `Crawl-delay` (DV-04) et pour l'alerte.
- **Alerte au premier passage outre.** Quand un collecteur demande une adresse que `robots.txt` interdit à
  l'agent `Veilleur`, la requête part, et :
  - au **premier** cas pour un couple (collecte mutualisée, hôte), le serveur l'enregistre dans le journal
    d'administration (`event`), l'affiche dans `veilleur sources` avec un code stable (piste :
    `robots_ignored`), et la notification suivante le compte (« N sources passent outre `robots.txt` ») ;
  - les cas suivants pour le même couple ne réalertent pas, sauf si le contenu de `robots.txt` change
    (empreinte) [Suppose] ;
  - l'alerte ne contient **jamais l'adresse complète** (elle peut porter des paramètres d'abonnement,
    ES-09) : hôte, collecteur et règle `Disallow` en cause seulement ;
  - la notification ne porte que des comptes (EF-52).
- [Suppose] Un réglage de l'administrateur, par instance et par hôte, rétablit le respect strict
  (`robots = "enforce"`, défaut `"warn"`). Peu coûteux, il laisse le choix à chaque installation. À trancher
  dans `DECISIONS.md`.
- Le mécanisme d'avertissement de DV-05 sert probablement aussi à l'alerte : l'architecte vérifie s'il faut
  les livrer ensemble.
- Mettre à jour : README, guide d'administration (responsabilité de l'administrateur, CGU, opposition à la
  fouille), modèle de menace si besoin, notes de version, dans les deux langues.

**Critères d'acceptation à décliner** (indicatifs) : une adresse interdite est demandée et collectée ; une
seule alerte pour deux tours successifs ; une nouvelle alerte après changement de `robots.txt` ; aucune trace
de l'adresse ni des paramètres dans les journaux capturés ; avec `enforce`, refus `robots_disallowed` comme
aujourd'hui ; `robots.txt` absent ou illisible ne bloque plus la collecte.

### 4.3 Objectif c (1) : demandes DV

Reprendre DV-01 à DV-06 (besoin, forme, exigences de sécurité, critères d'acceptation) dans `SPEC.md`, en
gardant leurs identifiants et leur ordre de priorité (DV-01 demande ferme ; DV-02 et DV-04 indispensables hors
V1 du greffon). Ajustements :
- DV-01 et DV-02 : critères `robots.txt` réécrits selon §4.2.
- DV-03 : à fusionner avec la réserve G3 « quota de 200 requêtes par hôte jamais remis à zéro dans `serve` ».
- DV-04 : `Crawl-delay` reste appliqué quelle que soit la politique `robots.txt`.
- DV-02 : le hors-périmètre « collecte derrière une authentification interactive » reste ; la session
  éphémère sur pages publiques n'en est pas une, l'ADR le justifie.

### 4.4 Objectif c (2) : réserves, de la plus importante à la moins importante

Ordre proposé ; l'architecte peut le corriger en le justifiant. Critère : sécurité et secrets, puis
disponibilité du tour, puis exactitude, puis confort.

**P1 — Sécurité, secrets, correctifs jamais revus**
1. G1 : correctifs du 7ᵉ passage (`a48c755`, clés publiques d'ordre faible) non revus ; G2 : correctif B2
   (`0e30a66`) non revu ; G4 : inscription de la limite ES-05 et passage en `xfail` non revus. Un lot de
   revue indépendante, limité à ces diffs.
2. G4 : un paquet forgé couvert par un `state` valide est ignoré sans signalement.
3. G4 : un code de jumelage passé en argument est répété sur stderr (fuite de secret).
4. G2 : requêtes non authentifiées non limitées en débit, corps lu avant l'authentification.
5. G3 : une réponse `304` sert le cache sans contrôler son type (ES-08).
6. G3 : le webhook transmet le sujet ntfy du jumelage à un tiers.
7. G5 : l'unité qui tire les jetons ntfy tourne en root sans durcissement.
8. G2 : `veilleur.db` en 0644 ([Probable] atténué en déploiement par `UMask=0077`, à confirmer).

**P2 — Disponibilité du tour et du service** (le greffon `veilleur-marches` en dépend)
9. EF-05 : un greffon qui viole son contrat (liste paresseuse qui lève, code d'erreur non textuel) arrête le
   tour.
10. Déclaration d'équipe cassée (greffon absent) : `round` et `serve` échouent au lieu de `collector_missing`.
11. Une faute dans `pairings` d'une déclaration d'équipe supprime l'abonnement.
12. ES-05 : le service ne suit pas un `key rotate` fait par un autre processus ; deux rotations en moins de
    90 jours : la seconde remplace la première déclaration.
13. Coûts non bornés : motifs RE2 jusqu'à ≈ 4 s par champ, cache des motifs compilés sans borne, `history`
    sans plafond de tâches, réponse JSON très profonde (`RecursionError`), lecture du corps jusqu'à ≈ 2× le
    délai.
14. Récepteur : code de jumelage non UTF-8 → trace d'appels.

**P3 — Exactitude**
15. Export et rotations (G4) : pas de `state` entre la fin des 90 jours et le tour suivant ; paquet jugé sur
    sa date et non sa clé ; deux rotations sans paquet intermédiaire ; `state` reconstruit avant un `delta`
    lisible de même numéro ; limite admise du membre qui a manqué deux rotations (piste dans `plan.md`).
16. EF-10 : `sync_team` duplique un abonnement supprimé puis redéclaré dans la même seconde.
17. EF-12 : surrogate isolé → 500 au lieu de 400 ; sélecteur de `page` non contrôlé à la réception ; virgule
    entre guillemets dans un sélecteur ; schéma de `pattern` muet sur la syntaxe RE2.
18. Filtre qui renvoie une adresse invalide compté `package_too_large` au lieu de `filter_failed` ; `1` et
    `1.0` donnent deux collectes (EF-04) ; `subscription show`/`export` par `uid` ambigus ; `export` après
    purge redondant ; `GET` avec corps accepté ; course rare dans `cut` (`transport.py`).
19. Rendus : U+061C non retiré ; adresses hors du plafond de 2 millions de caractères ; texte de lien non
    abrégé.
20. Déploiement (G5) : port 2019 accepté ; `ntfy.listenAddress` IPv6 sans crochets ; autres écritures de
    l'adresse joker ; formes inutilisables de `publicHost` ; `builtins.getFlake` sans `rev` dans le guide ;
    conflits de ports non lus (socket, nginx SSL, `listenAddresses` ssh) et faux positif sshd ;
    `backupPaths` non vide module désactivé ; bloc de frontal ntfy (`proxy_buffering`, WebSocket).

**P4 — Confort, documentation, vérifications externes**
21. Aide française : `LABEL`, `LIMIT`, `AFTER`, `LISTEN`, `PORT` non traduits ; argument `collecteur` sans aide.
22. `CONTRIBUTING*.md` ne citent pas `tools/check_vectors.py` ; exclusion `.gitleaks.toml` dépendante du
    dossier de lancement.
23. Non vérifié : charge ENF-07, certificat Let's Encrypt réel, `aarch64-linux`.
24. Marque : recherche limitée à l'INPI (TMview, WIPO non consultés) — action de l'utilisateur, pas un lot.
25. PR Dependabot #8 et #9 : à traiter dans un lot d'entretien (sauts majeurs, CI à vérifier).

**Entrelacement avec les DV** : à proposer par l'architecte. Recommandation de départ : P1 avant DV-01 (service
public exposé) ; la politique `robots.txt` (§4.2) avant DV-01 et DV-02, dont elle change les critères ; DV-03
avec la réserve sur le quota ; DV-05 avec ou avant l'alerte `robots.txt` ; P2 avant DV-02, le plus gros
chantier. À confirmer dans `DECISIONS.md`.

## 5. Hors périmètre

- Exécution de JavaScript ; authentification interactive ; contournement d'une protection technique.
- Toute fonction propre aux marchés publics.
- Publication PyPI.
- Reconception du protocole 1.0, du déploiement NixOS ou de l'architecture hexagonale : on reprend.
- Réécriture de l'historique git publié.

## 6. Construire ou réutiliser

Étape 1 du gabarit **réduite** : le projet existe et la reprise est décidée. Ne comparer que pour les ajouts :
gestion des cookies de DV-02 (`http.cookiejar` de la bibliothèque standard ou code propre) et lecture de
`Crawl-delay` (`urllib.robotparser` la fournit déjà [Probable]). Pas de `BUILD-OR-REUSE.md` complet : un
paragraphe dans `SPEC.md` suffit.

## 7. Décisions attendues (ADR)

- ADR rétrospectives du §10 (`Accepté`).
- Politique `robots.txt` : passer outre avec alerte, réglage `enforce`, `robots.txt` illisible, cadre juridique.
- POST JSON (DV-01) : redirections, cache, corps.
- Sessions éphémères (DV-02) : portée, stockage des cookies, plafonds, rapport au hors-périmètre.
- Limites par hôte (DV-03) : format de configuration, minimum et maximum imposés, remise à zéro du quota.
- `Crawl-delay` (DV-04) : plafond, interaction avec le délai de 30 s.
- Avertissements (DV-05) et expiration (DV-06) : évolution de l'API des greffons, compatibilité.
- Compatibilité de l'API des greffons pendant la réorganisation du code.
- Version suivante : [Suppose] 0.2.0 après DV-01 et la politique `robots.txt`.

## 8. Contraintes de travail

- **Dépôt existant** : lancement par `/architecte veilleur <ce brief> --reprise`. La table de correspondance
  du §3 est `docs/REPRISE.md`. Fichiers nouveaux de `docs/` seulement (rien dans `docs/en/` ni `docs/fr/`) ;
  ni le code, ni `cahier_des_charges.MD`, `plan.md` ou `CLAUDE.md` ne sont touchés.
- `/nouveau-projet` ne s'applique pas tel quel (squelette existant) : ses exigences (justfile, `CLAUDE.md`,
  CI) deviennent un lot du plan.
- Dépôt public : `docs/` sera lu de tous ; aucune donnée personnelle, aucun nom de site réel propre à un
  domaine métier (DV-01 à DV-06 citent des exemples génériques, les garder ainsi).
- Les tests existants et ceux de `tests/verif/` ne sont ni affaiblis ni supprimés par la réorganisation ;
  un test `xfail` passe en vert quand sa réserve est levée.

## Sources

- `~/projects/veilleur/cahier_des_charges.MD`, `plan.md`, `CLAUDE.md`, `pyproject.toml`,
  `src/veilleur/adapters/http/client.py` (branche `main`, commit `e355ab0`), consultés le 19/11/2026.
- `~/projects/veilleur-marches/docs/DEMANDES-VEILLEUR.md` et `DECISIONS.md` (commit `4cccab5`), 19/11/2026.
- `~/claude-config/skills/architecte/` (`SKILL.md`, `gabarit.md`), `nouveau-projet`, `livrer`, 19/11/2026.
- PR GitHub `Cafeinoman/veilleur` #1 à #10 (`gh pr list`), 19/11/2026.
- RFC 9309 (Robots Exclusion Protocol) ; directive (UE) 2019/790, art. 4 ; CPI art. L. 122-5-3 : cités de
  mémoire, **à vérifier sur le web par l'architecte**.
