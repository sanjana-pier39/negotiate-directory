# Contributing to negotiate-directory

Want your store listed? Submit a PR. Takes ~5 minutes.

## Submission checklist

Before you open a PR, verify your store is actually negotiate.v1-compliant:

```bash
# 1. Discovery file resolves
curl -s https://yourstore.com/negotiate.json | python3 -m json.tool | head -3
# expect: "negotiate_protocol": "negotiate.v1"

# 2. Catalog endpoint works
curl -s https://yourstore.com/api/store/catalog | python3 -m json.tool | head -10

# 3. Chat endpoint actually starts a session
curl -s "https://yourstore.com/api/store/chat/start?product_id=<one-of-your-product-ids>" \
  | python3 -m json.tool | head -5
# expect: a session_id and a greeting from your merchant agent
```

If all three commands succeed, you're ready to submit.

## Open a PR

1. **Fork** `negotiate-directory` on GitHub.
2. **Edit `registry.json`** in your fork. Add your store as a new entry inside the `stores` array, in alphabetical order by `name`. Use this template:

   ```json
   {
     "name": "Your Store Name",
     "domain": "yourstore.com",
     "tagline": "One-line marketing description (under 80 chars).",
     "city": "City, ST",
     "categories": ["main-category", "sub-category"],
     "products_count": 12,
     "sample_products": [
       "Most popular product",
       "Second product",
       "Third product"
     ],
     "added": "YYYY-MM-DD"
   }
   ```

3. **Update `version` and `updated` fields** at the top of registry.json:
   - Bump `version` only on schema changes (not for directory additions)
   - Set `updated` to today's date

4. **PR title**: `Add <store name>`. Body: link to your `/negotiate.json` so maintainers can verify.

## Field guidelines

- **`name`**: how it appears in search results. Keep it real — "Atlas Premium Appliance," not "**🔥🔥 BEST DEALS 🔥🔥**".
- **`domain`**: just the hostname, no scheme, no path. `yourstore.com`, not `https://yourstore.com/`.
- **`tagline`**: 80 chars max. Should help a shopper decide whether to negotiate at your store vs. another.
- **`categories`**: 1-6 lowercase, hyphen-separated tags. See README.md for the standard set.
- **`products_count`**: actual count. Updated periodically; doesn't have to be exact.
- **`sample_products`**: 3-6 representative product names. These help search work well — a shopper searching "airwrap" finds Atlas because "Dyson Airwrap Complete Long" is in the sample list.

## Removal

To remove your store, open a PR deleting your entry from the array. We'll merge without questions.

We may also remove entries proactively if:
- The `/negotiate.json` endpoint stops responding for 7+ days
- The store reports security issues or shopper complaints
- The store deceives shoppers (fake products, fake pricing, etc.)

## Verification

Maintainers may set `"verified": true` on entries after manually testing the protocol implementation. Verification means: the protocol works correctly. It does NOT mean: we've vetted the store's reputation, products, or business practices. Caveat emptor still applies.

## Maintainer notes

To verify a submission:

```bash
# Quick smoke test
DOMAIN=yourstore.com
curl -s -m 10 "https://$DOMAIN/negotiate.json" | python3 -c "import sys, json; d=json.load(sys.stdin); assert d['negotiate_protocol']=='negotiate.v1'; print('OK', d['store']['name'])"
```

If that prints `OK <store name>`, the discovery layer works. Spot-check the chat endpoint manually too.

After merging, the directory is automatically picked up by the `negotiate-mcp` connector within 5 minutes (cache TTL).
