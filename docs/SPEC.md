# Veilleur — spécification

> Document de référence du projet : il dit **ce que** Veilleur doit faire et **comment**, dans ses grandes lignes. Il
> prime sur toute autre documentation (`docs/en/design.md` et `docs/fr/design.md` en sont des présentations et le
> suivent). Toute évolution le met à jour d'abord. Les décisions sont dans `docs/adr/`, le travail dans
> `docs/PLAN.md`.
>
> Version 2, 2026-11-19 : reprise du `cahier_des_charges.MD` (version 1, 2026-11-15, état du commit `0be164e`) au
> format `/architecte`. Les identifiants EF-xx, ES-xx et ENF-xx sont **conservés** ; les numéros de section 1 à 9 aussi,
> pour que « cahier §7.4 » se lise « SPEC §7.4 ». La correspondance complète est dans `docs/REPRISE.md`.

**Priorités.** MUST : exigé ; SHOULD : attendu, peut glisser d'un jalon ; COULD : souhaitable, coupé en premier ;
WON'T : écarté pour la période, avec raison. **Livré** : présent dans la version 0.1.0 (étiquette `v0.1.0`), éventuellement
avec une réserve de `docs/PLAN.md` (notée R<nn>). Tout ce qui est livré est MUST.

## 1. Objet

Veilleur est un **serveur de veille auto-hébergé**, libre (EUPL-1.2), installable par une petite équipe sur un serveur
qu'elle contrôle. Il :
1. **collecte** des informations depuis des sources branchables : flux RSS/Atom, API JSON, pages web, et toute source
   écrite comme greffon ;
2. **repère** ce qui est nouveau, a changé ou a disparu d'un tour de collecte à l'autre ;
3. en fait des **rapports** : données structurées et rendu lisible ;
4. les **livre**, signés et chiffrés, à des **outils de réception**, par HTTPS ou par transfert de fichiers, avec une
   notification qui ne porte que des comptes.

L'outil de réception (ce qu'on fait des rapports : tri, archivage, rapprochement avec d'autres données, affichage) est
**hors périmètre**. Veilleur fournit seulement une bibliothèque de protocole et un récepteur de référence minimal pour
qu'on puisse en écrire un.

Veilleur est **générique** : il ne contient aucune connaissance d'un domaine métier particulier. Une source propre à un
domaine s'ajoute par un greffon, maintenu hors du dépôt.

## 2. Acteurs

| Acteur | Rôle |
|---|---|
| **Administrateur** | installe et met à jour le serveur, crée et révoque les jumelages, déclare les abonnements d'équipe, autorise les collecteurs par jumelage, règle la politique `robots.txt` et les limites par hôte, consulte l'état des sources et les alertes ; **choisit les sources et répond de leur usage** (CGU, opposition à la fouille) |
| **Membre** (et son outil de réception) | jumelé une fois avec le serveur ; reçoit les rapports des abonnements qui le concernent ; peut créer ses propres abonnements si l'administrateur l'y autorise |
| **Auteur de greffon** | écrit un collecteur, un filtre, un rendu ou un notificateur, distribué comme paquet Python ; s'appuie sur la surface publique de l'API des greffons (ADR-0028) |
| **Auteur d'outil de réception** | lit les rapports grâce à la spécification du protocole, à la bibliothèque `veilleur-protocol` ou à ses vecteurs de test |

Un serveur sert **une équipe** (une poignée à quelques dizaines de membres) et a **un administrateur**. Ce n'est pas un
service multi-locataire.

## 3. Périmètre

**Dans le périmètre** : collecte, détection des changements, filtres, rapports, scellement (chiffrement et signature),
livraison HTTPS et par dossier, notification, jumelage, administration en ligne de commande, installation NixOS et repli
pour les autres distributions Linux, traduction française et anglaise, bibliothèque de protocole, récepteur de référence.
Ajouts de 0.2.0 et 0.3.0 : requêtes POST à corps JSON, sessions éphémères sur pages publiques, limites par hôte,
`Crawl-delay`, avertissements de collecte, expiration des éléments (§11).

**Hors périmètre** (WON'T) : l'outil de réception complet ; une interface web d'administration ; les comptes
utilisateurs, mots de passe et annuaires (le jumelage en tient lieu) ; la collecte derrière une authentification
interactive (une session éphémère sur page publique n'en est pas une, ADR-0024) ; le contournement de protections
anti-robots (`401`, `403`, `429`, pages de défi restent des pannes, ADR-0022) ; l'exécution de JavaScript (surface
d'attaque disproportionnée pour un service durci) ; Windows et macOS côté serveur ; toute fonction propre à un domaine
métier ; la publication sur PyPI (ADR-0021).

## 4. Glossaire

| Terme | Définition |
|---|---|
| **Collecteur** | greffon qui, pour des paramètres donnés, rend une suite d'éléments |
| **Élément** | une information collectée : clé stable, champs, empreinte, date de recueil, adresse d'origine facultative, date d'expiration facultative (DV-06) |
| **Abonnement** | un collecteur, ses paramètres, ses filtres, sa périodicité et sa langue, identifié par un `uid` aléatoire |
| **Collecte** | exécution d'un collecteur pour des paramètres donnés ; partagée entre les abonnements qui ont les mêmes |
| **Tour** | passage qui exécute les collectes dues, calcule les différences, produit et livre les rapports |
| **Rapport** | paquet numéroté d'un abonnement, scellé, contenant les éléments nouveaux, modifiés ou disparus et leurs rendus |
| **Jumelage** | lien entre le serveur et un outil de réception : un secret partagé et un identifiant `key_id`, révocable |
| **Code de jumelage** | texte d'une ligne que l'administrateur remet au membre, qui contient tout ce que l'outil de réception doit savoir |
| **Scellement** | chiffrement authentifié et signature d'un paquet |
| **Avertissement** | code stable attaché à l'état d'une collecte, qui dit pourquoi elle est partielle ou ce qu'elle a fait de notable (DV-05, `robots_ignored`) |
| **Passage outre** | requête vers une adresse que le `robots.txt` de l'hôte interdit à l'agent `Veilleur`, faite en politique `warn` (EF-07) |
| **Session éphémère** | suite de requêtes d'une collecte vers un seul hôte, qui partage des cookies gardés en mémoire (DV-02) |

## 5. Exigences fonctionnelles

### 5.1 Collecte

- **EF-01** — MUST, livré. Un collecteur est un greffon Python déclaré par un *entry point* du groupe
  `veilleur.collectors`. Il publie le **schéma** de ses paramètres et une fonction de collecte qui reçoit les paramètres
  validés, la date de la collecte précédente réussie et le client HTTP du serveur. (ADR-0013, ADR-0028)
- **EF-02** — MUST, livré (R17). Collecteurs fournis : `rss` (RSS 2.0 et Atom), `json_api` (adresse, chemin des
  éléments dans la réponse, champ servant de clé, pagination simple), `page` (contenu d'une page web, ou d'une partie
  désignée par un sélecteur CSS ; un changement du contenu normalisé est un élément modifié). (ADR-0015)
- **EF-03** — MUST, livré. Chaque élément a une **clé stable** fournie par le collecteur (identifiant de la source,
  sinon adresse, sinon empreinte du contenu) et une **empreinte** (SHA-256 du JSON canonique de ses champs) qui sert à
  détecter les modifications.
- **EF-04** — MUST, livré (R18). Les collectes sont **mutualisées** : deux abonnements dont le collecteur et les
  paramètres canoniques sont identiques ne provoquent qu'une collecte par tour.
- **EF-05** — MUST, livré (R09). Une source en panne n'arrête pas le tour. L'état de chaque collecte (dernière
  réussite, dernière erreur résumée sans détail interne, avertissements) est conservé et figure dans les rapports et
  dans l'administration. Au-delà de deux jours de panne, la notification le signale. Un élément dont les champs
  s'imbriquent sur plus de **100 niveaux** (l'objet `fields` compte pour un) est écarté comme invalide (`bad_item`) et
  rend la collecte partielle, sans arrêter le tour (D19).
- **EF-06** — MUST ; **révisée le 2026-11-19** (ADR-0022, à livrer en J9). Un collecteur n'accède au réseau **que**
  par le client HTTP du serveur (§6, ES-08) : cache, délais, quotas par hôte (DV-03), lecture de `robots.txt` pour la
  politique de l'administrateur (EF-07) et pour `Crawl-delay` (DV-04), respect de `Retry-After` sur `429` et `503`,
  identification honnête (`User-Agent: Veilleur/<version>` et adresse du serveur), mode hors ligne pour les tests.
  *Version 0.1.0 (livrée)* : « respect de `robots.txt` » — refus `robots_disallowed`, et `robots_unavailable` si le
  fichier est illisible ; ce comportement devient la politique `enforce`.
- **EF-07** — MUST, nouvelle (ADR-0022, J9-L3). **Politique `robots.txt`.** Réglage `robots` = `"warn"` (défaut) ou
  `"enforce"`, pour l'instance (`[http]`) et par hôte (`[http.hosts."<hôte>"]`, qui prime).
  - `warn` : une adresse interdite est demandée et collectée. Au **premier** passage outre pour un couple (collecte
    mutualisée, hôte) et une empreinte donnée de `robots.txt`, le serveur ajoute un événement `robots_ignored` au
    journal d'administration, attache l'avertissement `robots_ignored` à l'état de la collecte (visible dans
    `veilleur sources`) et la notification suivante du jumelage concerné compte les sources en cause. Les passages
    suivants pour le même couple ne réalertent pas, sauf si `robots.txt` change (nouvelle empreinte).
  - L'alerte ne contient **jamais l'adresse demandée** ni ses paramètres (ES-09) : hôte, collecteur, identifiant de
    collecte et règle `Disallow` en cause seulement ; la notification ne porte que des comptes (EF-52).
  - `robots.txt` absent ou illisible ne bloque pas la collecte en `warn`.
  - `enforce` : refus `robots_disallowed` et `robots_unavailable`, comme en 0.1.0.
  - L'analyse suit RFC 9309 (règle la plus longue, groupe `Veilleur` sinon `*`).

### 5.2 Abonnements

- **EF-10** — MUST, livré (R11, R16). L'administrateur déclare des abonnements d'équipe dans un fichier de
  configuration (TOML) ou par une option du module NixOS, et les rattache à un ou plusieurs jumelages. (ADR-0010)
- **EF-11** — MUST, livré. Un outil de réception peut créer, modifier et supprimer ses propres abonnements par l'API
  (`PUT`/`DELETE`), avec des paramètres scellés. Il ne peut utiliser **que les collecteurs que l'administrateur autorise
  pour son jumelage** ; les collecteurs qui suivent une adresse donnée par le client (`rss`, `page`, `json_api`) sont
  refusés par défaut.
- **EF-12** — MUST, livré (R17). Les paramètres d'un abonnement sont validés contre le schéma du collecteur à la
  réception ; une erreur est renvoyée avec un code stable et un message traduit.
- **EF-13** — MUST, livré. Un abonnement porte une **périodicité** de rapport (à chaque tour, quotidienne par défaut,
  hebdomadaire) et une **langue** (`fr` ou `en`) pour ses rendus.
- **EF-14** — MUST, livré. Un abonnement modifié porte un numéro de version ; une modification fondée sur une version
  dépassée est refusée (`409`).

### 5.3 Filtres

- **EF-20** — MUST, livré (R13). Un filtre est un greffon (`veilleur.filters`) qui garde, écarte ou transforme des
  éléments. Fournis : mots-clés et expressions régulières (sur des champs désignés, insensibles à la casse et aux
  accents au choix ; moteur RE2, ADR-0016), dédoublonnage entre collectes d'un même abonnement (ADR-0015).
- **EF-21** — MUST, livré. Les filtres s'appliquent après la détection des changements et avant le rapport ; ils ne
  modifient jamais les éléments mémorisés.

### 5.4 Détection des changements

- **EF-30** — MUST, livré. Le serveur mémorise, pour chaque collecte, l'état courant des éléments (clé, empreinte,
  champs, première et dernière vue).
- **EF-31** — MUST, livré. D'un tour à l'autre, un élément est **nouveau** (clé inconnue), **modifié** (empreinte
  différente) ou **disparu** (absent d'une collecte complète réussie ; jamais après une collecte en échec ou partielle).
  Un élément **expiré** (DV-06) quitte l'état courant sans être disparu.
- **EF-32** — MUST, livré. Un abonnement neuf reçoit d'abord un rapport `state` (ce qui est en vigueur), puis des
  `delta`. (ADR-0011)

### 5.5 Rapports

- **EF-40** — MUST, livré. Pour chaque abonnement, le serveur produit une suite de **paquets numérotés** sans trou.
  Genres : `delta` (changements depuis le paquet précédent), `state` (tout ce qui est en vigueur), `history`
  (rattrapage depuis une date, préparé en tâche de fond).
- **EF-41** — MUST, livré. Un paquet contient : `manifest.json` (version du protocole, `uid` de l'abonnement, numéro,
  genre, période couverte, empreinte SHA-256 de chaque autre fichier, état des collectes), `manifest.sig`,
  `items.jsonl`, et les rendus demandés.
- **EF-42** — MUST, livré. `items.jsonl` : JSON Lines UTF-8, un élément par ligne, trié par clé :
  `{key, change: new|changed|gone, hash, fields, fetched_at, url}`. C'est la donnée qui **fait foi**.
- **EF-43** — MUST, livré (R19). Rendus : greffons `veilleur.renderers` ; fournis `markdown` et `html` (gabarit simple,
  sans JavaScript ni ressource externe), dans la langue de l'abonnement. Facultatifs et dérivés. (ADR-0018)
- **EF-44** — MUST, livré. Un rapport vide (aucun changement) n'est pas produit.
- **EF-45** — MUST, livré (R15). Les paquets sont gardés **90 jours**. Un paquet purgé répond `410` ; l'outil de
  réception demande alors un `state`.

### 5.6 Livraison et notification

- **EF-50** — MUST, livré. Livraison par **HTTPS** : l'outil de réception tire les paquets (§7.4) ; le serveur ne se
  connecte jamais à lui.
- **EF-51** — MUST, livré (R15). Livraison **par dossier** : pour un membre sans accès réseau au serveur,
  l'administrateur extrait les paquets d'un abonnement dans un dossier ; un outil de réception les lit de la même façon.
  Les paquets étant scellés, leur transport ne demande aucune précaution.
- **EF-52** — MUST, livré (R06). Notification après chaque tour qui a produit des rapports ou une alerte : greffons
  `veilleur.notifiers` ; fournis `ntfy` (sujet par jumelage, jeton d'accès) et `webhook` (POST JSON signé HMAC-SHA256
  avec une clé propre). La notification ne contient **que des comptes** (nombre de rapports, d'éléments nouveaux, de
  sources en panne, de sources qui passent outre `robots.txt` pour la première fois), jamais de contenu. (ADR-0017)

### 5.7 Jumelage

- **EF-60** — MUST, livré. L'administrateur crée un jumelage (`veilleur pairing new --label …`) ; le serveur
  tire un secret de 32 octets et un `key_id` aléatoire, et affiche un **code de jumelage** `VEIL1:<JSON en base64url>`
  contenant : version, adresse du serveur (ou `folder:`), `key_id`, secret, clé publique de signature du serveur, et, le
  cas échéant, adresse, sujet et jeton ntfy.
- **EF-61** — MUST, livré. Le code n'est montré qu'une fois ; le serveur ne garde que ce qui lui est nécessaire. Le
  libellé d'un jumelage est un repère (« poste 3 »), jamais un nom de personne.
- **EF-62** — MUST, livré. L'administrateur peut lister et **révoquer** un jumelage ; un jumelage révoqué reçoit `403`
  et ses abonnements cessent d'être servis.

### 5.8 Administration

- **EF-70** — MUST, livré (R21). Ligne de commande `veilleur` : `info`, `config`, `pairing new|list|revoke`,
  `subscription list|show`, `collectors` (installés, autorisés par jumelage ; `allow|deny|default` pour régler
  l'autorisation d'EF-11), `round` (lancer un tour et en afficher le bilan), `sources` (état des collectes, avec leurs
  avertissements), `log`, `export` (livraison par dossier), `notify --test [--pairing …]`, `key rotate` (rotation de la
  clé du serveur, ES-05), `serve`, `version`.
- **EF-71** — MUST, livré. Le service HTTP (`veilleur serve`) et le tour périodique (minuterie systemd) tournent comme
  deux processus sur la même base.
- **EF-72** — MUST, livré. Les migrations de la base se font à l'ouverture, après une sauvegarde de la base.

### 5.9 Langues

- **EF-80** — MUST, livré (R21). Tout ce qu'une personne lit existe en **français et en anglais** : messages de la
  ligne de commande et des journaux, messages d'erreur de l'API, rendus des rapports, documentation (`docs/fr/`,
  `docs/en/`, mêmes fichiers). (ADR-0005)
- **EF-81** — MUST, livré. Langue d'un processus : option `--lang`, puis `VEILLEUR_LANG`, puis la langue du système ; à
  défaut l'anglais. Langue d'un rapport : celle de l'abonnement.
- **EF-82** — MUST, livré. Les codes d'erreur de l'API, les codes d'avertissement et les identifiants des formats sont
  des identifiants anglais stables, jamais traduits.

## 6. Exigences de sécurité et de confidentialité

- **ES-01 Confidentialité** — MUST, livré : *le serveur connaît ce qu'il collecte, jamais ce que les destinataires en
  font*. Il ne reçoit des outils de réception que des paramètres d'abonnement ; il ne stocke aucune donnée personnelle
  des membres. Les paramètres sont chiffrés en transit et lisibles par le serveur dans sa base ; la documentation le
  dit.
- **ES-02 Clés** — MUST, livré : HKDF-SHA256 à partir du secret de jumelage, avec un sel par abonnement et une
  étiquette `info` par usage (paquets du serveur, paramètres envoyés par le client, authentification des requêtes) :
  une clé ne sert qu'à un usage et un abonnement. Seules les requêtes qui ne visent aucun abonnement
  (`GET /v1/collectors`, `GET /v1/subscriptions`) sont authentifiées par une clé propre au jumelage (sel vide).
- **ES-03 Enveloppe** — MUST, livré : chiffrement authentifié **XChaCha20-Poly1305**, nonce aléatoire de 24 octets ;
  données associées = en-tête (magie, version) + `uid` + numéro + genre, de sorte qu'un paquet ne puisse être ni rejoué
  sous un autre numéro ni substitué à celui d'un autre abonnement. L'en-tête porte `uid`, numéro et genre en clair,
  pour qu'un paquet livré par dossier dise ce qu'il est. Le contenu chiffré est une archive zip non chiffrée ; noms et
  tailles des fichiers ne sont donc pas visibles. (ADR-0007, ADR-0008)
- **ES-04 Signature** — MUST, livré (R01) : Ed25519 pur (RFC 8032) sur les octets exacts de `manifest.json`, qui porte
  l'empreinte de chaque autre fichier. Vérifiée avant toute lecture des données.
- **ES-05 Rotation de la clé du serveur** — MUST, livré (R12, R15) : la clé sortante signe la clé entrante ; la
  déclaration est jointe à chaque paquet pendant 90 jours, ce qui évite de rejumeler les membres. Limite admise : un
  membre à qui il manque un paquet purgé et qui a manqué deux rotations ou plus doit être rejumelé (ADR-0019).
- **ES-06 Authentification des requêtes** — MUST, livré (R04) :
  `Authorization: Veilleur <key_id>:<base64url(HMAC-SHA256(A, méthode ⏎ chemin et requête ⏎ horodatage ⏎ SHA-256 du corps))>`
  et `X-Veilleur-Date` (UTC, tolérance de 5 minutes). Toute requête est authentifiée.
- **ES-07 Lecteur de paquets** — MUST, livré : avant toute lecture, il contrôle la taille du paquet, le nombre de
  fichiers (32 au plus), leurs noms (aucun chemin, aucun fichier non prévu par le genre), leurs tailles ; il n'écrit
  rien en clair sur le disque.
- **ES-08 SSRF** — MUST, livré (R05) : le client HTTP refuse, **après résolution DNS** et à chaque redirection, les
  adresses de bouclage, privées, lien-local, CGNAT, multidiffusion et réservées (IPv4 et IPv6) ; il plafonne la taille
  des réponses, la durée des requêtes et le nombre de redirections, et vérifie les types de contenu attendus. Le
  pare-feu du conteneur (§8) est une seconde barrière, pas la seule. S'applique aussi à `post_json` et aux sessions
  (DV-01, DV-02). (ADR-0014)
- **ES-09 Journaux** — MUST, livré : jamais de corps de requête, d'en-tête d'authentification, de secret, de paramètre
  d'abonnement ni d'adresse IP de membre (le mandataire TLS ne tient pas de journal d'accès ; le service ne voit que
  `127.0.0.1`). Ajouts : ni adresse collectée dans une alerte `robots.txt`, ni corps de POST, ni cookie, ni valeur de
  formulaire.
- **ES-10 Secrets** — MUST, livré (R07, R08) : dans le dossier d'état du service (droits 700), jamais dans le *store*
  Nix, la configuration NixOS, les journaux ni le dépôt.
- **ES-11 Limites** — MUST, livré (R04, R13) : corps de requête de 1 Mo au plus (`413`), refusé par l'application même si
  le mandataire laisse passer.
- **ES-12 Pas de confidentialité persistante** — MUST, livré : un secret de jumelage volé ouvre les paquets passés de
  ce jumelage. Assumé et documenté dans le modèle de menace.
- **ES-13 Livrables** — MUST, livré (R22) : spécification du protocole (**normative en anglais**, traduction française
  informative), vecteurs de test, modèle de menace, `SECURITY.md` (signalement privé des failles par GitHub), tests à
  données aléatoires du lecteur de paquets.

## 7. Spécifications techniques

### 7.1 Architecture

- Python 3.12 ou plus récent, architecture **hexagonale** : `core/domain` (objets), `core/services` (règles),
  `core/ports` (interfaces), `adapters` (SQLite, client HTTP, collecteurs, filtres, rendus, notificateurs, scellement),
  `apps/server` (ligne de commande, service WSGI, fil de travail). (ADR-0003)
- Le cœur ne dépend ni du stockage, ni du réseau, ni de la traduction ; `lint-imports` le vérifie.
- Dépendances d'exécution minimales et sous licence compatible avec l'EUPL-1.2 ; cryptographie par `pycryptodomex`
  seulement (règle d'exécution ; une bibliothèque peut servir d'oracle de test en développement, ADR-0009).
- **Surface publique de l'API des greffons** (ADR-0028) : groupes d'*entry points* `veilleur.collectors`,
  `veilleur.filters`, `veilleur.renderers`, `veilleur.notifiers` ; modules `veilleur.core.ports.plugins`,
  `veilleur.core.ports.http`, `veilleur.core.domain.model`, `veilleur.core.domain.errors`,
  `veilleur.core.domain.schema`. Seuls des ajouts compatibles en 0.x ; un test fige la surface.
- Le cœur parle au client HTTP du serveur par un port serveur (portée de collecte) distinct du port `HttpClient` vu
  par les greffons (ADR-0027).

### 7.2 Stockage

SQLite en mode WAL (deux processus : service et tour), migrations numérotées en SQL. Tables principales : `pairing`,
`collector_grant`, `subscription`, `source_status` (une ligne par collecte mutualisée, avec ses avertissements à partir
de 0.2.0), `item` (avec sa date d'expiration à partir de 0.3.0), `reported` (ce que chaque abonnement a rapporté en
dernier), `package`, `job`, `event` (journal d'administration), et une table des alertes `robots.txt` déjà émises
(0.2.0). Une seule connexion par processus, usage sérialisé par un verrou dans le service. (ADR-0004)

### 7.3 Bibliothèque de protocole

`veilleur-protocol`, paquet séparé dans le même dépôt (`protocol/`), sans dépendance au serveur : code de jumelage,
signature des requêtes, scellement et ouverture des paquets, vérification de la rotation de clé. Accompagnée de
**vecteurs de test** vérifiés par une seconde implémentation indépendante. Le détail (formats, ordre des contrôles du
lecteur, codes d'erreur) est dans la spécification `docs/en/protocol.md` (normative, ES-13), qui suit ce document. Le
protocole reste en version 1.0 pour 0.2.0 et 0.3.0 (ADR-0008, ADR-0027). (ADR-0008, ADR-0009)

### 7.4 Interface HTTP `/v1`

Application WSGI à l'écoute de `127.0.0.1`, servie par un serveur WSGI à fils, derrière un mandataire TLS (Caddy).
(ADR-0012)

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

Erreurs : corps `{"code", "message"}` sans détail interne ; `400`, `401` (authentification), `403` (jumelage révoqué ou
collecteur non autorisé), `404`, `409`, `410`, `413`, `429`, `500`. En-tête `Cache-Control: no-store` sur toute
réponse.

### 7.5 Tâches longues

Préparation d'un `history` et premier `state` d'un abonnement : réponse `202`, exécution par un fil de travail du
service, reprise au démarrage des tâches restées en attente. Le quota par hôte est remis à zéro au début de chaque
tâche qui collecte (ADR-0025). Nombre de tâches en attente plafonné (R13).

### 7.6 Client HTTP sortant (ajout de la reprise)

Résumé de l'ADR-0014, révisé par les ADR-0022 à ADR-0026 :

| Réglage | Valeur | Réglable |
|---|---|---|
| Taille de réponse (après décompression) | 5 Mo | non |
| Durée d'une requête, redirections comprises, **hors attente imposée** | 30 s | non |
| Redirections (GET) | 5 | non |
| Redirections (POST) | `307`/`308` une fois, même hôte ; `301`/`302`/`303` refusées | non |
| Corps d'un POST | 1 Mo | non |
| Intervalle par hôte | 1 s par défaut, **1 s au moins** | `[http]`, `[http.hosts."<hôte>"]` |
| Quota par hôte et par tour | 200 par défaut, **10 000 au plus** | idem |
| `Crawl-delay` | appliqué si plus long que l'intervalle ; **60 s au plus**, sinon `crawl_delay_too_long` | non |
| Politique `robots.txt` | `warn` par défaut | `robots = "warn" \| "enforce"` |
| Lecture de `robots.txt` | une fois par jour et par origine ; illisible : nouvel essai après 1 h | non |
| Session éphémère | un hôte, 100 requêtes, 50 cookies de 4 Kio | non |

## 8. Exigences non fonctionnelles

- **ENF-01 Installation NixOS déclarative** — MUST, livré (R20, R23) : par le flake du dépôt, qui expose
  `nixosModules.default` (service sur l'hôte, `services.veilleur`) et `nixosModules.container`
  (`services.veilleur-container` : conteneur `systemd-nspawn` à utilisateurs privés, réseau privé, accès sortant à
  Internet seulement, ni à l'hôte, ni aux réseaux privés, ni au réseau Tailscale (100.64/10), port 25 fermé, plafonds
  de mémoire (`memoryMax`) et de processus). Caddy (TLS Let's Encrypt, nom de domaine ou adresse IP), ntfy, minuterie du
  tour. (ADR-0006, ADR-0020)
- **ENF-02 Code en lecture seule** — MUST, livré : le code et son environnement Python (construit d'après `uv.lock` par
  uv2nix, avec le Python de nixpkgs) sont dans `/nix/store` ; rien n'est téléchargé au démarrage ; les greffons
  s'ajoutent par une option du module.
- **ENF-03 Version verrouillée** — MUST, livré (R20) : la configuration de l'hôte charge Veilleur depuis `github:Cafeinoman/veilleur/<étiquette>`, en entrée de flake (verrouillée dans son `flake.lock`) ou par `builtins.getFlake` avec `narHash` ; une archive déposée à la main (`tarball+file://…?narHash=…`) reste possible pour un hôte sans accès à GitHub. La configuration de l'hôte doit **s'évaluer sur n'importe quelle machine**, sans fichier propre au serveur.
- **ENF-03b Intégration dans une configuration d'hôte existante** — MUST, livré (R20) (serveur personnel qui porte d'autres services) :
  - les deux modules sont **inertes tant que `enable = false`** (`mkIf`) : l'hôte peut les importer sans condition ;
  - **frontal TLS au choix** : `proxy = "caddy"` (Veilleur prend 80/443, 8443 pour ntfy sans nom propre) ou `proxy = "external"` (Veilleur n'écoute que sur une adresse interne ; le guide donne le bloc Caddy et nginx à ajouter au frontal de l'hôte). Une **assertion** signale tout conflit de ports déclaré dans la configuration ;
  - **ntfy au choix** : intégré, externe (adresse et jeton d'un serveur ntfy déjà en place) ou aucun ;
  - **secrets fournis par l'hôte** en option (chemins de fichiers, compatibles sops-nix ou agenix) pour le jeton ntfy et la clé de webhook ; à défaut, générés dans le dossier d'état ;
  - **sauvegarde** : le module expose la liste des chemins à sauvegarder (`backupPaths`) et un service de copie cohérente de la base, à brancher sur la sauvegarde de l'hôte (restic, borg) ;
  - **adresse publique** (`publicHost`) inscrite dans les codes de jumelage : le guide conseille un nom (y compris un nom gratuit à mise à jour dynamique) plutôt qu'une IP ; en mode conteneur, la redirection de ports est en IPv4, donc **pas d'enregistrement AAAA** (Let's Encrypt et les clients IPv6 échoueraient) tant que l'IPv6 n'est pas relayée, ce que le guide et une assertion rappellent ;
  - un exemple de module d'hôte (`deploy/nixos/examples/host-module.nix`) montre cette intégration avec un fichier de réglages.
- **ENF-04 Durcissement systemd** — MUST, livré (R07) : complet (utilisateur dédié, aucune capacité, système en lecture
  seule, espaces de noms privés, filtrage des appels système et des familles d'adresses, `UMask=0077`).
- **ENF-05 Autres distributions Linux** — MUST, livré : unités systemd, `Caddyfile` et extrait de configuration ntfy
  fournis ; code et environnement appartenant à root.
- **ENF-06 Test en VM NixOS** — MUST, livré : dans la CI (`nix flake check`) : installation, jumelage, tour sur une
  source locale, récupération d'un paquet ; un second test monte Veilleur en mode `proxy = "external"` derrière un Caddy
  d'hôte ; s'y ajoutent le conteneur (avec et sans `nftables`) et les unités de repli (ADR-0020).
- **ENF-07 Charge** — MUST, livré **non vérifié** (R23) : une équipe, quelques centaines d'abonnements, un tour par jour
  par défaut ; 1 Go de mémoire suffit.
- **ENF-08 Sauvegarde** — MUST, livré : le guide indique quoi sauvegarder (base, secrets, état ntfy) et comment (copie
  cohérente de la base).
- **ENF-09 Tests sans réseau** — MUST, livré : réponses enregistrées, aucun port ouvert (l'application WSGI est appelée
  directement).

Le déploiement est résumé dans `docs/DEPLOIEMENT.md`.

## 9. Contraintes de développement

- Licence **EUPL-1.2** ; première ligne de chaque fichier Python : `# SPDX-License-Identifier: EUPL-1.2`.
- Code, identifiants, commentaires et messages de commit en **anglais** ; textes destinés aux personnes traduits par gettext (§5.9).
- Contrôles obligatoires avant tout commit : `pytest`, `ruff`, `mypy` (strict), `lint-imports`.
- Dépôt public sur GitHub (`Cafeinoman/veilleur`) ; CI GitHub Actions ; actions fixées par empreinte de commit avant la première publication.
- **Une branche par fonctionnalité** (`claude/<sujet>`), poussée et proposée en *pull request* par Claude ; la fusion dans `main` est faite par l'utilisateur. Aucun envoi direct sur `main` après le premier commit.

Précisions de la reprise (ADR-0002, ADR-0029) : un lot de docs/PLAN.md porte un identifiant J-n-L-m et sa branche
reprend cet identifiant ; un lot par session, clos par le vérificateur indépendant ; les contrôles se lancent par la
commande unique du justfile, que la CI lance aussi ; documents de pilotage en français.

## 10. Décisions

Les décisions datées de l'ancien §10 sont des ADR (`docs/adr/`). Index :

| Date d'origine | Décision | ADR |
|---|---|---|
| 2026-11-15 | Nom, licence, bilinguisme, hébergement | 0001 |
| 2026-11-15, 2026-11-19 | Branche et PR par lot ; fin de l'enchaînement sans confirmation | 0002 |
| 2026-11-15 | Architecture hexagonale, trois paquets, dépendances minimales | 0003 |
| 2026-11-15 | Stockage SQLite | 0004 |
| 2026-11-15 | Textes sources en anglais, catalogue gettext, `argparse` | 0005 |
| 2026-11-15 | Intégration NixOS dans un hôte existant | 0006 |
| 2026-11-15 | Enveloppe XChaCha20-Poly1305, requêtes signées, rotation, garde SSRF | 0007 |
| 2026-11-17 | Protocole 1.0 | 0008 |
| 2026-11-17 | Seconde implémentation avec libsodium | 0009 |
| 2026-11-17 | Modèle des abonnements et des jumelages | 0010 |
| 2026-11-17 | Production des rapports | 0011 |
| 2026-11-17, 2026-11-18 | Service HTTP `/v1`, `GET /v1/subscriptions` | 0012 |
| 2026-11-17, 2026-11-18 | API des greffons | 0013 |
| 2026-11-18 | Client HTTP sortant (révisé par 0022) | 0014 |
| 2026-11-18 | Collecteurs et filtres fournis | 0015 |
| 2026-11-18 | Filtre `regex` sur RE2 | 0016 |
| 2026-11-18 | Notifications par jumelage | 0017 |
| 2026-11-18 | Rendus | 0018 |
| 2026-11-18 | Récepteur de référence et rotations | 0019 |
| 2026-11-18 | Déploiement NixOS | 0020 |
| 2026-11-18 | Publication, pas de PyPI | 0021 |
| 2026-11-19 (proposées) | `robots.txt` ; POST JSON ; sessions ; limites par hôte ; `Crawl-delay` ; avertissements et expiration ; API des greffons et versions ; mise au standard | 0022 à 0029 |

## 11. Évolutions demandées (DV-01 à DV-06)

Demandes du greffon `veilleur-marches`, reprises sous leurs identifiants, dans leur ordre de priorité, rédigées de
façon générique. Les critères d'acceptation sont ceux de la demande, révisés là où la reprise l'impose (en gras).

### DV-01. Requêtes POST à corps JSON — MUST (0.2.0, demande ferme)

- **Besoin.** Certaines API publiques de recherche n'acceptent que le POST, la requête étant trop riche pour une
  adresse.
- **Forme.** `http.post_json(url, body, accept=...)`, à côté de `get` (ADR-0023).
- **Sécurité.** Mêmes contrôles que `get` (garde SSRF à chaque résolution et redirection, quota, délai, plafonds) ;
  **politique `robots.txt` de l'administrateur (EF-07)** ; corps de 1 Mo au plus, sérialisé par le client, sans en-tête
  du greffon ; `301`, `302`, `303` refusées ; `307` et `308` suivies une fois au plus vers le même hôte ; pas de cache
  conditionnel ; corps jamais journalisé ; hors ligne : `network_unavailable`.
- **Critères d'acceptation.**
  1. Un POST vers un service de test envoie le corps JSON attendu, avec `Content-Type: application/json`.
  2. Une cible résolue vers une adresse privée est refusée avec `address_refused`.
  3. Une redirection `302` est refusée sans nouvelle requête.
  4. Un corps de plus de 1 Mo est refusé avant toute connexion.
  5. **Un chemin interdit par `robots.txt` est demandé et collecté en `warn`, avec une alerte (EF-07) ; il est refusé
     avec `robots_disallowed` en `enforce`.**
  6. Le POST compte dans le quota de l'hôte.
  7. Aucune trace du corps dans les journaux capturés pendant les tests.

### DV-02. Formulaires et cookies de session — SHOULD (0.3.0, indispensable au greffon hors de sa V1)

- **Besoin.** Des sites publics, consultables sans compte, ne servent une liste complète ou paginée qu'à travers un
  formulaire et un cookie de session.
- **Forme.** Session éphémère, limitée à une collecte et à un seul hôte (ADR-0024) : `session = http.session()`,
  `page = session.get(url)`, puis soumission d'un formulaire lu dans une page de la session : `session.form(page)` puis
  `session.submit(form, changes)`, sans `post_form` libre (D9).
- **Sécurité.** Cookies en mémoire, propres à une session, jamais écrits sur disque ni envoyés à un autre hôte ; aucun
  champ de mot de passe ; aucune authentification ; mêmes contrôles que `get` (**politique `robots.txt` de
  l'administrateur**) ; ni cookie ni valeur de formulaire dans les journaux ; requêtes par session plafonnées.
- **Hors périmètre maintenu** : la collecte derrière une authentification interactive (ADR-0024).
- **Critères d'acceptation.**
  1. Un cookie reçu est renvoyé aux requêtes suivantes de la session, sur le même hôte.
  2. Une redirection vers un autre hôte ne transmet pas le cookie.
  3. Deux sessions ne partagent aucun cookie.
  4. Un formulaire contenant un champ `password` est refusé.
  5. **Un chemin interdit par `robots.txt`, en GET comme en POST, est demandé avec alerte en `warn` et refusé avec
     `robots_disallowed` en `enforce`.**
  6. Aucun cookie ni valeur de formulaire dans les journaux capturés.
  7. La session se ferme à la fin de la collecte, même après une exception.

### DV-03. Limites réglables par hôte — SHOULD (0.2.0), avec la réserve R26

- **Besoin.** Le quota de 200 requêtes par hôte est fixé dans le code ; un hôte qui publie un fichier par entrée ne peut
  pas être lu en un tour.
- **Forme.** Section `[http.hosts."<hôte>"]` (`quota`, `interval`, `robots`) du fichier de configuration (ADR-0025).
- **Sécurité.** Réglage réservé à l'administrateur ; intervalle minimal de 1 s ; quota maximal de 10 000 ; aucun effet
  sur la garde SSRF ni sur la politique `robots.txt` d'un autre hôte.
- **Réserve fusionnée (R26)** : le quota est remis à zéro à chaque tour et à chaque tâche de `serve`.
- **Critères d'acceptation.**
  1. Sans réglage, le comportement actuel est inchangé (200 requêtes, 1 s).
  2. Un hôte réglé à 1 000 accepte 1 000 requêtes, et refuse la suivante avec `host_quota_exceeded`.
  3. Un intervalle inférieur au minimum est refusé au chargement de la configuration.
  4. Un quota supérieur au maximum est refusé au chargement de la configuration.
  5. Le réglage d'un hôte n'a aucun effet sur un autre hôte.
  6. **Dans un même processus `serve`, deux tâches successives disposent chacune du quota entier.**

### DV-04. Respect de `Crawl-delay` — MUST (0.2.0, indispensable au greffon hors de sa V1)

- **Besoin.** Un site peut demander un délai entre deux requêtes par `Crawl-delay` ; le client l'ignore.
- **Forme.** Délai appliqué = maximum entre l'intervalle de l'hôte et `Crawl-delay` (ADR-0026), **quelle que soit la
  politique `robots.txt`**.
- **Sécurité.** Délai plafonné à 60 s ; au-delà, code stable `crawl_delay_too_long` ; la limite de 30 s par requête ne
  compte pas l'attente.
- **Critères d'acceptation.**
  1. Avec `Crawl-delay: 15`, deux requêtes successives sont espacées d'au moins 15 s (horloge simulée).
  2. Sans directive, le délai reste de 1 s.
  3. Une directive pour un autre agent n'est pas appliquée.
  4. Une valeur au-delà du plafond produit un code d'erreur stable.
  5. L'attente imposée par la directive ne provoque pas de `timeout`.
  6. **En politique `warn` comme `enforce`, la directive est appliquée.**

### DV-05. Avertissements de collecte partielle — MUST (0.2.0, socle de l'alerte `robots.txt`)

- **Besoin.** `Collected(complete=False)` ne dit pas pourquoi une collecte est partielle.
- **Forme.** `Collected(items, complete=False, warnings=("budget_exceeded",))` (ADR-0027).
- **Sécurité.** Codes stables `[a-z][a-z0-9_]{0,63}`, nombre plafonné (8), sans détail libre.
- **Critères d'acceptation.**
  1. Les codes figurent dans l'état des sources (`source_status`) et dans `veilleur sources`.
  2. Un code invalide est écarté sans faire échouer la collecte.
  3. Un greffon qui n'en fournit pas se comporte comme aujourd'hui.

### DV-06. Expiration des éléments d'une collecte partielle — COULD (0.3.0)

- **Besoin.** Une source lue par fenêtre glissante reste partielle : ses éléments s'accumulent et le `state` grossit
  jusqu'à être sauté (`package_too_large`). COULD : le greffon n'en a pas besoin à court terme (taille des `state` à
  suivre en exploitation).
- **Forme.** `CollectedItem(fields, key, url, expires_at=...)` (ADR-0027).
- **Sécurité.** Date validée (avec fuseau), sans effet sur la conservation des paquets déjà scellés.
- **Critères d'acceptation.**
  1. Un élément expiré n'est plus dans le paquet `state`.
  2. Il n'apparaît pas comme `gone` dans un `delta`.
  3. Un élément sans date se comporte comme aujourd'hui.
  4. Un élément revu après expiration redevient courant.

**Non demandé par le greffon et non retenu** (WON'T) : exécution de JavaScript ; état persistant d'un greffon (il le
garde de son côté).

## 12. Construire ou réutiliser (ajouts seulement)

La reprise ne compare que les ajouts ; le projet lui-même n'est pas remis en cause.

- **Analyse de `robots.txt` et `Crawl-delay`.** `urllib.robotparser` (bibliothèque standard) lit `Crawl-delay` mais
  applique la première règle qui correspond, pas la plus longue (RFC 9309 §2.2.2), et ne dit pas quelle règle a joué
  [Certain : essai sous Python 3.12.13]. Protego (BSD-3, 0.7.0 du 2026-09-21, sans dépendance) suit RFC 9309 et lit
  `Crawl-delay`, mais ne rend pas non plus la règle en cause. **Décision : analyseur propre** (≈ 150 lignes : groupes,
  règle la plus longue, `*`, `$`, `Crawl-delay`), dont l'alerte a besoin ; **Protego en dépendance de développement
  seulement**, comme oracle de tests différentiels, sur le précédent de PyNaCl (ADR-0009) [D8].
- **Cookies de session (DV-02).** `http.cookiejar` suppose les objets de `urllib.request` et une logique de domaine
  inutile (et risquée) pour une session limitée à un hôte. **Décision : stockage propre lié à l'hôte exact**, analyse de
  `Set-Cookie` par `http.cookies.SimpleCookie` de la bibliothèque standard (ADR-0024).
- **POST, limites par hôte, avertissements, expiration** : extensions du code existant, rien à réutiliser.

## 13. Réserves

Les réserves des lots G1 à G6 sont reprises, numérotées R01 à R26 et classées de la plus à la moins importante, dans
la section `## Réserves` de `docs/PLAN.md`. Priorité : R01 à R08 (sécurité) MUST ; R09 à R14 (disponibilité) SHOULD ;
R15 à R20 (exactitude) COULD ; R21 à R23 et R25 (confort, entretien) COULD ; R24 (marque) hors lot, action de
l'utilisateur.

## Sources

- `cahier_des_charges.MD`, `plan.md`, `CLAUDE.md`, code et tests du dépôt, commit `0be164e`, consultés le 2026-11-19.
- `~/projects/veilleur-marches/docs/DEMANDES-VEILLEUR.md`, commit `4cccab5`, consulté le 2026-11-19.
- RFC 9309 — https://www.rfc-editor.org/rfc/rfc9309.html, consulté le 2026-11-19.
- Protego — https://pypi.org/project/Protego/, consulté le 2026-11-19.
- Autres sources de la politique `robots.txt` : voir `docs/adr/0022-politique-robots-txt.md`.
