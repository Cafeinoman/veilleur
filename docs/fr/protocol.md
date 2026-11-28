# Protocole Veilleur 1.0

*[English version](../en/protocol.md) (le texte anglais fait foi ; cette traduction est informative)*

Ce document dit comment un serveur Veilleur et un outil de réception se jumellent, authentifient les requêtes et
échangent des paquets de rapports scellés. Il suffit pour écrire un outil de réception sans lire le code du serveur.
L'implémentation de référence est le paquet Python `veilleur-protocol` (`protocol/` dans le dépôt) ; les vecteurs de
test de `protocol/vectors/` font partie de la spécification.

Les mots DOIT, NE DOIT PAS, DEVRAIT et PEUT s'entendent au sens de la RFC 2119.

## 1. Vue d'ensemble

- L'administrateur crée un **jumelage** : un secret aléatoire de 32 octets et un `key_id`. L'outil de réception les
  reçoit une fois, avec la clé publique de signature du serveur, dans un **code de jumelage** (§3).
- Toutes les clés dérivent du secret de jumelage, une par usage et par portée (§4).
- Un **paquet** est une archive zip dont le `manifest.json` est signé par le serveur (§6) et donne l'empreinte de
  chaque autre fichier (§7), scellée dans une **enveloppe** authentifiée (§5).
- Chaque requête HTTP de l'outil de réception est authentifiée par un HMAC (§8). Le serveur ne se connecte jamais à
  l'outil de réception.
- Un **lecteur** contrôle tout, dans un ordre fixé, avant d'interpréter la moindre donnée (§10).

## 2. Encodages

| Nom | Définition |
|---|---|
| base64url | alphabet de la RFC 4648 §5, **sans remplissage**. Un décodeur DOIT refuser le remplissage, tout autre caractère et les encodages non canoniques (bits finaux inutilisés non nuls). |
| hex | hexadécimal en minuscules |
| `key_id` | identifiant de jumelage : 8 octets aléatoires, soit 16 chiffres hexadécimaux |
| `uid` | identifiant d'abonnement : 16 octets aléatoires, soit 32 chiffres hexadécimaux ; choisi par qui crée l'abonnement (le serveur ou l'outil de réception) |
| horodatage | UTC, à la seconde, exactement `AAAA-MM-JJTHH:MM:SSZ` (par exemple `2026-11-17T06:00:00Z`) |
| JSON | RFC 8259, UTF-8, sans indicateur d'ordre des octets. Un lecteur DOIT refuser un objet dont un nom de membre est en double et les valeurs non JSON `NaN`, `Infinity` et `-Infinity` ; il PEUT refuser un nombre qu'il ne sait pas représenter. Chaque refus prend le code de ce qui est lu (`bad_pairing_code`, `bad_rotation`, `bad_manifest`, `bad_items`, `bad_subscription`). |

Les écrivains produisent du JSON compact (sans blanc superflu), aux membres triés. Les lecteurs NE DOIVENT PAS en
dépendre : signatures et empreintes portent sur des octets exacts, jamais sur une resérialisation.

## 3. Code de jumelage

```
VEIL1:<base64url(objet JSON)>
```

| Membre | Type | Valeur |
|---|---|---|
| `v` | entier | `1` |
| `server` | chaîne | origine du serveur, `https://hôte[:port]` (sans identifiants, chemin, requête ni fragment, pas même un `?` ou un `#` vides ; un seul `/` final est toléré), ou `folder:` pour une livraison par dossier seulement |
| `key_id` | chaîne | `key_id` du jumelage |
| `secret` | chaîne | base64url du secret de jumelage de 32 octets |
| `sign_key` | chaîne | base64url de la clé publique Ed25519 du serveur, 32 octets |
| `ntfy` | objet, facultatif | `{"url": adresse https, "topic": chaîne non vide, "token": absent, ou chaîne non vide (pas `null`)}` |

Dans `https://hôte[:port]`, `hôte` est un nom DNS (étiquettes de lettres, de chiffres et de traits d'union internes,
de 1 à 63 caractères, séparées par des points, 253 caractères au plus, la dernière étiquette pas entièrement
numérique), une adresse IPv4 en décimal pointé sans zéro initial, ou une adresse IPv6 entre crochets ; `port` est un
nombre décimal de 1 à 65535 sans zéro initial. Le membre `ntfy.url` a la même forme, suivie éventuellement d'un chemin
et d'une requête : `/` ou `?`, puis des lettres, des chiffres et ``-._~!$&'()*+,;=:@/?%`` (sans fragment).

Un lecteur DOIT ignorer les blancs autour du code, refuser un code de plus de 4096 caractères et refuser un code qui
ne respecte pas ce tableau (`bad_pairing_code`). Les membres inconnus DOIVENT être ignorés. Le code de jumelage n'est
montré qu'une fois ; il contient le secret et DOIT être traité comme tel.

## 4. Dérivation des clés

```
clé = HKDF-SHA256(IKM = secret de jumelage, sel, info, L = 32)        (RFC 5869)
```

| Usage | `info` (ASCII) | Portée, sel |
|---|---|---|
| scellement des paquets (serveur → outil de réception) | `veilleur-report` | abonnement : sel = les 16 octets de son `uid` |
| scellement des documents d'abonnement (outil de réception → serveur) | `veilleur-subscription` | abonnement : sel = les 16 octets de son `uid` |
| authentification des requêtes | `veilleur-auth` | l'abonnement nommé dans le chemin de la requête (sel = ses 16 octets), sinon le jumelage (sel vide) |

Une clé sert donc un usage et une portée : le paquet d'un abonnement ne peut jamais être ouvert, ni passer, pour
celui d'un autre.

## 5. Enveloppe

```
en-tête   = magie "VEIL" (4 octets) || version 0x01 (1 octet) || uid (16 octets) || seq (8 octets, non signé,
            gros-boutiste) || genre (1 octet)                                                       -- 30 octets
enveloppe = en-tête || nonce (24 octets) || XChaCha20-Poly1305(clé, nonce, clair, données associées = en-tête)
```

`chiffré || étiquette (16 octets)` suit le nonce. XChaCha20-Poly1305 est la construction de draft-irtf-cfrg-xchacha
(sous-clé HChaCha20, puis l'AEAD ChaCha20-Poly1305 de la RFC 8439). Le nonce est aléatoire pour chaque enveloppe.

| Octet `genre` | Genre | Clé | Clair |
|---|---|---|---|
| `0x01` | `delta` | paquets | archive du paquet (§7) |
| `0x02` | `state` | paquets | archive du paquet |
| `0x03` | `history` | paquets | archive du paquet |
| `0x10` | `subscription` | abonnement | document d'abonnement (§7.6) |

`seq` est inférieur à 2^63. L'en-tête circule en clair : un paquet trouvé dans un dossier dit à quel abonnement, quel
numéro et quel genre il appartient. Comme il forme les données associées, modifier l'un de ses octets fait échouer le
déchiffrement : un paquet ne peut être ni rejoué sous un autre numéro ou un autre genre, ni substitué à celui d'un
autre abonnement.

## 6. Signatures

### 6.1 Clé de signature du serveur

Le serveur détient une paire de clés Ed25519 (RFC 8032, Ed25519 pur, sans pré-hachage). Les clés publiques font
32 octets, les signatures 64. L'outil de réception fait confiance à la clé de son code de jumelage, puis à celles
qu'il adopte par des déclarations de rotation (§6.3).

Une clé publique DOIT être l'encodage canonique d'un point du sous-groupe d'ordre premier autre que le point neutre
(sans composante d'ordre faible). La RFC 8032 laisse une clé d'ordre faible « vérifier » des signatures de messages
que personne n'a signés, et les bibliothèques divergent sur ces clés ; l'exiger met tous les lecteurs d'accord et ne
refuse aucune clé produite par un serveur honnête. Un lecteur refuse toute autre clé : `bad_pairing_code` dans un code
de jumelage, `bad_rotation` dans une déclaration de rotation ; une signature sous cette clé n'est jamais valide.

### 6.2 Signature du manifeste

`manifest.sig` contient la signature de 64 octets des octets exacts de `manifest.json`. Comme le manifeste porte le
SHA-256 de chaque autre fichier, il authentifie le paquet entier.

### 6.3 Rotation de clé

Quand le serveur remplace sa clé, la clé sortante signe une déclaration qui nomme la clé entrante :

`rotation.json` (octets exacts signés) :

| Membre | Valeur |
|---|---|
| `protocol` | `"1.0"` |
| `old_key` | base64url de la clé publique sortante |
| `new_key` | base64url de la clé publique entrante |
| `issued_at` | horodatage |

`rotation.sig` contient la signature de `rotation.json` par `old_key`. Le serveur joint les deux fichiers à chaque
paquet pendant 90 jours après la rotation. Un lecteur qui fait confiance à `old_key` et trouve le manifeste signé par
`new_key` adopte `new_key` (§10, étape 7). Une fois `new_key` adoptée, l'outil de réception DOIT cesser de faire
confiance à `old_key` : la rotation est le moyen pour le serveur de se remettre du vol de sa clé, la clé volée ne doit
donc plus pouvoir signer. Un paquet d'un autre abonnement encore signé par `old_key` est alors refusé (`bad_signature`) ;
l'outil de réception demande un `state` (§9), que le serveur signe avec `new_key`. Un dossier ne permet pas cette
demande : un export qui contient un paquet signé par `old_key` contient aussi ce `state`, et les paquets y restent pour
qu'un outil de réception resté sur une clé plus ancienne puisse suivre chaque déclaration. Un outil de réception
qui a manqué toute la fenêtre de 90 jours doit être jumelé de nouveau ; de même pour celui à qui il manque un paquet
purgé et qui a manqué au moins deux rotations, le `state` qui comble le trou ne portant que la dernière déclaration.

## 7. Paquets

### 7.1 Archive

Le clair d'une enveloppe de paquet est une archive zip (APPNOTE), méthode de compression 0 (stockée) ou 8 (deflate),
sans chiffrement, sans dossier, sur un seul disque, sans Zip64 et sans descripteur de données (indicateurs généraux
limités aux bits 1, 2 et 11) ; chaque en-tête local porte les mêmes indicateurs, méthode, CRC, tailles et nom que le
répertoire central. Elle ne contient que ces fichiers, chacun une fois au plus, à la racine :

| Fichier | Obligatoire | Contenu |
|---|---|---|
| `manifest.json` | oui | §7.2, 1 Mio au plus |
| `manifest.sig` | oui | §6.2, 64 octets |
| `items.jsonl` | oui | §7.4 |
| `rotation.json`, `rotation.sig` | ensemble ou pas du tout | §6.3 ; `rotation.json` 4096 octets au plus |
| `report.<ext>` | non | rendu lisible, `<ext>` de la forme `[a-z0-9]{1,16}` (par exemple `report.md`, `report.html`) |

Les écrivains DEVRAIENT dater chaque fichier du 1980-01-01 00:00:00, pour que les archives ne révèlent rien de
l'horloge du serveur au-delà du manifeste.

### 7.2 Manifeste

| Membre | Type | Valeur |
|---|---|---|
| `protocol` | chaîne | `"1.0"` ; un lecteur accepte `1.<mineure>` (`<mineure>` un nombre décimal sans zéro initial, de longueur quelconque) et refuse toute autre version majeure |
| `uid` | chaîne | abonnement, égal à celui de l'enveloppe |
| `seq` | entier | égal à celui de l'enveloppe |
| `kind` | chaîne | `delta`, `state` ou `history`, égal à celui de l'enveloppe |
| `created_at` | horodatage | date de fabrication du paquet |
| `period` | objet | `{"from": horodatage ou null, "to": horodatage}`, les deux membres présents : ce que couvre le paquet |
| `files` | objet | nom de fichier → SHA-256 en hex, pour **chaque** fichier de l'archive sauf `manifest.json` et `manifest.sig` |
| `sources` | tableau d'objets | état des collectes derrière l'abonnement (§7.5) |

Les membres inconnus DOIVENT être ignorés (les versions mineures peuvent en ajouter).

### 7.3 Numérotation

Les paquets d'un abonnement sont numérotés à partir de 1, sans trou, dans l'ordre où le serveur les produit. Le
premier paquet d'un nouvel abonnement est un `state` ; les suivants sont des `delta`.

Un `state` ou un `history` préparé à la demande (§9) porte le numéro du dernier paquet dont il tient compte : l'outil
de réception reprend ensuite avec les paquets qui suivent ce numéro. Un tel paquet et le `delta` de même numéro se
distinguent par leur genre, que l'enveloppe authentifie.

### 7.4 `items.jsonl`

JSON Lines : un objet JSON par ligne, chaque ligne terminée par un saut de ligne (`0x0A`), sans ligne vide ; un
fichier vide signifie aucun élément. Les lignes sont triées par `key`, dans l'ordre strictement croissant des points
de code Unicode (les clés sont donc uniques).

| Membre | Type | Valeur |
|---|---|---|
| `key` | chaîne non vide | clé stable fournie par le collecteur |
| `change` | chaîne | `new`, `changed` ou `gone` |
| `hash` | chaîne | SHA-256 en hex calculé par le serveur à partir des champs de l'élément ; les outils de réception le comparent, sans avoir à le recalculer |
| `fields` | objet | les données de l'élément (pour `gone`, les derniers champs connus) |
| `fetched_at` | horodatage | date de la collecte |
| `url` | chaîne ou null | adresse de l'élément à sa source, s'il y en a une |

`items.jsonl` fait foi ; les rendus en dérivent et ne servent qu'à la lecture.

### 7.5 État des sources

Chaque élément de `sources` décrit une collecte : `id` (chaîne), `ok` (booléen), `last_success` (horodatage ou null),
`error` (code d'erreur stable ou null), plus des membres qu'un lecteur DOIT ignorer s'il ne les connaît pas. Il ne
contient jamais de détail interne (traces d'exécution, adresses du serveur).

### 7.6 Document d'abonnement

Le corps de `PUT /v1/subscriptions/{uid}` est une enveloppe de genre `subscription`, scellée avec la clé
d'abonnement. Son `seq` est la version sur laquelle se fonde la modification : `0` pour créer l'abonnement, sinon la
version renvoyée par le `PUT` précédent. Le clair est un objet JSON dont les membres (collecteur, paramètres, filtres,
périodicité, langue, rendus) sont définis avec l'interface HTTP (§9.1). L'enveloppe entière forme le corps de la requête :
elle fait donc au plus 1 000 000 octets (§9), et le clair au plus 999 930 octets.

## 8. Authentification des requêtes

Chaque requête porte :

```
X-Veilleur-Date: <horodatage>
Authorization: Veilleur <key_id>:<base64url(HMAC-SHA256(A, chaîne à signer))>
```

```
chaîne à signer = méthode "\n" chemin-et-requête "\n" X-Veilleur-Date "\n" hex(SHA-256(corps))
```

- `méthode` en lettres majuscules ; `chemin-et-requête` exactement tel qu'envoyé sur la ligne de requête
  (encodage-pourcent inchangé), en ASCII, commençant par `/`, sans saut de ligne ; sinon la requête est refusée
  (`bad_authorization`) ; le corps est vide pour `GET` et `DELETE` (son empreinte est alors celle de la chaîne
  vide).
- `A` est la clé `veilleur-auth` (§4) de la portée de la requête : quand le chemin commence par
  `/v1/subscriptions/<uid>` suivi de `/`, de `?` ou de sa fin, la portée est cet abonnement (un `uid` mal formé à cet
  endroit est refusé) ; sinon, le jumelage.
- Le serveur contrôle, dans cet ordre, et s'arrête au premier échec : un en-tête `Authorization` absent ou mal formé,
  y compris un MAC qui n'est pas le base64url canonique de 32 octets (`bad_authorization`) ; un `X-Veilleur-Date`
  absent ou mal formé (`bad_date`) ; une date à plus de **5 minutes** de son horloge dans un sens ou dans l'autre
  (`stale_date`) ; puis il retrouve le secret par le `key_id` et compare le MAC en temps constant
  (`bad_authorization`).

La date borne le rejeu à une fenêtre de 5 minutes. Dans cette fenêtre, un rejeu est sans effet : une lecture ; un
`PUT` fondé sur une version désormais dépassée reçoit `409` ; un `uid` supprimé n'est jamais réutilisé (§9.1). Voir le
[modèle de menace](threat-model.md), §4.

## 9. Interface HTTP `/v1`

Toutes les requêtes sont authentifiées (§8). Chaque réponse porte `Cache-Control: no-store`. Les réponses d'erreur
ont un corps JSON `{"code", "message"}` : `code` est un identifiant anglais stable (§9.3), `message` un texte traduit
sans détail interne, dans la langue d'`Accept-Language` (`en` ou `fr`), sinon celle du serveur.

| Requête | Réponse |
|---|---|
| `GET /v1/collectors` | `200 {"collectors": [{"name", "schema"}]}` : collecteurs permis à ce jumelage, avec le schéma JSON de leurs paramètres |
| `GET /v1/subscriptions` | `200 {"subscriptions": [{"uid", "origin", "name", "version"}]}` : abonnements vivants (non supprimés) de ce jumelage, triés par `uid` ; `origin` vaut `"team"` (déclaré par l'administrateur, avec son `name`) ou `"client"` (créé par l'outil de réception, sans `name`) ; les paramètres n'y figurent jamais |
| `PUT /v1/subscriptions/{uid}` | document d'abonnement scellé (§7.6, §9.1) ; `200 {"version"}` ; `409` si fondé sur une version dépassée |
| `DELETE /v1/subscriptions/{uid}` | `204` |
| `GET /v1/subscriptions/{uid}/reports?after=N` | `200 {"packages": [{"seq", "size", "sha256"}], "oldest", "last"}`, en clair, sans contenu |
| `GET /v1/subscriptions/{uid}/reports/{n}` | `200` paquet (`application/octet-stream`) ; `410` si purgé (les paquets sont gardés 90 jours) |
| `GET /v1/subscriptions/{uid}/state` | `200` paquet `state`, ou `202` avec `Retry-After` pendant sa préparation |
| `GET /v1/subscriptions/{uid}/history?since=AAAA-MM-JJ` | `200` paquet `history`, ou `202` avec `Retry-After` |

États : `400`, `401` (authentification), `403` (jumelage révoqué, ou collecteur non autorisé pour ce jumelage), `404`,
`409`, `410`, `413` (corps de plus de 1 000 000 octets), `429`, `500`. Après un `410`, l'outil de réception demande un `state`.
Le serveur ne lit le corps qu'une fois l'en-tête `Authorization`, la date et le `key_id` acceptés (§8), pour vérifier
son empreinte. Au-delà de 300 réponses `401` par minute, les requêtes non authentifiées reçoivent `429` à la place ; les
requêtes authentifiées n'en sont pas affectées.

Le serveur aiguille sur le chemin exactement tel que signé (§8), sans le décoder ni le normaliser : `N` et `n` sont
des nombres décimaux sans zéro initial, une requête (partie après `?`) non prévue ici est refusée (`400`), et tout le
reste reçoit `404`. Chaque jumelage a son propre espace d'`uid` : l'abonnement d'un autre jumelage reçoit `404`, comme
un abonnement qui n'existe pas.

### 9.1 Document d'abonnement

| Membre | Type | Valeur |
|---|---|---|
| `collector` | chaîne | nom d'un collecteur que ce jumelage peut utiliser (`GET /v1/collectors`) |
| `params` | objet, facultatif | les paramètres du collecteur, valides selon son schéma ; par défaut `{}` |
| `filters` | tableau, facultatif | au plus 16 objets `{"name", "params"}` : filtres appliqués dans l'ordre ; par défaut `[]` |
| `frequency` | chaîne, facultative | `every_round`, `daily` (par défaut) ou `weekly` |
| `language` | chaîne, facultative | langue des rendus : `en` (par défaut) ou `fr` |
| `renderings` | tableau, facultatif | au plus 8 noms distincts de rendus (par exemple `markdown`) ; par défaut `[]` |

Les membres inconnus sont ignorés. Le premier `PUT` (version de base `0`) crée l'abonnement en version `1` ; chaque
`PUT` suivant doit se fonder sur la version courante et renvoie la suivante. `DELETE` augmente aussi la version et
laisse une pierre tombale : un `uid` supprimé n'est jamais réutilisé (`PUT` reçoit `409` `subscription_deleted`,
`DELETE` reçoit de nouveau `204`, sans effet), de sorte qu'une création ou une suppression rejouée ne change rien
(modèle de menace §4). Un outil de réception qui veut retrouver un abonnement tire un nouvel `uid`.

### 9.2 Paquets d'un abonnement

Le premier paquet d'un abonnement neuf est un `state` (§7.3), produit dès que sa première collecte réussit, même sans
élément ; jusque-là, `reports` ne liste rien (`"last": 0`) et `state` répond `202`. Ensuite, un `delta` est produit
quand le rapport de l'abonnement est dû (à chaque tour, après un jour environ, ou après une semaine environ) et que
quelque chose a changé ; un `delta` vide n'est jamais produit. `oldest` est le plus ancien numéro encore gardé (ou
`null`), `last` le dernier numéro produit (`0` s'il n'y en a pas).

Un `state` demandé décrit ce que détient l'outil de réception après le paquet `last`, et porte ce numéro. Un
`history` liste les éléments rapportés pour la première fois (`new`), modifiés (`changed`) ou disparus (`gone`)
depuis 00:00 UTC à la date donnée, dans la limite des 90 jours que le serveur garde ; son `period.from` est cette date.

### 9.3 Codes d'erreur de l'interface

En plus des codes du §11 (`bad_authorization`, `bad_date`, `stale_date` avec `401` ; les codes d'une enveloppe
d'abonnement refusée avec `400`, `too_large` avec `413`) :

| Code | État | Signification |
|---|---|---|
| `bad_request` | 400 | requête mal formée (partie requête, numéro, date, `Content-Length`) |
| `invalid_subscription` | 400 | un membre du document d'abonnement a un type ou une valeur incorrects |
| `invalid_params` | 400 | les paramètres ne respectent pas le schéma de leur collecteur ou filtre |
| `unknown_collector`, `unknown_filter`, `unknown_renderer` | 400 | non installé sur ce serveur |
| `revoked` | 403 | le jumelage est révoqué |
| `collector_not_allowed` | 403 | collecteur non autorisé pour ce jumelage |
| `team_subscription` | 403 | un abonnement d'équipe est géré par l'administrateur, pas par l'interface |
| `not_found` | 404 | ressource inexistante |
| `version_conflict` | 409 | `PUT` fondé sur une version dépassée |
| `subscription_deleted` | 409 | l'`uid` appartient à un abonnement supprimé |
| `purged` | 410 | le paquet n'est plus gardé |
| `body_too_large` | 413 | corps de plus de 1 000 000 octets |
| `rate_limited` | 429 | trop de requêtes de ce jumelage, ou trop de requêtes non authentifiées |
| `internal_error` | 500 | défaillance du serveur, sans détail |

## 10. Lecteur

### 10.1 Limites

| Limite | Par défaut |
|---|---|
| taille de l'enveloppe | 64 Mio |
| nombre de fichiers de l'archive | 32 |
| taille déclarée d'un fichier | 64 Mio (`manifest.json` 1 Mio, `rotation.json` 4096 octets, signatures 64 octets) |
| somme des tailles déclarées | 128 Mio |
| taille d'une enveloppe d'abonnement | 1 000 000 octets (la limite du corps de requête, §9) |

Un lecteur PEUT abaisser ces limites ; une limite par fichier abaissée borne aussi les fichiers indiqués entre parenthèses. Il DOIT garder les données déchiffrées en mémoire, ou dans un stockage que lui
seul peut lire ; l'implémentation de référence n'écrit rien sur le disque.

### 10.2 Ordre des contrôles

Un lecteur qui ouvre un paquet de l'abonnement `uid`, en attendant éventuellement un numéro et un ensemble de genres,
DOIT faire ces contrôles dans cet ordre et s'arrêter au premier échec, avec le code indiqué :

1. enveloppe plus grande que la limite : `too_large` ;
2. moins de 70 octets, magie autre que `VEIL` : `bad_envelope` ; version autre que 1 : `unsupported_version` ;
   `seq` ≥ 2^63 ou octet de genre inconnu : `bad_envelope` ;
3. `uid` autre que celui attendu : `uid_mismatch` ; genre non attendu : `kind_mismatch` ; numéro autre que celui
   attendu (s'il y en a un) : `seq_mismatch` ;
4. le déchiffrement avec la clé du genre de l'enveloppe échoue : `decryption_failed` ;
5. archive :
   - pas d'enregistrement de fin du répertoire central (le dernier dont le commentaire termine l'archive), plusieurs
     disques, ou un répertoire central qui ne se termine pas exactement là où commence cet enregistrement (position
     plus taille) : `bad_archive` ;
   - l'enregistrement annonce plus d'entrées que la limite : `too_many_files`, avant d'analyser le répertoire ;
   - puis le répertoire central, entrée par entrée :
     - une entrée tronquée ou mal formée : `bad_archive` ;
     - un nom non permis par le §7.1 (ou non ASCII) : `unexpected_file` ;
     - un nom vu deux fois, d'autres indicateurs généraux que ceux permis par le §7.1 (chiffrement, descripteur de
       données…), une méthode de compression autre que 0 ou 8, un marqueur Zip64 (`0xFFFFFFFF` comme taille ou
       position) : `bad_archive` ;
     - une taille déclarée au-delà de sa limite : `file_too_large` ;
   - des entrées qui ne remplissent pas exactement le répertoire central : `bad_archive` ;
   - puis la somme des tailles déclarées au-delà de sa limite : `too_large` ;
   - puis un fichier obligatoire absent, ou un seul de `rotation.json` / `rotation.sig` : `missing_file` ;
6. lire `manifest.json`, `manifest.sig`, et `rotation.json` / `rotation.sig` s'ils sont présents : la totalité des
   données compressées de l'entrée (sa taille compressée, à partir de l'en-tête local) doit se décompresser en
   exactement la taille et le CRC déclarés, sans jamais rendre plus que la taille déclarée ; un en-tête local dont les
   indicateurs, la méthode, le CRC, les tailles ou le nom diffèrent du répertoire central, des données hors de l'archive, des données corrompues, des données qui se
   prolongent au-delà de la taille déclarée, une taille ou un CRC différents de ceux déclarés donnent `bad_archive` ;
7. signature :
   - si une déclaration de rotation est présente, elle doit être bien formée et signée par son `old_key` :
     `bad_rotation` ;
   - le manifeste est accepté s'il est signé par une clé de confiance ;
   - sinon, si une déclaration de rotation est présente, que son `old_key` est de confiance et que le manifeste est
     signé par son `new_key`, le manifeste est accepté et `new_key` adoptée ;
   - sinon : `bad_signature` ;
8. manifeste :
   - pas un objet JSON : `bad_manifest` ;
   - `protocol` autre que `1.<mineure>` : `unsupported_version` ;
   - `uid`, `seq` (un entier, pas un booléen) ou `kind` différents de ceux de l'enveloppe ; `created_at` ou `period`
     mal formés ; `sources` qui n'est pas un tableau d'objets ; `files` qui n'est pas un objet d'empreintes SHA-256 en
     hex : `bad_manifest` ;
   - un fichier listé mais absent : `missing_file` ; un fichier présent mais non listé : `unexpected_file` ;
9. chaque fichier listé : lu comme à l'étape 6, puis son SHA-256 diffère du manifeste : `hash_mismatch` ;
10. `items.jsonl` ne respecte pas le §7.4 : `bad_items`.

Alors seulement l'outil de réception peut se servir du paquet. Lors de la lecture d'un dossier (sans numéro attendu),
l'outil de réception vérifie que les numéros se suivent.

Un serveur qui ouvre un document d'abonnement applique les étapes 1 à 4 (limite de 1 000 000 octets, genre `subscription`), puis
refuse un clair qui n'est pas un objet JSON (`bad_subscription`).

## 11. Codes d'erreur

Identifiants stables, jamais traduits :

| Code | Sens |
|---|---|
| `bad_encoding` | base64url, identifiant ou horodatage mal formé |
| `bad_pairing_code` | code de jumelage mal formé |
| `too_large` | enveloppe ou contenu de l'archive au-delà des limites |
| `bad_envelope` | pas une enveloppe Veilleur |
| `unsupported_version` | version d'enveloppe ou de protocole non prise en charge |
| `uid_mismatch`, `seq_mismatch`, `kind_mismatch` | enveloppe d'un autre abonnement, d'un autre numéro ou d'un autre genre |
| `decryption_failed` | échec de l'authentification de l'enveloppe (mauvaise clé, données altérées) |
| `bad_archive` | archive illisible, nom en double, entrée chiffrée, compression non prise en charge, taille ou CRC différents de ceux déclarés |
| `too_many_files`, `unexpected_file`, `missing_file`, `file_too_large` | contenu de l'archive non permis |
| `bad_signature` | manifeste non signé par une clé de confiance |
| `bad_rotation` | déclaration de rotation mal formée ou faussement signée |
| `bad_manifest` | manifeste mal formé, ou qui ne correspond pas à l'enveloppe |
| `hash_mismatch` | un fichier ne correspond pas à son empreinte dans le manifeste |
| `bad_items` | `items.jsonl` mal formé |
| `bad_subscription` | document d'abonnement mal formé |
| `bad_authorization` | `Authorization` absent ou mal formé, ou MAC différent |
| `bad_date` | `X-Veilleur-Date` absent ou mal formé |
| `stale_date` | date de la requête à plus de 5 minutes de l'horloge du serveur |

## 12. Vecteurs de test

`protocol/vectors/` contient des fichiers JSON (valeurs binaires en hex) :

| Fichier | Contenu |
|---|---|
| `keys.json` | secret, `uid` (ou null), `info` → clé dérivée |
| `pairing.json` | codes de jumelage et leurs membres décodés |
| `requests.json` | requêtes, chaîne à signer, portée, en-tête `Authorization` |
| `subscriptions.json` | documents d'abonnement scellés |
| `packages.json` | paquets valides (delta, state, history, rotation de clé) : enveloppe, archive en clair et ce qu'un lecteur doit y trouver |
| `refusals.json` | paquets, requêtes et codes de jumelage qu'un lecteur doit refuser, avec le code attendu |

Ils sont produits par l'implémentation de référence (`tools/protocol_vectors.py`) et vérifiés par une implémentation
indépendante écrite d'après ce document, avec libsodium au lieu de pycryptodomex (`tools/check_vectors.py`) ; la CI
exécute les deux.

## 13. Versions

Le préfixe du code de jumelage (`VEIL1:`), l'octet de version de l'enveloppe et le membre `protocol` du manifeste
portent la version. Une version mineure (`1.x`) n'ajoute que des membres facultatifs, que les lecteurs plus anciens
ignorent. Une version majeure change le préfixe, l'octet de version et le numéro majeur ; les lecteurs refusent ce
qu'ils ne connaissent pas.
