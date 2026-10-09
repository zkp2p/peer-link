# Bank logo sources

Use locally stored, unchanged bank artwork to identify directory entries. Every new bank entry must include a logo and a source record here. Listing a bank or its logo does not establish an implemented integration, bank endorsement or approval for Peer payments.

These assets were retrieved unchanged on October 2, 2026 from icon links in the banks' official public homepages:

| Local file | Official homepage | Asset URL |
| --- | --- | --- |
| `chase.jpg` | https://www.chase.com/ | https://www.chase.com/etc/designs/chase-ux/favicon-152.png |
| `bank-of-america.png` | https://www.bankofamerica.com/ | https://www.bankofamerica.com/homepage/spa-assets/images/assets-images-global-favicon-android-chrome-192x192-CSXafb7d716.png |
| `wells-fargo.png` | https://www.wellsfargo.com/ | https://www17.wellsfargomedia.com/assets/images/icons/icon-hires_192x192.png |

Other bank logos predate this source register and are preserved from the existing repository; this file does not claim to have reverified their provenance. Peer wordmarks are documented separately in [PEER-ASSETS.md](PEER-ASSETS.md).

Chase serves JPEG bytes at its `.png` icon URL; the local `.jpg` extension matches the unchanged response format.

Wise artwork was retrieved unchanged on October 9, 2026 from its official [newsroom logo kit](https://newsroom.wise.com/en-NAM/assets/228784/): [`wise.png`](wise.png), served as the page logo at https://d21buns5ku92am.cloudfront.net/69646/logo/retina-1677657632.png. SHA-256: `9ab5f0b5bae5c06911ab8752f0c4d3f51831146fb752147a622a95e09478af8b`.

Mercury's existing [`mercury.svg`](mercury.svg) comes from its official
[website icon](https://mercury.com/icon.svg), also recorded in
[LOGOS.md](../../LOGOS.md). Reverified October 9, 2026: the official SVG and local
asset have identical viewbox, path geometry and default fill. The preserved local
copy adds a `Mercury` title and omits the official dark-mode stylesheet, so it is
not byte-identical to the current download. Local SHA-256:
`49b110e558441a46b463a82117675640550c4f650fe27d67d0a340bb82a6811d`.
This source record does not establish a live Mercury API acquisition or an endorsed
integration.
