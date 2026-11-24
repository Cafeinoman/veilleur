# Modèle de menace

*[English version](../en/threat-model.md)*

Ce que Veilleur protège, contre qui, comment, et ce qu'il ne protège pas. Le détail du protocole est dans
[protocol.md](protocol.md).

## 1. Ce qui est protégé

| Bien | Où |
|---|---|
| **Contenu des rapports** (éléments, rendus) | base du serveur, paquets en transit ou dans un dossier, outil de réception |
| **Paramètres d'abonnement** (ce qu'un membre surveille) | en transit depuis l'outil de réception ; base du serveur |
| **Secrets de jumelage** | dossier d'état du serveur, outil de réception, code de jumelage une fois |
| **Clé de signature du serveur** | dossier d'état du serveur |
| **Identité et activité des membres** | jamais recueillies : ni compte, ni nom (le libellé d'un jumelage est un repère comme « poste 3 »), ni adresse IP dans les journaux |
| **Le serveur lui-même** | une machine sur Internet qui émet des requêtes pour le compte de ses utilisateurs |

Principe (spécification ES-01) : *le serveur connaît ce qu'il collecte, jamais ce que les destinataires en font.*

## 2. Adversaires

| Adversaire | Capacités |
|---|---|
| **Réseau** | lit, modifie, rejoue et supprime le trafic entre l'outil de réception et le serveur, ou les paquets transportés par dossier |
| **Client non jumelé** | envoie des requêtes quelconques à l'API publique |
| **Membre jumelé** | détient un secret de jumelage ; peut tenter d'atteindre d'autres abonnements, ou de se servir du serveur pour sonder des réseaux internes (SSRF) |
| **Source hostile** | un site ou une API surveillés qui renvoient un contenu piégé : énorme, mal formé, redirigeant vers des adresses internes |
| **Voleur d'un code de jumelage ou du stockage d'un outil de réception** | détient un secret de jumelage |
| **Compromission du serveur** | lit la base et le dossier d'état |

## 3. Menaces et parades

| Menace | Parade |
|---|---|
| Lecture des rapports en transit ou dans un dossier | enveloppe XChaCha20-Poly1305, clé dérivée par abonnement ; TLS en plus pour HTTPS |
| Fabrication ou modification d'un paquet | AEAD avec une clé que seuls le serveur et le jumelage connaissent ; signature Ed25519 du manifeste, qui porte l'empreinte de chaque fichier |
| Rejeu d'un paquet sous un autre numéro, genre ou abonnement | l'en-tête (uid, numéro, genre) forme les données associées de l'AEAD ; le manifeste le répète et il est signé |
| Rétention de paquets | les numéros se suivent sans trou ; l'outil de réception remarque un manque (`reports?after=N`) |
| Archive malveillante (traversée de chemin, bombe zip, trop de fichiers) | le lecteur contrôle noms, nombre et tailles déclarées avant de décompresser, ne décompresse jamais au-delà de la taille déclarée, n'écrit rien sur le disque ([protocol.md §10](protocol.md#10-lecteur)) ; testé à données aléatoires |
| Requête d'un client non jumelé | HMAC sur la méthode, le chemin et la requête, la date et l'empreinte du corps ; comparaison en temps constant ; `401` |
| Rejeu de requête | tolérance de 5 minutes sur la date ; écritures versionnées (voir le §4 pour ce qui reste) |
| Un membre qui atteint l'abonnement d'un autre | clé d'authentification dérivée pour l'abonnement nommé dans le chemin ; un jumelage ne voit que ses abonnements ; `403` pour un jumelage révoqué |
| SSRF par l'abonnement d'un membre | les collecteurs qui suivent une adresse donnée par le client sont refusés sauf autorisation de l'administrateur pour ce jumelage ; le client HTTP refuse les adresses de bouclage, privées, lien-local, CGNAT, de multidiffusion et réservées après résolution DNS et à chaque redirection ; la connexion se fait vers l'adresse contrôlée, jamais vers un nom résolu de nouveau (DNS rebinding), et un nom dont une seule adresse est interne est refusé ; plafonds de taille (après décompression), de durée et de redirections ; pare-feu sortant du conteneur en seconde barrière |
| Contenu hostile d'une source | plafonds de taille, de durée et de type de contenu dans le client HTTP ; une source en panne n'arrête pas le tour ; les erreurs de source sont rapportées par des codes stables, sans détail interne |
| Vol de la clé du serveur | rotation : la clé sortante signe la clé entrante, les outils de réception suivent sans nouveau jumelage et cessent de faire confiance à la clé sortante |
| Fuites par les journaux | ni corps, ni en-tête d'authentification, ni secret, ni paramètre d'abonnement, ni IP de membre dans les journaux ; le mandataire ne tient pas de journal d'accès |
| Fuites par les notifications | les notifications ne portent que des comptes, jamais de contenu |
| Requêtes surdimensionnées | corps de plus de 1 Mo refusés par l'application (`413`) |

## 4. Risques acceptés

Connus et documentés, ils découlent des choix de la spécification.

- **Pas de confidentialité persistante** (ES-12) : un secret de jumelage volé ouvre tous les paquets de ce jumelage,
  passés et futurs, que le voleur peut obtenir. Révoquer le jumelage arrête les paquets futurs ; changer le secret
  d'un jumelage revient à jumeler de nouveau.
- **Le serveur lit les paramètres d'abonnement** : il le doit, pour collecter. Ils ne sont chiffrés qu'en transit. Qui
  contrôle le serveur sait ce que surveille chaque jumelage (mais pas qui est le membre).
- **Métadonnées en clair** : l'en-tête d'une enveloppe montre l'`uid` de l'abonnement, le numéro du paquet et son
  genre ; sa taille donne l'ordre de grandeur du contenu ; `reports?after=N` liste numéros, tailles et empreintes.
  L'adversaire réseau ne les voit que s'il casse aussi TLS ; quiconque détient un dossier exporté les voit.
- **Fenêtre de rejeu** : une requête capturée malgré TLS peut être rejouée pendant 5 minutes. Un tel rejeu ne change
  rien : une lecture ; un `PUT` fondé sur une version désormais dépassée reçoit `409` ; un `DELETE` ou une création
  (`PUT` fondé sur la version 0) rejoués après une suppression trouvent une pierre tombale, car un `uid` supprimé n'est
  jamais réutilisé et les versions continuent de croître après une suppression
  ([protocol.md §9.1](protocol.md#91-document-dabonnement)). Reste ce que permet un retard : un adversaire qui retient
  une requête peut la délivrer jusqu'à 5 minutes plus tard.
- **Clé sortante compromise** : un outil de réception cesse de faire confiance à la clé sortante dès qu'il a adopté la
  clé entrante ([protocol.md §6.3](protocol.md#63-rotation-de-clé)). D'ici là, le voleur de la clé pourrait signer
  une rotation vers sa propre clé, mais ne pourrait toujours pas fabriquer un paquet que l'outil de réception accepte
  sans le secret de jumelage.
- **Compromission du serveur** : le serveur détient les secrets de jumelage et la clé de signature, donc tout. Le
  durcissement (utilisateur dédié, système en lecture seule, aucune capacité, filtrage des appels système, conteneur)
  réduit ce risque sans le supprimer.
- **Déni de service** : la limitation de débit (`429`) et les quotas protègent le serveur d'un jumelage, pas d'une
  attaque réseau déterminée ; c'est l'affaire de l'hôte.

## 5. Hors périmètre

La sécurité de l'outil de réception une fois le paquet ouvert (stockage, affichage), la sécurité de l'hôte et de ses
autres services, et la confidentialité de ce que publient les sources (public par nature).
