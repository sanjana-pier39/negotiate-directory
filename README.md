# negotiate-directory

The public directory of [negotiate.v1](https://github.com/sanjana-pier39/pier39-skills/blob/main/PROTOCOL.md)-compliant storefronts. AI shopper agents (via [`negotiate-mcp`](https://github.com/sanjana-pier39/negotiate-mcp) or any other client) query this list to discover stores they can negotiate at.

## What's here

[`registry.json`](./registry.json) is a single JSON file listing every known store that implements the negotiate.v1 protocol. The MCP connector fetches this URL via its `find_stores` tool whenever a shopper asks "find me a store that sells X."

## Add your store

If you've deployed a [pier39-merchant-server](https://github.com/sanjana-pier39/pier39-merchant-server) (or any other negotiate.v1-compliant backend) and want to be discoverable by AI shoppers:

1. Confirm your `/negotiate.json` is reachable and returns `"negotiate_protocol": "negotiate.v1"`:

   ```bash
   curl -s https://yourstore.com/negotiate.json | python3 -m json.tool | head -3
   ```

2. Fork this repo, edit `registry.json`, add an entry alphabetically by `name`:

   ```json
   {
     "name": "Your Store Name",
     "domain": "yourstore.com",
     "tagline": "One-line description.",
     "city": "Your City, ST",
     "categories": ["appliances", "books", ...],
     "products_count": 12,
     "sample_products": [
       "Product A",
       "Product B",
       "Product C"
     ],
     "added": "YYYY-MM-DD"
   }
   ```

3. Open a PR. We'll verify the `/negotiate.json` endpoint resolves and merge.

Once merged, AI shoppers using `negotiate-mcp` will find you within ~5 minutes (the MCP caches the directory for 5 minutes per process).

## Schema

```jsonc
{
  "version": "1.0",                              // schema version
  "updated": "2026-05-03",                       // last directory update
  "stores": [
    {
      "name": "Required, human-readable",
      "domain": "Required, the domain (no scheme, no path)",
      "tagline": "Required, < 80 chars",
      "city": "Optional",
      "categories": ["Required", "list"],         // 1-6 lowercase tags
      "products_count": 4,                        // Required, integer
      "sample_products": ["a", "few"],            // 3-6 representative names
      "added": "YYYY-MM-DD",                      // Required, ISO date
      "verified": true                            // Optional, set by maintainers
    }
  ]
}
```

## Categories

We keep these freeform but try to converge on standard tags so search works well across stores:

- **`appliances`** — small/large home appliances
- **`electronics`** — consumer electronics
- **`furniture`** — chairs, desks, home furniture
- **`fashion`** — clothing, shoes, accessories
- **`fitness`** — gym equipment, sports gear
- **`books`** — books, ebooks, audiobooks
- **`home`** — household goods generally
- **`office`** — office supplies, work-from-home gear
- **`travel`** — luggage, travel accessories
- **`automotive`** — car parts, accessories

Plus brand tags like `dyson`, `apple`, `herman-miller` for stores specializing in one brand.

## How AI shoppers use this

When a shopper asks Claude/ChatGPT/etc. "find me a Dyson vacuum I can negotiate for," the agent calls:

```
find_stores(query="dyson vacuum")
```

The tool returns matching stores. The agent picks one, calls `start_negotiation(domain, product_id)`, and the haggling begins.

## Verified stores

Stores marked `"verified": true` have been manually confirmed by directory maintainers:

- The `/negotiate.json` is live and well-formed
- The chat API actually responds
- The store isn't a phishing/scam destination
- The store's pricing is consistent with what shoppers see on site

We can't verify quality of negotiations, store reputation, or product authenticity — that's the shopper's responsibility. Verification is just "the protocol works as advertised."

## License

The `registry.json` content (the directory data itself) is CC0 — public domain. The repo's tooling and docs are MIT.
