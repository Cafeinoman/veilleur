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
| JSON | RFC 8259, UTF-8, sans indicateur d'ordre des octets. Les noms de membres d'un objet sont uniques. |

Les écrivains produisent du JSON compact (sans blanc superflu), aux membres triés. Les lecteurs NE DOIVENT PAS en
dépendre : signatures et empreintes portent sur des octets exacts, jamais sur une resérialisation.

## 3. Code de jumelage

```
VEIL1:<base64url(objet JSON)>
```

| Membre | Type | Valeur |
|---|---|---|
| `v` | entier | `1` |
| `server` | chaîne | origine du serveur, `https://hôte[:port]` (sans identifiants, chemin, requête ni fragment ; un seul `/` final est toléré), ou `folder:` pour une livraison par dossier seulement |
| `key_id` | chaîne | `key_id` du jumelage |
| `secret` | chaîne | base64url du secret de jumelage de 32 octets |
| `sign_key` | chaîne | base64url de la clé publique Ed25519 du serveur, 32 octets |
| `ntfy` | objet, facultatif | `{"url": adresse https, "topic": chaîne non vide, "token": chaîne non vide facultative}` |

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
`new_key` adopte `new_key` (§10, étape 7). Un outil de réception qui a manqué toute la fenêtre de 90 jours doit être
jumelé de nouveau.

## 7. Paquets

### 7.1 Archive

Le clair d'une enveloppe de paquet est une archive zip (APPNOTE), méthode de compression 0 (stockée) ou 8 (deflate),
sans chiffrement, sans dossier. Elle ne contient que ces fichiers, chacun une fois au plus, à la racine :

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
| `protocol` | chaîne | `"1.0"` ; un lecteur accepte `1.<mineure>` et refuse toute autre version majeure |
| `uid` | chaîne | abonnement, égal à celui de l'enveloppe |
| `seq` | entier | égal à celui de l'enveloppe |
| `kind` | chaîne | `delta`, `state` ou `history`, égal à celui de l'enveloppe |
| `created_at` | horodatage | date de fabrication du paquet |
| `period` | objet | `{"from": horodatage ou null, "to": horodatage}` : ce que couvre le paquet |
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
version renvoyée par le `PUT` précédent. Le clair est un objet JSON d'au plus 1 Mio dont les membres (collecteur,
paramètres, filtres, périodicité, langue, rendus) sont définis avec l'interface HTTP.

## 8. Authentification des requêtes

Chaque requête porte :

```
X-Veilleur-Date: <horodatage>
Authorization: Veilleur <key_id>:<base64url(HMAC-SHA256(A, chaîne à signer))>
```

```
chaîne à signer = méthode "\n" chemin-et-requête "\n" X-Veilleur-Date "\n" hex(SHA-256(corps))
```

- `méthode` en majuscules ; `chemin-et-requête` exactement tel qu'envoyé sur la ligne de requête (encodage-pourcent
  inchangé), commençant par `/` ; le corps est vide pour `GET` et `DELETE` (son empreinte est alors celle de la chaîne
  vide).
- `A` est la clé `veilleur-auth` (§4) de la portée de la requête : quand le chemin commence par
  `/v1/subscriptions/<uid>` suivi de `/`, de `?` ou de sa fin, la portée est cet abonnement (un `uid` mal formé à cet
  endroit est refusé) ; sinon, le jumelage.
- Le serveur retrouve le secret par le `key_id`, refuse une date à plus de **5 minutes** de son horloge dans un sens
  ou dans l'autre (`stale_date`), puis compare le MAC en temps constant.

La date borne le rejeu à une fenêtre de 5 minutes ; les requêtes sont idempotentes (`GET`, `PUT` avec version,
`DELETE`), si bien qu'un rejeu dans la fenêtre ne change rien.

## 9. Interface HTTP `/v1`

Toutes les requêtes sont authentifiées (§8). Chaque réponse porte `Cache-Control: no-store`. Les réponses d'erreur
ont un corps JSON `{"code", "message"}` : `code` est un identifiant anglais stable, `message` un texte traduit sans
détail interne.

| Requête | Réponse |
|---|---|
| `GET /v1/collectors` | collecteurs permis à ce jumelage, avec le schéma JSON de leurs paramètres |
| `PUT /v1/subscriptions/{uid}` | document d'abonnement scellé (§7.6) ; `200 {"version"}` ; `409` si fondé sur une version dépassée |
| `DELETE /v1/subscriptions/{uid}` | `204` |
| `GET /v1/subscriptions/{uid}/reports?after=N` | `200 {"packages": [{"seq", "size", "sha256"}], "oldest", "last"}`, en clair, sans contenu |
| `GET /v1/subscriptions/{uid}/reports/{n}` | `200` paquet (`application/octet-stream`) ; `410` si purgé (les paquets sont gardés 90 jours) |
| `GET /v1/subscriptions/{uid}/state` | `200` paquet `state`, ou `202` avec `Retry-After` pendant sa préparation |
| `GET /v1/subscriptions/{uid}/history?since=AAAA-MM-JJ` | `200` paquet `history`, ou `202` avec `Retry-After` |

États : `400`, `401` (authentification), `403` (jumelage révoqué, ou collecteur non autorisé pour ce jumelage), `404`,
`409`, `410`, `413` (corps de plus de 1 Mo), `429`, `500`. Après un `410`, l'outil de réception demande un `state`.

## 10. Lecteur

### 10.1 Limites

| Limite | Par défaut |
|---|---|
| taille de l'enveloppe | 64 Mio |
| nombre de fichiers de l'archive | 32 |
| taille déclarée d'un fichier | 64 Mio (`manifest.json` 1 Mio, `rotation.json` 4096 octets, signatures 64 octets) |
| somme des tailles déclarées | 128 Mio |
| taille d'une enveloppe d'abonnement | 1 Mio |

Un lecteur PEUT abaisser ces limites. Il DOIT garder les données déchiffrées en mémoire, ou dans un stockage que lui
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
5. archive, d'après son répertoire central, entrée par entrée :
   - archive zip illisible : `bad_archive` ;
   - plus de fichiers que la limite : `too_many_files` ;
   - un nom non permis par le §7.1 : `unexpected_file` ;
   - un nom vu deux fois, une entrée chiffrée, une méthode de compression autre que 0 ou 8 : `bad_archive` ;
   - une taille déclarée au-delà de sa limite : `file_too_large` ;
   - puis la somme des tailles déclarées au-delà de sa limite : `too_large` ;
   - puis un fichier obligatoire absent, ou un seul de `rotation.json` / `rotation.sig` : `missing_file` ;
6. lire `manifest.json`, `manifest.sig`, et `rotation.json` / `rotation.sig` s'ils sont présents ; la décompression ne
   rend jamais plus que la taille déclarée, et une taille ou un CRC différents de ceux déclarés donnent `bad_archive` ;
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

Un serveur qui ouvre un document d'abonnement applique les étapes 1 à 4 (limite de 1 Mio, genre `subscription`), puis
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
