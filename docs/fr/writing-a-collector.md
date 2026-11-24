# Écrire un collecteur

Un collecteur est un greffon Python qui, pour des paramètres donnés, rend les éléments d'une source (spécification EF-01).
Veilleur reste générique : une source propre à un domaine est un greffon, maintenu hors du dépôt de Veilleur.
Un exemple complet se trouve dans [`examples/veilleur-example-collector`](../../examples/veilleur-example-collector).

## 1. Le contrat

Un collecteur est un objet (ou une classe, instanciée sans argument) qui a :

| Membre | Rôle |
|---|---|
| `name` | le nom du greffon, égal au nom de son *entry point* : `[a-z][a-z0-9_]{0,63}` |
| `schema` | schéma JSON des paramètres, dans le sous-ensemble que Veilleur valide (`type`, `properties`, `required`, `additionalProperties`, `enum`, `const`, longueurs, `pattern`, bornes, `items`, `minItems`, `maxItems`, `uniqueItems`, et les annotations `title`, `description`, `default`, `examples`, `format`) ; tout autre mot-clé fait refuser le greffon au chargement |
| `follows_client_urls` | `True` quand les paramètres désignent une adresse à lire : un outil de réception ne peut alors utiliser le collecteur que si l'administrateur l'autorise pour son jumelage |
| `collect(params, since, http)` | les éléments, sous la forme `Collected(items, complete=...)` ou de tout itérable de `CollectedItem` |
| `check_params(params)` (facultatif) | un contrôle que le schéma ne sait pas exprimer ; renvoie `None`, ou le pointeur JSON du paramètre fautif (`"/selector"`). Il s'exécute à la réception d'un abonnement, pour qu'une erreur soit refusée tout de suite (`400 invalid_params`) |

`collect` reçoit les paramètres déjà validés, la date de la dernière collecte réussie (`None` la première fois) et
le client HTTP du serveur.

## 2. Les éléments

`CollectedItem(fields, key=None, url=None)` :

- `fields` : un objet JSON (chaînes, nombres, booléens, `null`, listes, objets). Son SHA-256 sur le JSON canonique
  est l'empreinte de l'élément : tout changement de `fields` donne un élément **modifié**. Laissez de côté ce qui
  change sans signification (compteur de visites, date de génération).
- `key` : un identifiant stable fourni par la source. À défaut, Veilleur prend `url`, et à défaut l'empreinte du
  contenu.
- `url` : l'adresse de l'élément, `http` ou `https`, s'il en a une.

`Collected(items, complete=True)` : mettez `complete=False` quand vous savez ne pas avoir vu tous les éléments
(pagination arrêtée tôt, fenêtre des dernières entrées, entrées écartées). Un élément absent d'une collecte complète
devient **disparu** ; rien ne disparaît après une collecte partielle ou en échec.

## 3. Le réseau

N'utilisez **que** le client `http` passé à `collect`, jamais `urllib`, `requests` ni un *socket* :

```python
response = http.get(params["url"], accept=("application/json",))
response.status   # 2xx
response.url      # adresse finale, après redirections
response.headers  # content-type, etag, last-modified
response.body     # octets, 5 Mo au plus
```

Le client contrôle chaque adresse contre les réseaux privés et réservés après résolution DNS et à chaque
redirection, respecte `robots.txt`, tient un délai et un quota par hôte, met en cache les requêtes
conditionnelles, et plafonne taille et durée. `accept` liste les types de contenu attendus (`type/*` et `*+json`
sont permis) ; un autre type est refusé. En mode hors ligne (`offline = true`, et dans les tests), toute requête
échoue avec `network_unavailable`.

## 4. Les pannes

Levez `CollectorError("code")` avec un code stable (`[a-z][a-z0-9_]{0,63}`), jamais avec du détail : le code
figure dans les rapports et dans `veilleur sources`. Les codes du client (`address_refused`, `timeout`,
`http_404`…) passent tels quels. Toute autre exception compte comme `collector_failed`. Une source en panne
n'arrête jamais le tour.

## 5. La distribution

Déclarez l'*entry point* dans le `pyproject.toml` du greffon :

```toml
[project.entry-points."veilleur.collectors"]
text_lines = "veilleur_example_collector:TextLinesCollector"
```

Sous NixOS, le greffon s'ajoute par l'option du module et se construit dans l'environnement en lecture seule. Un
greffon qui ne se charge pas, dont le schéma est invalide ou dont le nom est déjà pris est écarté avec un
avertissement.

## 6. Les tests

Testez sans réseau : donnez à `collect` un faux client qui rend des réponses enregistrées, comme les tests de
Veilleur (`tests/server/http_fakes.py`). Vérifiez que le schéma est accepté (`veilleur.adapters.plugins.validated`)
et que les paramètres de vos exemples le respectent (`veilleur.core.domain.schema.validate`).

Les filtres (`veilleur.filters`) suivent le même modèle : `name`, `schema`, `apply(item, params)` qui rend
l'élément (éventuellement transformé) ou `None`, et au besoin `select(items, params)` pour un filtre qui a besoin
de tous les éléments à la fois.
