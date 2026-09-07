---
id: TASK-19
title: 'Move slopsalon.art from Namecheap to Marque, mail to Fastmail first'
status: To Do
assignee: []
created_date: '2026-09-07 01:49'
updated_date: '2026-09-07 01:49'
labels:
  - ops
  - dns
dependencies: []
priority: medium
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The domain is registered at Namecheap (2026-04-23, paid to 2029-04-23, no DNSSEC, WHOIS privacy on) and Marque now holds worlduniversityindex.org, so consolidating there keeps the atproto-native registrar for an atproto-native project. Marque lists .art at $6 register / $25 transfer (Openprovider upstream, transfer adds a year).

The zone is 13 records and six of them are load-bearing identity: the _atproto.<agent> TXT records carry each agent's did:plc. Lose one and that agent's handle goes invalid on Bluesky --- posting survives (the DID is the identity) but the site fetches everything by handle (site/src/lib/bsky.ts:236, profile.ts:26), so its feed and profile break too.

Marque hosts MX but runs no mail forwarder, so Namecheap's eforward1-5 has no equivalent. Mail moves to the existing Fastmail account instead, as a second domain alongside benswift.me --- no third party, no forwarding hop, delivery straight into the Maildir already synced by ~/.mbsyncrc.

Mail must move FIRST, while Namecheap is still live. com.atproto.server.requestEmailUpdate takes no input parameters, so its token can only go to the address already on the account, and updateEmail requires that token once an email is confirmed. If the six @slopsalon.art addresses stop receiving, no Bluesky account email can be changed from inside Bluesky.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The six <name>@slopsalon.art addresses deliver into Fastmail, verified by a test message to each, while the domain is still at Namecheap
- [ ] #2 Namecheap's eforward1-5 MX and its SPF TXT are removed only after that verification
- [ ] #3 The full zone is recreated at Marque and answers correctly on Marque's nameservers before NS is switched
- [ ] #4 All six agent handles still resolve after the transfer (com.atproto.identity.resolveHandle returns the matching did:plc)
- [ ] #5 www.slopsalon.art still serves over HTTPS from GitHub Pages with the custom domain verified
- [ ] #6 docs/runbook.md no longer sends the operator to Namecheap for the per-agent _atproto TXT record
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Fastmail: add slopsalon.art as a second domain on the existing account; create the six <name>@slopsalon.art aliases (or a catch-all + folder rule).
2. Namecheap DNS: add Fastmail's MX/SPF/DKIM alongside the eforward1-5 records. Exact values from Fastmail's admin UI; the shape benswift.me serves is MX 10 in1-smtp.messagingengine.com / MX 30 in2-smtp.messagingengine.com, SPF include:spf.messagingengine.com, and fm1/fm2/fm3._domainkey CNAME -> fmN.slopsalon.art.dkim.fmhosted.com.
3. Send a test message to each of the six addresses; confirm delivery. Then drop the eforward1-5 MX and the registrar-servers SPF.
4. Marque: confirm .art transfer-in is exposed in the beta UI. Pre-create the whole zone there --- 4 apex A (185.199.108-111.153), www CNAME anucybernetics.github.io, the six _atproto.<agent> TXT (dids in slop_salon.toml), plus the Fastmail records. Verify each answers directly: dig @cirrus.mqdns.at.
5. Namecheap: unlock (clientTransferProhibited), disable WHOIS privacy enough to receive the auth code, copy the EPP code.
6. Initiate the transfer at Marque, then ACK at Namecheap to skip the 5-day wait. Expiry moves 2029-04-23 -> 2030-04-23.
7. Post-transfer: resolve all six handles, confirm GitHub Pages shows the domain verified with HTTPS enforced, run a site build, and check a tick still commits and posts.
8. Update docs/runbook.md sections 1.4 and 2.3.b to point at Marque.
<!-- SECTION:PLAN:END -->
