# Veilleur — cahier des charges

> Document de référence du projet : il dit **ce que** Veilleur doit faire et **comment**, dans ses grandes lignes. Il prime sur toute autre documentation (`docs/en/design.md`, `docs/fr/design.md` en sont des présentations et doivent le suivre). Toute évolution le met à jour d'abord. L'état d'avancement est dans `plan.md`.
> Version 1, 2026-11-15.

## 1. Objet

Veilleur est un **serveur de veille auto-hébergé**, libre (EUPL-1.2), installable par une petite équipe sur un serveur qu'elle contrôle. Il :
1. **collecte** des informations depuis des sources branchables : flux RSS/Atom, API JSON, pages web, et toute source écrite comme greffon ;
2. **repère** ce qui est nouveau, a changé ou a disparu d'un tour de collecte à l'autre ;
3. en fait des **rapports** : données structurées et rendu lisible ;
4. les **livre**, signés et chiffrés, à des **outils de réception**, par HTTPS ou par transfert de fichiers, avec une notification qui ne porte que des comptes.

L'outil de réception (ce qu'on fait des rapports : tri, archivage, rapprochement avec d'autres données, affichage) est **hors périmètre**. Veilleur fournit seulement une bibliothèque de protocole et un récepteur de référence minimal pour qu'on puisse en écrire un.

Veilleur est **générique** : il ne contient aucune connaissance d'un domaine métier particulier. Une source propre à un domaine s'ajoute par un greffon, maintenu hors du dépôt.

## 2. Acteurs

| Acteur | Rôle |
|---|---|
| **Administrateur** | installe et met à jour le serveur, crée et révoque les jumelages, déclare les abonnements d'équipe, autorise les collecteurs par jumelage, consulte l'état des sources |
| **Membre** (et son outil de réception) | jumelé une fois avec le serveur ; reçoit les rapports des abonnements qui le concernent ; peut créer ses propres abonnements si l'administrateur l'y autorise |
| **Auteur de greffon** | écrit un collecteur, un filtre, un rendu ou un notificateur, distribué comme paquet Python |
| **Auteur d'outil de réception** | lit les rapports grâce à la spécification du protocole, à la bibliothèque `veilleur-protocol` ou à ses vecteurs de test |

Un serveur sert **une équipe** (une poignée à quelques dizaines de membres) et a **un administrateur**. Ce n'est pas un service multi-locataire.

## 3. Périmètre

**Dans le périmètre** : collecte, détection des changements, filtres, rapports, scellement (chiffrement et signature), livraison HTTPS et par dossier, notification, jumelage, administration en ligne de commande, installation NixOS et repli pour les autres distributions Linux, traduction française et anglaise, bibliothèque de protocole, récepteur de référence.

**Hors périmètre** : l'outil de réception complet ; une interface web d'administration ; les comptes utilisateurs, mots de passe et annuaires (le jumelage en tient lieu) ; la collecte derrière une authentification interactive ; le contournement de protections anti-robots ; Windows et macOS côté serveur ; toute fonction propre à un domaine métier.

## 4. Glossaire

| Terme | Définition |
|---|---|
| **Collecteur** | greffon qui, pour des paramètres donnés, rend une suite d'éléments |
| **Élément** | une information collectée : clé stable, champs, empreinte, date de recueil, adresse d'origine facultative |
| **Abonnement** | un collecteur, ses paramètres, ses filtres, sa périodicité et sa langue, identifié par un `uid` aléatoire |
| **Collecte** | exécution d'un collecteur pour des paramètres donnés ; partagée entre les abonnements qui ont les mêmes |
| **Tour** | passage qui exécute les collectes dues, calcule les différences, produit et livre les rapports |
| **Rapport** | paquet numéroté d'un abonnement, scellé, contenant les éléments nouveaux, modifiés ou disparus et leurs rendus |
| **Jumelage** | lien entre le serveur et un outil de réception : un secret partagé et un identifiant `key_id`, révocable |
| **Code de jumelage** | texte d'une ligne que l'administrateur remet au membre, qui contient tout ce que l'outil de réception doit savoir |
| **Scellement** | chiffrement authentifié et signature d'un paquet |

## 5. Exigences fonctionnelles

### 5.1 Collecte
- **EF-01** Un collecteur est un greffon Python déclaré par un *entry point* du groupe `veilleur.collectors`. Il publie le **schéma** de ses paramètres et une fonction de collecte qui reçoit les paramètres validés, la date de la collecte précédente réussie et le client HTTP du serveur.
- **EF-02** Collecteurs fournis : `rss` (RSS 2.0 et Atom), `json_api` (adresse, chemin des éléments dans la réponse, champ servant de clé, pagination simple), `page` (contenu d'une page web, ou d'une partie désignée par un sélecteur CSS ; un changement du contenu normalisé est un élément modifié).
- **EF-03** Chaque élément a une **clé stable** fournie par le collecteur (identifiant de la source, sinon adresse, sinon empreinte du contenu) et une **empreinte** (SHA-256 du JSON canonique de ses champs) qui sert à détecter les modifications.
- **EF-04** Les collectes sont **mutualisées** : deux abonnements dont le collecteur et les paramètres canoniques sont identiques ne provoquent qu'une collecte par tour.
- **EF-05** Une source en panne n'arrête pas le tour. L'état de chaque collecte (dernière réussite, dernière erreur résumée sans détail interne) est conservé et figure dans les rapports et dans l'administration. Au-delà de deux jours de panne, la notification le signale.
- **EF-06** Un collecteur n'accède au réseau **que** par le client HTTP du serveur (§6, ES-08) : cache, délais, quotas par hôte, respect de `robots.txt`, identification honnête (`User-Agent: Veilleur/<version>` et adresse du serveur), mode hors ligne pour les tests.

### 5.2 Abonnements
- **EF-10** L'administrateur déclare des abonnements d'équipe dans un fichier de configuration (TOML) ou par une option du module NixOS, et les rattache à un ou plusieurs jumelages.
- **EF-11** Un outil de réception peut créer, modifier et supprimer ses propres abonnements par l'API (`PUT`/`DELETE`), avec des paramètres scellés. Il ne peut utiliser **que les collecteurs que l'administrateur autorise pour son jumelage** ; les collecteurs qui suivent une adresse donnée par le client (`rss`, `page`, `json_api`) sont refusés par défaut.
- **EF-12** Les paramètres d'un abonnement sont validés contre le schéma du collecteur à la réception ; une erreur est renvoyée avec un code stable et un message traduit.
- **EF-13** Un abonnement porte une **périodicité** de rapport (à chaque tour, quotidienne par défaut, hebdomadaire) et une **langue** (`fr` ou `en`) pour ses rendus.
- **EF-14** Un abonnement modifié porte un numéro de version ; une modification fondée sur une version dépassée est refusée (`409`).

### 5.3 Filtres
- **EF-20** Un filtre est un greffon (`veilleur.filters`) qui garde, écarte ou transforme des éléments. Fournis : mots-clés et expressions régulières (sur des champs désignés, insensibles à la casse et aux accents au choix), dédoublonnage entre collectes d'un même abonnement.
- **EF-21** Les filtres s'appliquent après la détection des changements et avant le rapport ; ils ne modifient jamais les éléments mémorisés.

### 5.4 Détection des changements
- **EF-30** Le serveur mémorise, pour chaque collecte, l'état courant des éléments (clé, empreinte, champs, première et dernière vue).
- **EF-31** D'un tour à l'autre, un élément est **nouveau** (clé inconnue), **modifié** (empreinte différente) ou **disparu** (absent d'une collecte complète réussie ; jamais après une collecte en échec ou partielle).
- **EF-32** Un abonnement neuf reçoit d'abord un rapport `state` (ce qui est en vigueur), puis des `delta`.

### 5.5 Rapports
- **EF-40** Pour chaque abonnement, le serveur produit une suite de **paquets numérotés** sans trou. Genres : `delta` (changements depuis le paquet précédent), `state` (tout ce qui est en vigueur), `history` (rattrapage depuis une date, préparé en tâche de fond).
- **EF-41** Un paquet contient : `manifest.json` (version du protocole, `uid` de l'abonnement, numéro, genre, période couverte, empreinte SHA-256 de chaque autre fichier, état des collectes), `manifest.sig`, `items.jsonl`, et les rendus demandés.
- **EF-42** `items.jsonl` : JSON Lines UTF-8, un élément par ligne, trié par clé : `{key, change: new|changed|gone, hash, fields, fetched_at, url}`. C'est la donnée qui **fait foi**.
- **EF-43** Rendus : greffons `veilleur.renderers` ; fournis `markdown` et `html` (gabarit simple, sans JavaScript ni ressource externe), dans la langue de l'abonnement. Facultatifs et dérivés.
- **EF-44** Un rapport vide (aucun changement) n'est pas produit.
- **EF-45** Les paquets sont gardés **90 jours**. Un paquet purgé répond `410` ; l'outil de réception demande alors un `state`.

### 5.6 Livraison et notification
- **EF-50** Livraison par **HTTPS** : l'outil de réception tire les paquets (§7.4) ; le serveur ne se connecte jamais à lui.
- **EF-51** Livraison **par dossier** : pour un membre sans accès réseau au serveur, l'administrateur extrait les paquets d'un abonnement dans un dossier ; un outil de réception les lit de la même façon. Les paquets étant scellés, leur transport ne demande aucune précaution.
- **EF-52** Notification après chaque tour qui a produit des rapports : greffons `veilleur.notifiers` ; fournis `ntfy` (sujet par jumelage, jeton d'accès) et `webhook` (POST JSON signé HMAC-SHA256 avec une clé propre). La notification ne contient **que des comptes** (nombre de rapports, d'éléments nouveaux, de sources en panne), jamais de contenu.

### 5.7 Jumelage
- **EF-60** L'administrateur crée un jumelage (`veilleur pairing new --label …`) ; le serveur tire un secret de 32 octets et un `key_id` aléatoire, et affiche un **code de jumelage** `VEIL1:<JSON en base64url>` contenant : version, adresse du serveur (ou `folder:`), `key_id`, secret, clé publique de signature du serveur, et, le cas échéant, adresse, sujet et jeton ntfy.
- **EF-61** Le code n'est montré qu'une fois ; le serveur ne garde que ce qui lui est nécessaire. Le libellé d'un jumelage est un repère (« poste 3 »), jamais un nom de personne.
- **EF-62** L'administrateur peut lister et **révoquer** un jumelage ; un jumelage révoqué reçoit `403` et ses abonnements cessent d'être servis.

### 5.8 Administration
- **EF-70** Ligne de commande `veilleur` : `info`, `config`, `pairing new|list|revoke`, `subscription list|show`, `collectors` (installés, autorisés par jumelage ; `allow|deny|default` pour régler l'autorisation d'EF-11), `round` (lancer un tour et en afficher le bilan), `sources` (état des collectes), `log`, `export` (livraison par dossier), `notify --test [--pairing …]`, `key rotate` (rotation de la clé du serveur, ES-05), `serve`, `version`.
- **EF-71** Le service HTTP (`veilleur serve`) et le tour périodique (minuterie systemd) tournent comme deux processus sur la même base.
- **EF-72** Les migrations de la base se font à l'ouverture, après une sauvegarde de la base.

### 5.9 Langues
- **EF-80** Tout ce qu'une personne lit existe en **français et en anglais** : messages de la ligne de commande et des journaux, messages d'erreur de l'API, rendus des rapports, documentation (`docs/fr/`, `docs/en/`, mêmes fichiers).
- **EF-81** Langue d'un processus : option `--lang`, puis `VEILLEUR_LANG`, puis la langue du système ; à défaut l'anglais. Langue d'un rapport : celle de l'abonnement.
- **EF-82** Les codes d'erreur de l'API et les identifiants des formats sont des identifiants anglais stables, jamais traduits.

## 6. Exigences de sécurité et de confidentialité

- **ES-01 Confidentialité** : *le serveur connaît ce qu'il collecte, jamais ce que les destinataires en font*. Il ne reçoit des outils de réception que des paramètres d'abonnement ; il ne stocke aucune donnée personnelle des membres. Les paramètres sont chiffrés en transit et lisibles par le serveur dans sa base ; la documentation le dit.
- **ES-02 Clés** : HKDF-SHA256 à partir du secret de jumelage, avec un sel par abonnement et une étiquette `info` par usage (paquets du serveur, paramètres envoyés par le client, authentification des requêtes) : une clé ne sert qu'à un usage et un abonnement. Seules les requêtes qui ne visent aucun abonnement (`GET /v1/collectors`, `GET /v1/subscriptions`) sont authentifiées par une clé propre au jumelage (sel vide).
- **ES-03 Enveloppe** : chiffrement authentifié **XChaCha20-Poly1305**, nonce aléatoire de 24 octets ; données associées = en-tête (magie, version) + `uid` + numéro + genre, de sorte qu'un paquet ne puisse être ni rejoué sous un autre numéro ni substitué à celui d'un autre abonnement. L'en-tête porte `uid`, numéro et genre en clair, pour qu'un paquet livré par dossier dise ce qu'il est. Le contenu chiffré est une archive zip non chiffrée ; noms et tailles des fichiers ne sont donc pas visibles.
- **ES-04 Signature** : Ed25519 pur (RFC 8032) sur les octets exacts de `manifest.json`, qui porte l'empreinte de chaque autre fichier. Vérifiée avant toute lecture des données.
- **ES-05 Rotation de la clé du serveur** : la clé sortante signe la clé entrante ; la déclaration est jointe à chaque paquet pendant 90 jours, ce qui évite de rejumeler les membres.
- **ES-06 Authentification des requêtes** : `Authorization: Veilleur <key_id>:<base64url(HMAC-SHA256(A, méthode ⏎ chemin et requête ⏎ horodatage ⏎ SHA-256 du corps))>` et `X-Veilleur-Date` (UTC, tolérance de 5 minutes). Toute requête est authentifiée.
- **ES-07 Lecteur de paquets** : avant toute lecture, il contrôle la taille du paquet, le nombre de fichiers (32 au plus), leurs noms (aucun chemin, aucun fichier non prévu par le genre), leurs tailles ; il n'écrit rien en clair sur le disque.
- **ES-08 SSRF** : le client HTTP refuse, **après résolution DNS** et à chaque redirection, les adresses de bouclage, privées, lien-local, CGNAT, multidiffusion et réservées (IPv4 et IPv6) ; il plafonne la taille des réponses, la durée des requêtes et le nombre de redirections, et vérifie les types de contenu attendus. Le pare-feu du conteneur (§8) est une seconde barrière, pas la seule.
- **ES-09 Journaux** : jamais de corps de requête, d'en-tête d'authentification, de secret, de paramètre d'abonnement ni d'adresse IP de membre (le mandataire TLS ne tient pas de journal d'accès ; le service ne voit que `127.0.0.1`).
- **ES-10 Secrets** : dans le dossier d'état du service (droits 700), jamais dans le *store* Nix, la configuration NixOS, les journaux ni le dépôt.
- **ES-11 Limites** : corps de requête de 1 Mo au plus (`413`), refusé par l'application même si le mandataire laisse passer.
- **ES-12 Pas de confidentialité persistante** : un secret de jumelage volé ouvre les paquets passés de ce jumelage. Assumé et documenté dans le modèle de menace.
- **ES-13 Livrables** : spécification du protocole (**normative en anglais**, traduction française informative), vecteurs de test, modèle de menace, `SECURITY.md` (signalement privé des failles par GitHub), tests à données aléatoires du lecteur de paquets.

## 7. Spécifications techniques

### 7.1 Architecture
- Python 3.12 ou plus récent, architecture **hexagonale** : `core/domain` (objets), `core/services` (règles), `core/ports` (interfaces), `adapters` (SQLite, client HTTP, collecteurs, filtres, rendus, notificateurs, scellement), `apps/server` (ligne de commande, service WSGI, fil de travail).
- Le cœur ne dépend ni du stockage, ni du réseau, ni de la traduction ; `lint-imports` le vérifie.
- Dépendances d'exécution minimales et sous licence compatible avec l'EUPL-1.2 ; cryptographie par `pycryptodomex` seulement.

### 7.2 Stockage
SQLite en mode WAL (deux processus : service et tour), migrations numérotées en SQL. Tables principales : `pairing`, `collector_grant`, `subscription`, `source_status` (une ligne par collecte mutualisée), `item`, `reported` (ce que chaque abonnement a rapporté en dernier), `package`, `job`, `event` (journal d'administration). Une seule connexion par processus, usage sérialisé par un verrou dans le service.

### 7.3 Bibliothèque de protocole
`veilleur-protocol`, paquet séparé dans le même dépôt (`protocol/`), sans dépendance au serveur : code de jumelage, signature des requêtes, scellement et ouverture des paquets, vérification de la rotation de clé. Accompagnée de **vecteurs de test** vérifiés par une seconde implémentation indépendante. Le détail (formats, ordre des contrôles du lecteur, codes d'erreur) est dans la spécification `docs/en/protocol.md` (normative, ES-13), qui suit ce cahier.

### 7.4 Interface HTTP `/v1`
Application WSGI à l'écoute de `127.0.0.1`, servie par un serveur WSGI à fils, derrière un mandataire TLS (Caddy).

| Requête | Réponse |
|---|---|
| `GET /v1/collectors` | collecteurs permis à ce jumelage, avec leurs schémas |
| `GET /v1/subscriptions` | abonnements vivants de ce jumelage : `{"subscriptions": [{"uid", "origin", "name", "version"}]}`, sans paramètres (`name` pour un abonnement d'équipe) |
| `PUT /v1/subscriptions/{uid}` | crée ou remplace un abonnement (corps scellé) ; `200 {"version"}`, `409` si version dépassée |
| `DELETE /v1/subscriptions/{uid}` | `204` |
| `GET /v1/subscriptions/{uid}/reports?after=N` | `200` JSON en clair, sans contenu : `{"packages": [{"seq", "size", "sha256"}], "oldest", "last"}` |
| `GET /v1/subscriptions/{uid}/reports/{n}` | `200` paquet ; `410` si purgé |
| `GET /v1/subscriptions/{uid}/state` | `200` paquet `state` |
| `GET /v1/subscriptions/{uid}/history?since=AAAA-MM-JJ` | `200` paquet, ou `202` + `Retry-After` pendant sa préparation |

Erreurs : corps `{"code", "message"}` sans détail interne ; `400`, `401` (authentification), `403` (jumelage révoqué ou collecteur non autorisé), `404`, `409`, `410`, `413`, `429`, `500`. En-tête `Cache-Control: no-store` sur toute réponse.

### 7.5 Tâches longues
Préparation d'un `history` et premier `state` d'un abonnement : réponse `202`, exécution par un fil de travail du service, reprise au démarrage des tâches restées en attente.

## 8. Exigences non fonctionnelles

- **ENF-01 Installation NixOS déclarative** par le flake du dépôt, qui expose `nixosModules.default` (service sur l'hôte, `services.veilleur`) et `nixosModules.container` (`services.veilleur-container` : conteneur `systemd-nspawn` à utilisateurs privés, réseau privé, accès sortant à Internet seulement, ni à l'hôte, ni aux réseaux privés, ni au réseau Tailscale (100.64/10), port 25 fermé, plafonds de mémoire (`memoryMax`) et de processus). Caddy (TLS Let's Encrypt, nom de domaine ou adresse IP), ntfy, minuterie du tour.
- **ENF-02 Code en lecture seule** : le code et son environnement Python (construit d'après `uv.lock` par uv2nix, avec le Python de nixpkgs) sont dans `/nix/store` ; rien n'est téléchargé au démarrage ; les greffons s'ajoutent par une option du module.
- **ENF-03 Version verrouillée** : la configuration de l'hôte charge Veilleur depuis `github:Cafeinoman/veilleur/<étiquette>`, en entrée de flake (verrouillée dans son `flake.lock`) ou par `builtins.getFlake` avec `narHash` ; une archive déposée à la main (`tarball+file://…?narHash=…`) reste possible pour un hôte sans accès à GitHub. La configuration de l'hôte doit **s'évaluer sur n'importe quelle machine**, sans fichier propre au serveur.
- **ENF-03b Intégration dans une configuration d'hôte existante** (serveur personnel qui porte d'autres services) :
  - les deux modules sont **inertes tant que `enable = false`** (`mkIf`) : l'hôte peut les importer sans condition ;
  - **frontal TLS au choix** : `proxy = "caddy"` (Veilleur prend 80/443, 8443 pour ntfy sans nom propre) ou `proxy = "external"` (Veilleur n'écoute que sur une adresse interne ; le guide donne le bloc Caddy et nginx à ajouter au frontal de l'hôte). Une **assertion** signale tout conflit de ports déclaré dans la configuration ;
  - **ntfy au choix** : intégré, externe (adresse et jeton d'un serveur ntfy déjà en place) ou aucun ;
  - **secrets fournis par l'hôte** en option (chemins de fichiers, compatibles sops-nix ou agenix) pour le jeton ntfy et la clé de webhook ; à défaut, générés dans le dossier d'état ;
  - **sauvegarde** : le module expose la liste des chemins à sauvegarder (`backupPaths`) et un service de copie cohérente de la base, à brancher sur la sauvegarde de l'hôte (restic, borg) ;
  - **adresse publique** (`publicHost`) inscrite dans les codes de jumelage : le guide conseille un nom (y compris un nom gratuit à mise à jour dynamique) plutôt qu'une IP ; en mode conteneur, la redirection de ports est en IPv4, donc **pas d'enregistrement AAAA** (Let's Encrypt et les clients IPv6 échoueraient) tant que l'IPv6 n'est pas relayée, ce que le guide et une assertion rappellent ;
  - un exemple de module d'hôte (`deploy/nixos/examples/host-module.nix`) montre cette intégration avec un fichier de réglages.
- **ENF-04 Durcissement systemd** complet (utilisateur dédié, aucune capacité, système en lecture seule, espaces de noms privés, filtrage des appels système et des familles d'adresses, `UMask=0077`).
- **ENF-05 Autres distributions Linux** : unités systemd, `Caddyfile` et extrait de configuration ntfy fournis ; code et environnement appartenant à root.
- **ENF-06 Test en VM NixOS** dans la CI (`nix flake check`) : installation, jumelage, tour sur une source locale, récupération d'un paquet ; un second test monte Veilleur en mode `proxy = "external"` derrière un Caddy d'hôte.
- **ENF-07 Charge** : une équipe, quelques centaines d'abonnements, un tour par jour par défaut ; 1 Go de mémoire suffit.
- **ENF-08 Sauvegarde** : le guide indique quoi sauvegarder (base, secrets, état ntfy) et comment (copie cohérente de la base).
- **ENF-09 Tests sans réseau** : réponses enregistrées, aucun port ouvert (l'application WSGI est appelée directement).

## 9. Contraintes de développement

- Licence **EUPL-1.2** ; première ligne de chaque fichier Python : `# SPDX-License-Identifier: EUPL-1.2`.
- Code, identifiants, commentaires et messages de commit en **anglais** ; textes destinés aux personnes traduits par gettext (§5.9).
- Contrôles obligatoires avant tout commit : `pytest`, `ruff`, `mypy` (strict), `lint-imports`.
- Dépôt public sur GitHub (`Cafeinoman/veilleur`) ; CI GitHub Actions ; actions fixées par empreinte de commit avant la première publication.
- **Une branche par fonctionnalité** (`claude/<sujet>`), poussée et proposée en *pull request* par Claude ; la fusion dans `main` est faite par l'utilisateur. Aucun envoi direct sur `main` après le premier commit.

## 10. Décisions

| Date | Décision |
|---|---|
| 2026-11-15 | Nom **Veilleur** (libre sur PyPI) ; licence **EUPL-1.2** ; **bilingue** français/anglais ; hébergement **GitHub** (`Cafeinoman/veilleur`) |
| 2026-11-15 | Une branche et une *pull request* par fonctionnalité, ouvertes par Claude, fusionnées par l'utilisateur ; Claude enchaîne les étapes du plan sans confirmation, sauf erreur bloquante ou arbitrage impératif |
| 2026-11-15 | Intégration NixOS dans une configuration d'hôte existante (ENF-03b) : modules inertes si désactivés, frontal TLS et ntfy au choix, secrets et sauvegarde fournis par l'hôte |
| 2026-11-15 | Textes sources en anglais, un seul catalogue gettext (français) ; ligne de commande sur `argparse`, dont les textes standard sont traduits |
| 2026-11-15 | Enveloppe XChaCha20-Poly1305 plutôt qu'un zip chiffré ; empreinte du corps dans la signature des requêtes ; rotation signée de la clé du serveur ; garde SSRF dans le client HTTP |
| 2026-11-17 | Protocole 1.0 (G1) : `key_id` de 8 octets et `uid` de 16 octets en hexadécimal ; en-tête d'enveloppe de 30 octets portant `uid`, numéro et genre en clair (données associées = en-tête entier) ; clé d'authentification propre au jumelage pour les requêtes hors abonnement ; un `state` ou `history` demandé porte le numéro du dernier paquet dont il tient compte ; corps de `PUT` scellé avec pour numéro la version de base (0 à la création) ; ordre des contrôles du lecteur et codes d'erreur fixés par la spécification ; JSON strict (ni membre en double, ni `NaN`) et archive zip restreinte (ni Zip64, ni descripteur de données, en-têtes locaux identiques au répertoire central), lue par la bibliothèque elle-même ; après une rotation adoptée, l'outil de réception ne fait plus confiance à l'ancienne clé |
| 2026-11-17 | Seconde implémentation des vecteurs écrite avec libsodium (PyNaCl, licence Apache-2.0), **dépendance de développement seulement** : la règle « cryptographie par `pycryptodomex` seulement » vaut pour les dépendances d'exécution |
| 2026-11-17 | Cœur (G2) : un abonnement appartient à **un** jumelage (ses clés dérivent du secret de jumelage) ; un abonnement d'équipe rattaché à N jumelages existe N fois, avec un `uid` tiré à sa création ; chaque jumelage a son propre espace d'`uid` (`404` pour l'abonnement d'un autre). Un `uid` supprimé reste en pierre tombale, sa version continue de croître et il n'est jamais réutilisé (`409 subscription_deleted`) : création et suppression rejouées sont sans effet. Chaque abonnement garde ce qu'il a rapporté en dernier ; un `delta` compare à cela les éléments courants filtrés (les changements s'accumulent jusqu'à l'échéance ; un élément qu'un filtre ne retient plus devient `gone`). Le premier `state` est produit dès la première collecte réussie, même sans élément. Un `state` ou `history` demandé est construit à partir de ce qui a été rapporté. Document d'abonnement, réponses et codes d'erreur de l'API fixés par la spécification du protocole (§9). Schémas des paramètres : sous-ensemble de JSON Schema validé sans dépendance. Un collecteur qui ne suit pas d'adresse du client est autorisé par défaut ; les autres sont refusés par défaut (EF-11). Limite de débit : 120 requêtes par minute et par jumelage. Langue des messages d'erreur de l'API : `Accept-Language`, sinon celle du serveur. Service HTTP sur le serveur WSGI de la bibliothèque standard (`wsgiref`, à fils), sans dépendance |
| 2026-11-18 | Réponses aux questions de G2 : ajout de `GET /v1/subscriptions` (abonnements vivants du jumelage, `uid`, origine, nom d'équipe, version, sans paramètres ; clé propre au jumelage), pour qu'un outil de réception découvre ses abonnements d'équipe ; compléments de G2 confirmés (`collectors allow|deny|default`, `key rotate`, `serve`, tables du §7.2) |
| 2026-11-18 | Client HTTP, collecteurs, filtres, notificateurs (G3) : la garde SSRF refuse un nom dont **une seule** adresse résolue est interne (y compris IPv4 enfouie dans IPv6 : *mapped*, NAT64, 6to4 ; Teredo refusé) et se connecte à l'adresse contrôlée, sans seconde résolution ; un `robots.txt` illisible (5xx) refuse la requête (RFC 9309), absent (4xx) autorise tout ; délai d'1 s et quota de 200 requêtes par hôte et par processus ; réponses de 5 Mo au plus (après décompression), 30 s, 5 redirections ; cache des requêtes conditionnelles dans `cache/http.db` du dossier d'état ; codes de panne stables (`address_refused`, `http_<statut>`…) ; mode hors ligne par `offline = true`. Un flux `rss` n'est jamais une collecte complète (une entrée sortie du flux n'est pas disparue). `page` : un élément par page, champ `content` (texte visible normalisé) et `title`, sous-ensemble de sélecteurs CSS sans dépendance. Lecture XML par expat, toute DTD refusée. Un greffon peut contrôler ses paramètres au-delà du schéma (`check_params`), à la réception ; le filtre `regex` exclut tout retour arrière catastrophique (voir décision suivante). `dedup` garde un élément par valeur de champs choisis parmi les éléments de la collecte (interprétation de « dédoublonnage entre collectes ») ; un filtre peut voir tous les éléments à la fois (`select`). Notifications **par jumelage**, sur un sujet aléatoire tiré au jumelage (migration 0002) et donné dans le code de jumelage, avec les comptes de ce jumelage seulement ; `ntfy` (adresse de publication, adresse publique https, jetons dans des fichiers) et `webhook` (corps JSON avec `sent_at`, en-tête `X-Veilleur-Signature: sha256=…`, clé dans un fichier ou générée dans `webhook.key`) ; les notificateurs, réglés par l'administrateur, ne passent pas par la garde SSRF et ne suivent pas les redirections ; un greffon notificateur installé est utilisé |
| 2026-11-18 | Filtre `regex` (G3, décision de l'utilisateur après deux passages du vérificateur) : moteur **RE2** (`google-re2`, licence BSD-3, dépendance d'exécution), dont la recherche est linéaire dans la taille du texte ; aucun motif ne peut bloquer le tour. Syntaxe RE2 : sans références arrière ni assertions avant/arrière (refusées à la réception) ; `\w`, `\d`, `\b` limités à l'ASCII (`\pL` pour toute lettre). L'analyse statique des motifs sous `re` est abandonnée, faute de garantie |
| 2026-11-18 | Rendus et récepteur de référence (G4) : `markdown` et `html` traitent toute valeur collectée comme hostile (caractères de contrôle et de direction retirés, échappement propre au format, lien pour les seules adresses `http(s)`, politique de sécurité du contenu dans la page) ; valeurs abrégées à 4 000 caractères et rendu plafonné à 2 millions de caractères d'éléments, `items.jsonl` gardant le tout ; un paquet trop gros avec ses rendus est scellé sans eux. Récepteur : paquet autonome `veilleur-receive` (`receiver/`), qui ne dépend que de `veilleur-protocol` et a son propre catalogue de traduction ; commandes `pair` (code lu au terminal ou sur l'entrée standard, jamais en argument) et `pull --folder <dossier> [--from <dossier exporté>]` ; dépôt dans `<dossier>/<uid>/<numéro>-<genre>/`, réservé à l'utilisateur ; état (secret, clés reconnues, derniers numéros) dans un fichier en 600, refusé s'il est lisible par d'autres. Un trou de numérotation n'est accepté que couvert par un `state`. Après l'adoption d'une clé, un paquet encore signé par l'ancienne est remplacé par un `state` demandé au serveur (protocole §6.3) |
