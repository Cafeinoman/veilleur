# Conception et feuille de route

*[English version](../en/design.md)*

Ce document décrit ce que sera Veilleur. Le squelette (jalon G0) et le protocole (G1 : [spécification](protocol.md), [modèle de menace](threat-model.md), bibliothèque `veilleur-protocol`) existent aujourd'hui (§9).

## 1. Objet

Veilleur :
1. **collecte** des informations depuis des sources branchables (flux RSS/Atom, API JSON, pages web, et toute source écrite comme greffon) ;
2. **repère** ce qui est nouveau, a changé ou a disparu d'un tour à l'autre ;
3. en fait des **rapports** (données structurées et rendu lisible) ;
4. les **livre**, signés et chiffrés, à des outils de réception (hors périmètre), par HTTPS ou par transfert de fichiers, avec une notification qui ne porte que des comptes ;
5. s'installe **de façon déclarative** sous NixOS (serveur dédié, conteneur isolé, ou à côté d'autres services sur un hôte existant), avec des unités systemd durcies, un mandataire TLS sans journal d'accès et une version verrouillée par son étiquette et son empreinte (§7).

## 2. Modèle

| Terme | Définition |
|---|---|
| **collecteur** | greffon qui, pour des paramètres donnés, rend des éléments |
| **abonnement** | un collecteur, ses paramètres, des filtres facultatifs, une périodicité de rapport et une langue, identifié par un `uid` aléatoire |
| **élément** | `{key, fields, hash, fetched_at, url?}` ; `key` est stable et fournie par le collecteur |
| **rapport** | paquet numéroté d'un abonnement : éléments nouveaux, modifiés et disparus, et rendus lisibles |
| **jumelage** | secret partagé entre le serveur et un outil de réception, avec un `key_id` ; révocable |

Un tour : `collecteurs → normalisation (clé, empreinte) → mémoire des éléments → différence (nouveau / modifié / disparu) → filtres → rapport par abonnement → scellement → livraison → notification`.

Les collectes sont **mutualisées** : deux abonnements qui demandent le même flux ne déclenchent qu'une requête (clé de collecte = collecteur + paramètres canoniques). Une source en panne n'arrête pas le tour : elle est signalée dans l'état des sources des rapports et dans l'administration, et la notification le mentionne au-delà de deux jours de panne. Un élément n'est **disparu** que s'il manque à une collecte complète et réussie, jamais après une collecte en échec ou partielle.

### 2.1 Points d'extension (greffons Python, *entry points*)

| Groupe | Interface (esquisse) | Fournis d'office |
|---|---|---|
| `veilleur.collectors` | `schema` (paramètres, validés à la réception) ; `collect(params, since, http) -> Iterable[Item]` | `rss` (RSS/Atom), `json_api` (URL + chemin dans la réponse + champ clé), `page` (changement d'une page, extrait par sélecteur CSS) |
| `veilleur.filters` | `keep(item, params) -> bool` ou `transform(item) -> Item` | mots-clés / expression régulière (sur des champs désignés, insensibles à la casse et aux accents au choix), dédoublonnage entre les collectes d'un même abonnement |
| `veilleur.renderers` | `render(report, language) -> dict[nom_de_fichier, bytes]` | `markdown`, `html` (gabarit simple, sans JavaScript) |
| `veilleur.notifiers` | `notify(target, counts)` | `ntfy`, `webhook` (corps signé HMAC) |

Les filtres s'appliquent après la détection des changements et avant le rapport ; ils ne modifient jamais les éléments mémorisés.

Un collecteur ne touche jamais au réseau directement : il reçoit le client HTTP du serveur (cache, quotas, `robots.txt`, garde anti-SSRF, mode hors ligne). Sous NixOS, les greffons s'ajoutent par une option du module et sont construits dans l'environnement en lecture seule ; rien n'est installé à chaud.

### 2.2 Qui crée les abonnements

- **L'administrateur**, de façon déclarative (fichier de configuration ou option du module NixOS) : veille d'équipe sur des sujets fixés.
- **Un outil de réception**, par `PUT /v1/subscriptions/{uid}` avec des paramètres scellés, **limité aux collecteurs que l'administrateur autorise pour son jumelage**. Les collecteurs qui suivent des adresses données par le client (`rss`, `page`, `json_api`) sont refusés par défaut et autorisés jumelage par jumelage.

Les paramètres sont validés contre le schéma du collecteur à la réception ; un abonnement modifié porte un numéro de version, et une modification fondée sur une version dépassée est refusée (`409`).

Principe de confidentialité : *le serveur connaît ce qu'il collecte, jamais ce que les destinataires en font*. Les paramètres d'un abonnement sont chiffrés en transit et lisibles par le serveur dans sa base (il doit les lire pour collecter) ; le guide d'administration le dit.

## 3. Rapports

Un paquet contient `manifest.json` (version du protocole, abonnement, numéro, genre, période, empreinte de chaque autre fichier, état des collectes), `manifest.sig`, `items.jsonl` (JSON Lines, un élément par ligne, trié par clé : `{key, change: new|changed|gone, hash, fields, fetched_at, url}`) et les rendus demandés (`report.md`, `report.html`) dans la langue de l'abonnement. Les rendus sont **facultatifs** et **dérivés** : `items.jsonl` fait foi.

Genres : `delta` (depuis le paquet précédent), `state` (tout ce qui est en vigueur, pour un récepteur revenu après la purge des paquets), `history` (rattrapage depuis une date, préparé en tâche de fond). Périodicité par abonnement (quotidienne par défaut, hebdomadaire, à chaque tour) ; un rapport vide n'est pas produit ; un abonnement neuf reçoit d'abord un `state`, puis des `delta`. Les paquets sont numérotés sans trou et gardés 90 jours ; un paquet purgé répond `410`, et le récepteur demande alors un `state`.

## 4. Sécurité

| Sujet | Conception |
|---|---|
| Jumelage | secret aléatoire de 32 octets par jumelage, `key_id` aléatoire, clé publique Ed25519 du serveur ; remis une fois par un code de jumelage `VEIL1:<JSON en base64url>` ; son libellé est un repère (« poste 3 »), jamais un nom de personne ; un jumelage révoqué reçoit `403` |
| Clés | HKDF-SHA256 à partir du secret de jumelage, sel par abonnement, une étiquette `info` par usage : un paquet ne peut pas passer pour celui d'un autre abonnement ; les requêtes qui ne nomment aucun abonnement utilisent une clé d'authentification propre au jumelage |
| Enveloppe | `en-tête (magie, version, uid, numéro, genre) ‖ nonce de 24 octets ‖ XChaCha20-Poly1305(zip en clair)` ; données associées = l'en-tête (ni rejeu, ni substitution) ; l'en-tête est en clair pour qu'un paquet dans un dossier dise ce qu'il est |
| Signature | Ed25519 pur (RFC 8032) sur les octets exacts de `manifest.json`, qui porte le SHA-256 de chaque autre fichier ; vérifiée à l'intérieur de l'enveloppe, avant toute lecture des données |
| Requêtes | `Authorization: Veilleur <key_id>:<HMAC-SHA256(méthode, chemin et requête, horodatage, SHA-256 du corps)>`, `X-Veilleur-Date`, tolérance de 5 minutes |
| Rotation de la clé du serveur | la clé sortante signe la clé entrante ; la déclaration voyage dans chaque paquet pendant 90 jours |
| SSRF | le client HTTP refuse les adresses de bouclage, privées, lien-local, CGNAT, de multidiffusion et réservées (IPv4 et IPv6) **après résolution DNS** et à chaque redirection, plafonne le nombre de redirections, refuse les réponses trop grosses ou trop lentes et les types de contenu inattendus ; le pare-feu du conteneur est une seconde barrière |
| Lecteur | contrôle la taille du paquet, le nombre de fichiers (32 au plus), leurs noms (aucun chemin, aucun fichier non prévu par le genre) et leurs tailles avant de lire la moindre donnée ; la bibliothèque n'écrit rien en clair sur le disque du récepteur |
| Journaux | ni corps de requête, ni en-tête d'authentification, ni secret, ni paramètre d'abonnement, ni IP de membre (le mandataire ne tient pas de journal d'accès ; le service ne voit que `127.0.0.1`) |
| Secrets | dans le dossier d'état du service (droits 700), jamais dans le *store* Nix, la configuration NixOS, les journaux ni le dépôt |
| Limites | corps de requête de 1 Mo au plus (`413`), refusé par l'application même si le mandataire le laisse passer |

Pas de confidentialité persistante : un secret de jumelage volé ouvre les paquets passés de ce jumelage. Le modèle de menace le documente.

Livrables de sécurité : spécification du protocole (**normative en anglais**, traduction française informative), **vecteurs de test**, modèle de menace, `SECURITY.md`, tests à données aléatoires (*fuzzing*) du lecteur de paquets.

## 5. Côté réception

L'outil de réception est hors périmètre. Veilleur fournit :
- `veilleur-protocol`, une bibliothèque autonome (code de jumelage, signature des requêtes, ouverture et vérification d'un paquet ; dépendance unique `pycryptodomex`) ;
- un **récepteur de référence** minimal (`veilleur-receive pull --folder …`) qui récupère, vérifie et dépose les rapports dans un dossier. Il sert aux tests de bout en bout et d'exemple.

## 6. Interface HTTP `/v1`

`PUT|DELETE /subscriptions/{uid}`, `GET /subscriptions/{uid}/reports?after=N`, `GET …/reports/{n}`, `GET …/state`, `GET …/history`, `GET /collectors` (collecteurs permis à ce jumelage, avec leurs schémas). Une application WSGI à l'écoute de `127.0.0.1` derrière le mandataire ; les tâches longues répondent `202` avec `Retry-After` et tournent dans un fil de travail. Toute requête est authentifiée. Corps d'erreur : `{"code", "message"}`, sans détail interne ; `code` est un identifiant anglais stable, `message` est traduit. Statuts : `400`, `401`, `403` (jumelage révoqué ou collecteur non autorisé), `404`, `409`, `410`, `413`, `429`, `500`. Toute réponse porte `Cache-Control: no-store`.

La ligne de commande d'administration `veilleur` offre `info`, `config`, `pairing new|list|revoke`, `subscription list|show`, `collectors`, `round`, `sources`, `log`, `export` (livraison par dossier), `notify --test` et `version`. Le service HTTP (`veilleur serve`) et le tour périodique (minuterie systemd) sont deux processus sur la même base SQLite (mode WAL, migrations SQL numérotées appliquées à l'ouverture après une sauvegarde).

## 7. Installation

### 7.1 NixOS

Le flake du dépôt expose `nixosModules.default` (service sur l'hôte, `services.veilleur`) et `nixosModules.container` (`services.veilleur-container` : conteneur `systemd-nspawn` à utilisateurs privés et réseau privé, accès sortant à Internet seulement — ni à l'hôte, ni aux réseaux privés, ni au réseau Tailscale (100.64/10) —, port 25 fermé, plafonds de mémoire (`memoryMax`) et de processus). Caddy (TLS Let's Encrypt, nom de domaine ou adresse IP), ntfy et la minuterie du tour l'accompagnent. Les unités sont entièrement durcies (utilisateur dédié, aucune capacité, système en lecture seule, espaces de noms privés, filtrage des appels système et des familles d'adresses, `UMask=0077`).

Le code et son environnement Python (construit d'après `uv.lock` par uv2nix, avec le Python de nixpkgs) sont dans `/nix/store` ; rien n'est téléchargé au démarrage ; les greffons s'ajoutent par une option du module.

**Version verrouillée** : la configuration de l'hôte charge Veilleur depuis `github:Cafeinoman/veilleur/<étiquette>`, en entrée de flake (verrouillée dans son `flake.lock`) ou par `builtins.getFlake` avec `narHash` ; une archive déposée à la main (`tarball+file://…?narHash=…`) reste possible pour un hôte sans accès à GitHub. La configuration de l'hôte doit **s'évaluer sur n'importe quelle machine**, sans fichier propre au serveur.

### 7.2 Intégration dans une configuration d'hôte existante

Pour un serveur personnel qui porte déjà d'autres services :
- les deux modules sont **inertes tant que `enable = false`** (`mkIf`) : l'hôte peut les importer sans condition ;
- **frontal TLS au choix** : `proxy = "caddy"` (Veilleur prend 80/443, et 8443 pour ntfy sans nom propre) ou `proxy = "external"` (Veilleur n'écoute que sur une adresse interne ; le guide donne le bloc Caddy et nginx à ajouter au frontal de l'hôte). Une **assertion** signale tout conflit de ports déclaré dans la configuration ;
- **ntfy au choix** : intégré, externe (adresse et jeton d'un serveur ntfy déjà en place) ou aucun ;
- **secrets fournis par l'hôte** au choix (chemins de fichiers, compatibles sops-nix ou agenix) pour le jeton ntfy et la clé de webhook ; à défaut, générés dans le dossier d'état ;
- **sauvegarde** : le module expose la liste des chemins à sauvegarder (`backupPaths`) et un service de copie cohérente de la base, à brancher sur la sauvegarde de l'hôte (restic, borg) ;
- **adresse publique** (`publicHost`), inscrite dans les codes de jumelage : le guide conseille un nom (y compris un nom gratuit à mise à jour dynamique) plutôt qu'une IP ; en mode conteneur, la redirection de ports est en IPv4, donc **pas d'enregistrement AAAA** (Let's Encrypt et les clients IPv6 échoueraient) tant que l'IPv6 n'est pas relayée, ce que le guide et une assertion rappellent ;
- un exemple de module d'hôte (`deploy/nixos/examples/host-module.nix`) montre cette intégration avec un fichier de réglages.

### 7.3 Autres distributions Linux

Unités systemd, `Caddyfile` et extrait de configuration ntfy fournis ; code et environnement appartiennent à root.

## 8. Arborescence du dépôt

```
src/veilleur/
  core/domain/          éléments, abonnements, rapports, jumelages (ni réseau, ni stockage)
  core/services/        collecte, différence, rapport, jumelage, tour, purge
  core/ports/           Collector, Filter, Renderer, Notifier, Store, Sealer, HttpClient
  adapters/             sqlite, client http, collecteurs, notificateurs, rendus
  apps/server/          ligne de commande, service WSGI, fil de travail
  i18n.py, locale/      traductions (gettext)
protocol/               paquet veilleur-protocol et vecteurs de test
receiver/               récepteur de référence
deploy/nixos/           module NixOS, conteneur, exemple de VPS, test en VM NixOS
deploy/systemd/         unités, exemples de mandataire et de ntfy pour les autres distributions
docs/en/, docs/fr/      documentation, mêmes fichiers dans les deux langues
```

Le cœur ne dépend ni du stockage, ni du réseau, ni de la traduction ; `lint-imports` le vérifie.

## 9. Jalons

| Jalon | Contenu | Fini quand |
|---|---|---|
| **G0** | Squelette, licence EUPL-1.2 et en-têtes SPDX, CI, `ruff`, `mypy`, `lint-imports`, gettext avec catalogue français et tests de complétude, documentation bilingue | squelette vert, un message traduit de bout en bout |
| G1 | Protocole 1.0 : spécification, `veilleur-protocol`, enveloppe AEAD, rotation de clé, vecteurs de test | vecteurs vérifiés par deux implémentations (bibliothèque + script indépendant) |
| G2 | Cœur : éléments, différence, abonnements, rapports, jumelages, tours ; SQLite ; ligne de commande d'administration ; service WSGI | un tour complet sur un collecteur factice, tests sans réseau |
| G3 | Client HTTP avec garde anti-SSRF ; collecteurs `rss`, `json_api`, `page` ; notificateurs `ntfy`, `webhook` | tests sur réponses enregistrées, tentatives SSRF refusées |
| G4 | Rendus `markdown` et `html` ; récepteur de référence | de bout en bout, serveur → récepteur |
| G5 | Déploiement : flake, module NixOS, conteneur, test en VM NixOS, repli systemd, livrable versionné ; guide d'administration | `nix flake check` et test en VM verts |
| G6 | Passe de publication : recherche de secrets, `SECURITY.md`, version 0.1.0 | publication |

## 10. Décisions

- **Nom** : Veilleur.
- **Licence** : EUPL-1.2.
- **Langues** : code, identifiants et commentaires en anglais ; messages, messages d'erreur de l'API, rapports et documentation en anglais et en français. Les textes sources sont en anglais ; le catalogue français les traduit (voir [translating.md](translating.md)).
- **Hébergement** : GitHub (`Cafeinoman/veilleur`). NixOS installe depuis `github:Cafeinoman/veilleur/<étiquette>` (§7.1).
- **Développement** : une branche par fonctionnalité (`claude/<sujet>`), poussée et proposée en *pull request* par Claude ; l'utilisateur fusionne dans `main`. Aucun envoi direct sur `main` après le premier commit. Contrôles obligatoires avant tout commit : `pytest`, `ruff`, `mypy` (strict), `lint-imports`. Actions GitHub fixées par empreinte de commit avant la première publication.
