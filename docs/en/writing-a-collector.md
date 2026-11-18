# Writing a collector

A collector is a Python plugin that, for given parameters, returns the items of a source (specification EF-01).
Veilleur stays generic: a source belonging to one domain is a plugin, maintained outside Veilleur's repository.
A complete example lives in [`examples/veilleur-example-collector`](../../examples/veilleur-example-collector).

## 1. The contract

A collector is an object (or a class, instantiated without arguments) with:

| Member | Role |
|---|---|
| `name` | the plugin's name, equal to its entry point name: `[a-z][a-z0-9_]{0,63}` |
| `schema` | JSON schema of the parameters, in the subset Veilleur validates (`type`, `properties`, `required`, `additionalProperties`, `enum`, `const`, lengths, `pattern`, bounds, `items`, `minItems`, `maxItems`, `uniqueItems`, and the annotations `title`, `description`, `default`, `examples`, `format`); any other keyword makes the plugin refused at load time |
| `follows_client_urls` | `True` when the parameters name an address to fetch: receiving tools may then use the collector only if the administrator allows it for their pairing |
| `collect(params, since, http)` | the items, as `Collected(items, complete=...)` or any iterable of `CollectedItem` |
| `check_params(params)` (optional) | a check the schema cannot express; returns `None`, or the JSON pointer of the faulty parameter (`"/selector"`). It runs when a subscription is received, so that a mistake is refused at once (`400 invalid_params`) |

`collect` receives the parameters already validated, the date of the last successful collection (`None` the
first time) and the server's HTTP client.

## 2. Items

`CollectedItem(fields, key=None, url=None)`:

- `fields`: a JSON object (strings, numbers, booleans, `null`, lists, objects). Its SHA-256 over canonical JSON is
  the item's hash: any change in `fields` is a **changed** item. Leave out what changes without meaning (a
  visitor counter, a generation date).
- `key`: a stable identifier from the source. Without one, Veilleur uses `url`, and without it the hash of the
  content.
- `url`: the item's address, `http` or `https`, if it has one.

`Collected(items, complete=True)`: set `complete=False` when you know you did not see every item (paging stopped
early, a window of the latest entries, skipped entries). An item absent from a complete collection becomes
**gone**; nothing becomes gone after a partial or failed collection.

## 3. The network

Use **only** the `http` client given to `collect`, never `urllib`, `requests` or a socket:

```python
response = http.get(params["url"], accept=("application/json",))
response.status   # 2xx
response.url      # final address, after redirections
response.headers  # content-type, etag, last-modified
response.body     # bytes, at most 5 MB
```

The client checks every address against private and reserved networks after DNS resolution and at each
redirection, obeys `robots.txt`, keeps a delay and a quota per host, caches conditional requests, and caps size and
duration. `accept` lists the expected media types (`type/*` and `*+json` are allowed); another type is refused.
In offline mode (`offline = true`, and in the tests), every request fails with `network_unavailable`.

## 4. Failures

Raise `CollectorError("code")` with a stable code (`[a-z][a-z0-9_]{0,63}`), never with detail: the code is shown in
reports and in `veilleur sources`. The client's own codes (`address_refused`, `timeout`, `http_404`...) pass
through. Any other exception counts as `collector_failed`. A failing source never stops the round.

## 5. Packaging

Declare the entry point in the plugin's `pyproject.toml`:

```toml
[project.entry-points."veilleur.collectors"]
text_lines = "veilleur_example_collector:TextLinesCollector"
```

On NixOS, the plugin is added through the module's option and built into the read-only environment. A plugin that
cannot be loaded, has an invalid schema or a name already taken is left out with a warning.

## 6. Testing

Test without network: give `collect` a fake client returning recorded responses, as Veilleur's own tests do
(`tests/server/http_fakes.py`). Check that the schema is accepted (`veilleur.adapters.plugins.validated`) and that
the parameters of your examples pass it (`veilleur.core.domain.schema.validate`).

Filters (`veilleur.filters`) follow the same pattern: `name`, `schema`, `apply(item, params)` returning the item
(possibly transformed) or `None`, and optionally `select(items, params)` for a filter that needs every item at once.
