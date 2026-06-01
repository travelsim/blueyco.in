## Blueyco.in — High-Fidelity Prototype

**The home for Bluey coin collectors.**

This is the clean, pure-static Vercel repository powering the public experience (blueyco.in) and the full app prototype (value / collect / buy flows).

### What’s in this prototype (current state)
- Bright, cartoon title-card energy with Hello Headline (Comic Neue proxy) + the official Bluey palette.
- Public explorer (blueyco.in) with live-ish eBay sold data + strong **crossover** CTAs: “Save to collection” instantly triggers signup then lands you in your rich personal collection.
- Realistic mock accounts via localStorage (name, email, persistent).
- Rich **My Collection** + **Wishlist**: numbered edition entry, condition, purchase price/date, notes. Portfolio value calculated live.
- Proper **Deal Hunter**: unified search + filters across the coin catalog (eBay averages + mock retailer prices), price alerts that persist.
- **Simple premium framing product page** (the main revenue driver): beautiful focused experience with live frame preview, timber colour choices, glass upgrade, engraved nameplate option, dynamic pricing, add-to-cart, and a mini-cart that funnels to the future buy.blueyco.in subdomain checkout.
- Bluey voice throughout (“ripper”, “legend”, “mob”, “Bandit’s honour”, “G’day”).
- Subdomain hints everywhere for the planned IA (public / value / collect / buy / blog).
- Content seeds: RAM ballots, ABC episodes, behind-the-scenes creator analysis teasers.
- Zero backend. Everything client-side + the existing JSON data files. Ready for the real thing.

### Subdomain vision (from day one)
- blueyco.in — public marketing + explorer
- value.blueyco.in — personal portfolio dashboard
- collect.blueyco.in — My Collection + Wishlist
- buy.blueyco.in — Deal Hunter + premium framing shop (the real revenue engine)
- blog.blueyco.in — deep content, ballots, podcasts, creator analysis

The sister repo `blueyco.in` (dynamic Python/scraping) remains 100% untouched per the plan.

### Run / Deploy
Pure static. `index.html` + `ebay_cache.json` + `retailer_prices.json` + `vercel.json`. Deployed on Vercel.

Prototype only. No real money, no real accounts. Built with the final long-term product in mind.

Made for the mob.