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

## Next-release banks — October 13, 2026

The China, Singapore, Korea and VietinBank logos were retrieved for the planned
campaigns on October 5–7, 2026. Standard Chartered, Trust Bank and VietinBank
publish a square icon on their own homepages (VietinBank serves PNG bytes as
`image/x-icon`). ICBC, CCB, ABC, Bank of China, OCBC and UOB serve only 16 to
48 px favicons, so their icons come from each bank's own Apple App Store
listing (seller verified through the App Store lookup API), served by Apple at
128 × 128. Most Korean bank apps use app-brand icons, so Shinhan Bank and Hana
Bank use their financial groups' symbols, which match the banks' own favicons.
NongHyup's symbol comes from its CI download, which is a GIF, converted
losslessly to a pixel-identical PNG. The others are stored unchanged:

| Local file | Official source | Asset URL |
| --- | --- | --- |
| `icbc.png` | [ICBC App Store listing](https://apps.apple.com/cn/app/id423514795), seller Industrial and Commercial Bank of China | https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/c9/6e/49/c96e4981-d3a9-f9d0-cff5-4d36135fdc3b/AppIcon-0-0-1x_U007ephone-0-1-0-0-sRGB-85-220.png/128x128bb.png |
| `ccb.png` | [CCB App Store listing](https://apps.apple.com/cn/app/id391965015), seller China Construction Bank | https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/40/31/4c/40314c85-48eb-3376-cd85-2a5cd85c2fae/AppIcon-0-0-1x_U007ephone-0-1-0-sRGB-85-220.png/128x128bb.png |
| `abc.png` | [ABC App Store listing](https://apps.apple.com/cn/app/id515651240), seller Agricultural Bank of China Limited | https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/14/1f/68/141f68e4-112d-40de-0e7a-d1c188d0ce41/AppIcon-Release-1x_U007emarketing-0-6-0-sRGB-85-220-0.png/128x128bb.png |
| `boc.png` | [BOC App Store listing](https://apps.apple.com/cn/app/id399608199), seller Bank of China Limited | https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/a9/81/13/a981130c-a9d3-1ed8-1828-95d986c0e116/AppIcon-1x_U007emarketing-0-8-0-sRGB-85-220-0.png/128x128bb.png |
| `ocbc.png` | [OCBC Singapore App Store listing](https://apps.apple.com/sg/app/id292506828), seller Oversea-Chinese Banking Corporation Limited | https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/6c/d8/65/6cd8655f-2fee-8d61-7bd7-62b05fef11b1/AppIcon-0-0-1x_U007ephone-0-11-0-sRGB-85-220.png/128x128bb.png |
| `uob.png` | [UOB TMRW App Store listing](https://apps.apple.com/sg/app/id1049286296), seller United Overseas Bank Limited | https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/c9/03/b3/c903b35f-2ee9-9282-87fc-3d4941ae5475/AppIcon-0-0-1x_U007emarketing-0-7-0-85-220.png/128x128bb.png |
| `standard-chartered.png` | https://www.sc.com/sg/ | https://av.sc.com/sg/content/images/content/images/cropped-cropped-favicon-cropped-512x512-1-200x200.png |
| `trust.png` | https://trustbank.sg/ | https://trustbank.sg/images/trust_favicon.png |
| `shinhan.png` | https://www.shinhangroup.com/kr/main (Shinhan Financial Group) | https://www.shinhangroup.com/resources/publish/kr/images/common/favicon_192_192.png |
| `hana.png` | https://www.hanafn.com/ (Hana Financial Group) | https://www.hanafn.com/assets/img/favicon/apple-touch-icon.png |
| `woori.png` | https://spot.wooribank.com/pot/Dream?withyou=BPBKI0056 | https://simg.wooribank.com/img/section/nbp/icons/apple-touch-icon.png |
| `nonghyup.png` | https://www.nonghyup.com/introduce/ci/symbol.do | `cyber_symbol.gif` in https://www.nonghyup.com/cmm/file/resourceDownLoad.do?filepath=ai02.zip |
| `vietinbank.png` | https://www.vietinbank.vn/ | https://vietinbank.vn/assets/4ed6cd47-8286-40df-b66f-4ccb71e09b4b |

These assets were retrieved unchanged on October 13, 2026. PrivatBank, MoMo,
Airtm and Brubank link them as icons from their official homepages (Brubank's is
hosted on its website builder's CDN); Starling Bank declares its logo in its
homepage's structured data. Skrill's own site icons are blurry at card size, so
its icon comes from its own App Store listing (seller verified through the App
Store lookup API):

| Local file | Official source | Asset URL |
| --- | --- | --- |
| `privatbank.png` | https://privatbank.ua/ | https://privatbank.ua/sites/pb/img/favicon/favicon-192x192.png |
| `momo.png` | https://www.momo.vn/ | https://homepage.momocdn.net/img/momo-amazone-s3-api-241023152559-638652939595693626.png |
| `skrill.png` | [Skrill App Store listing](https://apps.apple.com/us/app/skrill-pay-transfer-money/id718248239), seller Skrill Ltd | https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/e6/0b/be/e60bbea5-3f31-5940-7701-6b4339b90b57/AppIcon-0-0-1x_U007epad-0-1-P3-85-220.png/128x128bb.png |
| `airtm.png` | https://www.airtm.com/en/ | https://www.airtm.com/wp-content/uploads/2022/09/cropped-favicon-white-1-192x192.png |
| `starling.png` | https://www.starlingbank.com/ | https://www.starlingbank.com/media-library/sb-logo.png |
| `brubank.png` | https://www.brubank.com/ | https://cdn.prod.website-files.com/63091bbd808ef433808b70cd/633336b1beaf6e8c27e2da15_Favicon%20(2).png |

SHA-256 of the stored files:

- `icbc.png`: `eb583ecdf825b602c748d3e62f0f0368b1a800841ddb2a8f2847b8777e1ae0f1`
- `ccb.png`: `0daba6bce6db30ba191201a3846517eb6e6bbedb29eccd7d2cc42b2a5c6417c0`
- `abc.png`: `3279a7b6727eb13efbcc159adaf681bfa5fa4f862ae092f253d5da9b0030c632`
- `boc.png`: `d4d502000df40868624ba0f0558d5caebd17a2e43b0db4dee88f25ee325cefb1`
- `ocbc.png`: `2f43e0cf7a681cf6d44d037afbb37f07634b0814f2df34ce704b0b86854ca285`
- `uob.png`: `f33beaa6876cec1c53420f541111b05062fa8b5eae22150a28abe7741337f168`
- `standard-chartered.png`: `e6f38c51972eba5604ed7ac633492bcdcb37e76c2b01fb71dfb187a7489f09b3`
- `trust.png`: `79723c03fbc5da0de580a8dfb51ff3659e65d0e4961c068091a191f431d58f4e`
- `shinhan.png`: `7b8df713a02858706392092ab80e2363b8ba85f975119c7e0f06b4b06843dd8d`
- `hana.png`: `f81823bbb871d8f81bed135de7f0568a825dbdcf4583f5a989ae3a5df48e9619`
- `woori.png`: `77407e849207e2b00bd507d4d2221e33376aa17d23f66168725540f2b41ca54a`
- `nonghyup.png`: `33170aaae190f9be8c2d31492c6f12be861ccbf8ebf436a516a322d482dad57d`
- `vietinbank.png`: `77e8526ff9bab977948142eba7854017edd28a80deae14accdc667d11c51174e`
- `privatbank.png`: `9f677469fe5006cce4e02db76e8edb6198ea12dd7c8f0974360b6befe5bb87a2`
- `momo.png`: `12d1f736345a09acdf1fdef665d8809ced4ebf9fdfc9cc108df20db67cf11d39`
- `skrill.png`: `ec5ddc79868f3d4b2bade4bfaa884d832cdf491c0e4b4fe69a8561eb955e6f31`
- `airtm.png`: `832bc56bb1148a9da1f355661fafa977ae0380d89c3ee57b4af0e97ee100c8a8`
- `starling.png`: `147bb3ca71471cfec37f95699aa2211c82b1925ba5780fa2675ff6773f69be82`
- `brubank.png`: `5b99b6587549abf4cd1265ed4d44431997ae5f04f06b137fecd537024f7f3a32`

## Vietnamese banks — October 14, 2026

These assets were retrieved unchanged on October 14, 2026. ACB and Sacombank
link them as icons from their official homepages. Agribank's homepage serves
only a 16 and 32 px icon file, so its symbol is the logo served by Agribank
Retail, the bank's personal internet banking linked from that homepage.
Techcombank, MB, VPBank and TPBank serve only 16 to 48 px favicons, so their
icons come from each bank's own Apple App Store listing (seller verified
through the App Store lookup API), served by Apple at 128 × 128:

| Local file | Official source | Asset URL |
| --- | --- | --- |
| `techcombank.png` | [Techcombank Mobile App Store listing](https://apps.apple.com/vn/app/id1548623362), seller Vietnam Technological and Commercial Joint Stock Bank | https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/26/68/33/2668331a-bf08-af0a-b540-77b209f72bcc/AppIcon-0-0-1x_U007ephone-0-1-85-220.png/128x128bb.png |
| `mb-bank.png` | [MB Bank App Store listing](https://apps.apple.com/vn/app/id1205807363), seller Military Commercial Joint Stock Bank | https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/ea/3a/6c/ea3a6c74-6211-f357-7289-4a9820139ba4/AppIcon-0-0-1x_U007emarketing-0-8-0-85-220.png/128x128bb.png |
| `acb.webp` | https://acb.com.vn/ | https://acb.com.vn/favicon.webp |
| `vpbank.png` | [VPBank NEO App Store listing](https://apps.apple.com/vn/app/id1209349510), seller Vietnam Prosperity Joint Stock Commercial Bank | https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/ae/3a/ad/ae3aad77-d781-86c0-4762-9f3200c19dc8/AppIcon-0-0-1x_U007ephone-0-11-0-sRGB-85-220.jpeg/128x128bb.png |
| `agribank.png` | https://www.agribank.com.vn/ (Agribank Retail, https://ebanking.agribank.com.vn/retail/) | https://ebanking.agribank.com.vn/retail/assets/image/logo_agribank_1.png |
| `sacombank.png` | https://www.sacombank.com.vn/ | https://www.sacombank.com.vn/android-chrome-512x512.png |
| `tpbank.png` | [TPBank Mobile App Store listing](https://apps.apple.com/vn/app/id450464147), seller TienPhong Bank | https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/4b/3a/6d/4b3a6d80-d391-fc9d-088b-d6779ab67e32/AppIcon-0-0-1x_U007emarketing-0-8-0-sRGB-85-220.png/128x128bb.png |

SHA-256 of the stored files:

- `techcombank.png`: `4d91511042055860967bc64982faa3a8bb28c484a7523eddaa188ebf869be4aa`
- `mb-bank.png`: `78373c1f38bc2a9957917df0664f9e133c6189ae5491688cd6c6344b1542ee77`
- `acb.webp`: `e62bf42b1edc53e7d0a78b0b18de1d586ea286c786557a15ad8b29d19203d58b`
- `vpbank.png`: `77e5adec59ac4f0ab61b7f6cf13d822091f0f0454bb64080bf5d6452b31d76cb`
- `agribank.png`: `23d161150df3e2aaa88bcf6c819615f3d57abd282b741681eb5020f1f93983c8`
- `sacombank.png`: `95330a5ce1376b149be1e86fa9503dfb8c040bf491b9621bfcdcef41df6feed9`
- `tpbank.png`: `aa4d15f151627f1f0dcc1f890de4080251ff80a1e8a1195adcd75f23f5aebd35`

## Canadian banks — October 16, 2026

These assets were retrieved unchanged on October 16, 2026. CIBC links its icon
as the apple-touch-icon from its official homepage. RBC Royal Bank, TD and
Scotiabank publish only ICO favicons and non-square logos or share images on
their homepages, and BMO's touch icon is a 96 px wordmark, so their icons come
from each bank's own Apple App Store listing (seller verified through the App
Store lookup API), served by Apple at 128 × 128. TD's file replaces the earlier
`td.png`, which predated this register and had no recorded source:

| Local file | Official source | Asset URL |
| --- | --- | --- |
| `rbc.png` | [RBC Mobile App Store listing](https://apps.apple.com/ca/app/id407597290), seller Royal Bank of Canada | https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/78/6c/f3/786cf315-f19e-547f-3de1-f2c93ad8a245/RBCMobile-0-0-1x_U007epad-0-1-0-85-220.png/128x128bb.png |
| `td.png` | [TD Canada App Store listing](https://apps.apple.com/ca/app/id358790776), seller Toronto Dominion Bank Financial Group | https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/89/53/01/8953016a-aef7-0f1d-04b0-b0aa2781294a/AppIcon-0-0-1x_U007epad-0-0-0-1-0-0-sRGB-85-220.png/128x128bb.png |
| `scotiabank.png` | [Scotiabank App Store listing](https://apps.apple.com/ca/app/id341151570), seller The Bank of Nova Scotia | https://is1-ssl.mzstatic.com/image/thumb/Purple221/v4/e3/51/ad/e351adbe-f904-c844-1c22-52e73cf1d236/AppIcon-0-0-1x_U007epad-0-9-0-85-220.png/128x128bb.png |
| `bmo.png` | [BMO Mobile Banking App Store listing](https://apps.apple.com/ca/app/id429080319), seller Bank of Montreal | https://is1-ssl.mzstatic.com/image/thumb/Purple211/v4/54/f4/16/54f416f5-4ec2-5567-808a-5d21ab504d62/AppIcon-0-0-1x_U007epad-0-1-0-85-220.png/128x128bb.png |
| `cibc.png` | https://www.cibc.com/ | https://www.cibc.com/content/dam/global-assets/logos/partner-logos/apple/apple-touch-icon.png |

SHA-256 of the stored files:

- `rbc.png`: `66e64b486ddeb072504d727aa6aea0573bb6d46e481017c2e26ba355d89e1c72`
- `td.png`: `e1fd2a32c09de762eaa684e35342a5d55bbe067b06e70c9df5e0d2dcd0e780f0`
- `scotiabank.png`: `e04e06deca086e783bdd4c50a49e8861302defc440184e2286426bcab7225dca`
- `bmo.png`: `00e9d81d1834e21c69f5c9afca832632342fe573e96955f52480aad88af49fc4`
- `cibc.png`: `e8e7d33bf324bf32b7fa045470ff4e7ac2d6fbd78b9f80b674f5fb10358291a1`
