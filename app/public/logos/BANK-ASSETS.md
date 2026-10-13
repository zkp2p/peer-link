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

Mercury's [`mercury.svg`](mercury.svg) was retrieved unchanged on October 9,
2026 from its official [website icon](https://mercury.com/icon.svg), also recorded
in [LOGOS.md](../../LOGOS.md). It retains the official path geometry, default fill
and dark-mode stylesheet. The local file exactly matches the downloaded bytes.
SHA-256: `2ed16fb63cf3b3035130b87e94ab07f6b507a6499c17968bc1a9f07090a9a9ef`.
This source record does not establish a live Mercury API acquisition or an endorsed
integration.

Mercury artwork is rendered as a decorative image beside the bank name in a
labelled link. Its standalone title lint rule is disabled only for this unchanged
third-party asset; the card supplies the accessible name.

These assets were retrieved unchanged on October 11, 2026 from icon links, header images or share images in the banks' official public homepages:

| Local file | Official homepage | Asset URL |
| --- | --- | --- |
| `kb-kookmin.png` | https://kbfg.com/ | https://kbfg.com/eng/images/common/icon_favicon_192_192.png |
| `rakuten-bank.png` | https://www.rakuten-bank.co.jp/ | https://www.rakuten-bank.co.jp/shared/images/icons/rb-icon512.png |
| `kasikornbank.png` | https://www.kasikornbank.com/en | https://www.kasikornbank.com/_catalogs/masterpage/KWeb2016/assets/img/apple-touch-icon-152x152.png |
| `dbs.svg` | https://www.dbs.com.sg/index/default.page | https://www.dbs.com.sg/iwov-resources/flp/images/dbs_logo.svg |
| `hsbc-hk.png` | https://www.hsbc.com.hk/ | https://www.hsbc.com.hk/etc.clientlibs/dpws/clientlibs-public/clientlib-site/resources/favicons/apple-touch-icon.png |
| `cmb.png` | https://m.cmbchina.com/ | https://s3gw.cmbimg.cn/srd-a2549394cd7491f-1255000101/touch-icon-iphone4.png |
| `capital-one.webp` | https://www.capitalone.co.uk/ | https://www.capitalone.co.uk/cloud_assets/webp/capital-one-logo.webp |
| `citi.png` | https://www.citi.com/ | https://www.citi.com/cbol-hp-static-assets/assets/favicon.ico |
| `pko-bp.png` | https://www.pkobp.pl/ | https://www.pkobp.pl/static/redesign/_front/_img/_layout/favicon_new.png |

KB Kookmin Bank's mark comes from KB Financial Group, the bank's parent and owner of the KB brand, because kbstar.com publishes only an icon overlaid with a "Web" ribbon. Rakuten Bank's icon is listed in the web app manifest linked from its homepage (`/manifest.webmanifest`). China Merchants Bank's icon is the apple-touch-icon linked from its official mobile homepage and served from the bank's `cmbimg.cn` asset host. DBS's file is the header logo on its Singapore homepage. PKO Bank Polski's file is the square favicon linked from its homepage. Capital One's file is the share image (`og:image`) on its official UK homepage, because the US homepage publishes only a cropped swoosh touch icon.

Citi serves PNG bytes at its `.ico` favicon URL; the local `.png` extension matches the unchanged response format. Capital One serves WebP bytes with a generic `binary/octet-stream` content type; the local `.webp` extension matches the unchanged response format.

SHA-256 of the unchanged files:

- `kb-kookmin.png`: `7aebccbf01ffbae2d4cb0fef86b5535ae6efea68e62665f3ad9bf523995979e8`
- `rakuten-bank.png`: `4953f308f4cf610e226c650cb6890225ab369384762cedc71071df7467c20b17`
- `kasikornbank.png`: `45b053f80935218b129b76d975e6682812df9357dfce75b61f9b48eb26f20133`
- `dbs.svg`: `17db6c6208625a56acd0380b00747a5b6db8a79f2adbe272844f0cff6ba923c7`
- `hsbc-hk.png`: `d258f7e2ad662d73ec5c4a2c9e0b7d514b353df351bb8880b9b4731682788766`
- `cmb.png`: `5db6ec2e108ea51a56337c898ce4864417275361ecc2f16ba4f2de5832ec047f`
- `capital-one.webp`: `a795c89c267576676498a35348b2a3f84d73d80f795b4e616b22d2a794ef9eca`
- `citi.png`: `2f6d73a312361b30f573d8f97bf9b345f2316c3d8b40723592b3145e360f8c32`
- `pko-bp.png`: `ffffc25af992fc247fd7f70edaf64ed1a45438fe30f9c4db7d67661ba7d30152`

## HDFC Bank — October 13, 2026

`hdfc-bank.svg` is the unchanged HDFC NetBanking logo served by the bank itself,
observed as its logo element’s background image.

Source: https://now.hdfc.bank.in/retail-app/assets/common-assets-bank/images/hdfc-bank-logo-now.svg

SHA-256: `7352799547d8df77bbde7055bd712ce54e52fb6f057400d463091be89ad6ef3a`.
