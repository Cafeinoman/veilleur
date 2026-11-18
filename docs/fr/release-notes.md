# Notes de version

## 0.1.0

Première version publique. C'est une version **alpha** : le protocole et les formats de données peuvent encore changer.

### Contenu

- **Collecte** : collecteurs `rss`, `json_api` et `page`, greffons, collecte mutualisée et client HTTP avec garde SSRF.
- **Rapports** : détection des changements, paquets `delta`, `state` et `history`, filtres `keywords`, `regex` et `dedup`, rendus `markdown` et `html` en français et en anglais.
- **Protocole 1.0** : paquets signés et chiffrés, requêtes signées, rotation de la clé du serveur, bibliothèque `veilleur-protocol` et vecteurs de test vérifiés par deux implémentations.
- **Livraison** : HTTPS ou dossier, notifications `ntfy` et `webhook` limitées à des comptes, récepteur de référence `veilleur-receive`.
- **Administration** : ligne de commande `veilleur`, jumelage et révocation, abonnements d'équipe déclarés en TOML.
- **Déploiement** : modules NixOS (hôte et conteneur isolé), unités systemd et configuration Caddy pour les autres distributions Linux.

### Non vérifié

- La charge avec plusieurs centaines d'abonnements.
- L'émission d'un vrai certificat Let's Encrypt.
- La construction et l'exécution sur `aarch64-linux`.

### Limites connues

- Un membre à qui il manque un paquet purgé et qui a manqué au moins deux rotations de clé doit être rejumelé.
- Le service en marche ne suit pas un `key rotate` lancé par un autre processus. Redémarrez le service après une rotation.
- Les requêtes non authentifiées ne sont pas limitées en débit.
- Une déclaration d'équipe cassée (greffon absent, par exemple) arrête le tour avant toute collecte.
- Le contrôle des conflits de ports ne couvre que ce que NixOS voit à l'évaluation.

Les secrets de jumelage n'offrent pas de confidentialité persistante : voir le [modèle de menace](threat-model.md).
