# JLCPCB web API — reference

Everything here was verified against a live account on **2026-07-28** (37 order
batches, 35 invoices, 16 parts orders, 215 purchase lots). Field names and
behaviour come from real payloads, not documentation — **JLCPCB publishes none
for this API**.

Implemented in `api/app/services/jlc_web.py`. Read that file's docstring for the
client contract; this document is the protocol reference.

> **Status: undocumented, unversioned, and plausibly against JLCPCB's ToS.** It
> can change without notice. Every response must be treated as an untrusted
> shape, the raw payload kept, and a shape change must fail LOUDLY rather than
> silently produce a wrong number. See *Traps* — several of these were caught
> only because a conservation check refused the write.

---

## 1. Why this exists at all

The official JOP-signed partner API (`open.jlcpcb.com`) **cannot serve any of
this**. Its complete published surface is 20 endpoints — 4 `component/`, 9
`pcb/`, 7 `tdp/`. There is no PCBA surface: every "SMT" token in the official
docs means SMD **stencil**, and `pcb/calculate` accepts `orderType` 1/2/3 (PCB,
PCB+stencil, stencil) only, so an assembly order cannot even be *placed*
officially. There is also no stock-movement endpoint at any permission level —
`getPrivateComponentLibrary` returns point-in-time balances, never a ledger.

Confirmed against three independent reconstructions of the official docs. Do not
re-probe this; use the web API.

---

## 2. Authentication

Base URL: `https://jlcpcb.com/api` + a service prefix.

Three legs, **all required on every call**:

| Leg | Value |
|---|---|
| Cookies | From a real browser login. `JLCPCB_SESSION_ID` is **httpOnly**, so `document.cookie` cannot produce it — take the whole `Cookie` header from DevTools → Network → Copy as cURL. |
| `x-xsrf-token` | The **URL-decoded** value of the `XSRF-TOKEN` cookie. |
| `secretkey` | See below. |

### The `secretkey` header

Two forms work:

1. **Minted** — `POST /overseas-core-platform/secret/update` with
   `{"keyId": "<random uuid4 hex>"}` returns `data.keyId`, valid ~30 minutes.
2. **Constant** — the browser was observed sending
   `secretkey: 64656661756c744b65794964`, which is hex for the ASCII string
   **`defaultKeyId`**. So the header is validated for presence and format far
   more than for content.

The client mints (form 1) because it is the documented-by-behaviour path, but
form 2 explains why a stale key is a soft failure rather than a hard one.

### Failure modes — do not conflate these

| Signal | Meaning | Action |
|---|---|---|
| HTTP **460** | Session cookies are dead. | A human must log in again. Surface it. |
| `success:false`, `code` 401/403 | Only the secret key aged out. | Re-mint and retry once (automatic). |
| `code: 500`, "System error" | Usually wrong/missing parameters. | Not a session problem. |

### XSRF bootstrap quirk

The `XSRF-TOKEN` cookie carries `Max-Age=1800`, so a pasted session very often
arrives without a live one. It can be re-minted, but **only the
`overseas-pcb-order` service runs the CSRF filter that issues it** — the site
root, `overseas-core-platform` and the SMT service all answer 200 without one.

The client therefore GETs a deliberately non-existent path under that prefix
(`/api/overseas-pcb-order/v1/csrf-bootstrap`): the filter runs *before* routing,
so the 404 still sets the cookie, making the bootstrap side-effect free. This is
the standard double-submit-cookie pattern, so a token the server just issued is
as valid as the one the browser held.

### Service prefixes

```
/overseas-pcb-order                        billing, invoice PDF, CSRF filter
/overseas-core-platform                    order centre, invoices, secret key
/overseas-smt-component-order-platform     parts orders, private library
```

---

## 3. Endpoints

### 3.1 Order batches

```
POST /overseas-core-platform/orderCenter/selectPersonBatch
{businessType, orderStatisticsType, searchKey, batchStatus, fromType: 3,
 orderBusinessSystemType: "0", timeStamp: <ms>, currentPage, pageRows}
```

`batchStatus`: `shipped | inProduction | cancelled | waitPay | waitReview` (or
empty for all). Returns `data.list[]`: `batchNum`, `batchCreateTime`,
`batchStatus`, `payUnionSecondVO{productFee, carriageFee, tariffFee, totalFee,
orderInfoVOList[]}`, `expressInfoVO`, `settleCurrencyInfoVO`.

**`payUnionSecondVO.totalFee` EXCLUDES prepaid components** — see §5.

### 3.2 Order detail — **the only source of panelisation**

```
POST /overseas-core-platform/orderCenter/selectPersonOrder
{"batchNum": "W...", "paySuccess": true}
```

Returns `data.unionOrderInfoVOList[]`, one entry per order in the batch:

```
orderCode, orderType            4 = SMT assembly, 0 = PCB fabrication
myOrdersRecord.detail.smtDetail
    smtOrderCode                SMT025101662104
    produceOrderCode            P29        <- the PCB order it was built from
    pasteNumber                 250        <- boards FABRICATED, PANELS when panelised
    allPatchNum                 250        <- boards ASSEMBLED, PANELS when panelised
    patchType                   all | no   <- "no": only part of the boards populated
    patchLocation, backToSingle
myOrdersRecord.detail.pcbDetail
    panelX, panelY              2, 2       <- the panelisation
    stencilCounts               250
```

**Devices = `allPatchNum × panelX × panelY` of the referenced PCB order.**

`allPatchNum` is what went through the line and equals the invoice's billed
`number` on all 46 assembly orders in the account (2026-09-24). `pasteNumber` is
the boards fabricated: on the 17 orders with `patchType="no"` it is larger — 75
fabricated / 60 assembled on `SMT026092263197`, 300 / 275, 50 / 45, 200 / 187.
JLC's BOM agrees with `allPatchNum` (a once-per-board part is placed 45 times on
the 50 / 45 order), so the gap is bare boards, not assembled spares.
Verified: P29 is 2×2 so `SMT025101662104` built 250 × 4 = **1000 devices**, while
P30 is 1×1 so `SMT025101662116` built **250**. Known for **44 of 44** assembly
orders in the account.

`panelX`/`panelY` is unavailable when the PCB order is not in the same batch — a
re-order assembles boards fabricated earlier. Treat that as *unknown*, never as 1.

A separate, older endpoint `selectPersonOrderDetail?batchNum=` returns a similar
tree but was NOT observed to carry `panelX`/`panelY`. Prefer `selectPersonOrder`.

### 3.3 Manufacturing invoice — **the consumption source**

```
POST /overseas-core-platform/orderCenter/invoiceOrder
{"batchNum": "W...", "orderPay": "yes"}
```

Header fields: `invoiceNo`, `invoiceDate` (**DD/MM/YYYY**), `batchNum`,
`productMoney`, `carriageMoney`, `tariffChargesMoney`, `tariffServiceMoney`,
`serviceCharges`, `discount`, `presaleMoney`, `subTotalMoney`, `totalMoney`,
`settleCurrencyInfoVO{settleCurrency, settleExchangeRate}`, `expressNo`,
billing/shipping addresses.

`invoiceListResponseList[]` — one row per ordered item:
`orderCode` (`SMT026070663866-Y88`, i.e. SMT order + board code), `orderType`
(display text), `specifications`, `orderFileName`, `number`, `unitMoney`,
`totalMoney`, `carriageMoney`, `tariffChargesMoney`, `presaleMoney`, `paiclMoney`.

`presaleDetailResultVOList[]` — **one row per component LOT consumed**:

| field | meaning |
|---|---|
| `smtOrderCode` | which assembly order consumed it |
| `componentCode` | LCSC code |
| `componentModel` | MPN |
| `componentNum` | quantity drawn **from this lot** |
| `settleGoodsPrice` / `componentMoney` | that lot's unit / extended value |
| `orderBatchNo` / `presaleOrderNo` / `presaleGoodsKeyId` | **which purchase lot** |
| `stockType`, `remainNumber`, `vatMoney`, `tariffMoney`, `operateMoney` | |

This list is the component → assembly-order → invoice join. It arrives as JSON
**`null`** (not absent, not `[]`) when nothing was drawn — see *Traps*.

### 3.3b SMT order detail — **who supplied each part, and JLC's own BOM**

```
GET  /overseas-pcb-order/v1/smtOrder/getSmtOrderDetail?smtOrderNum=<UUID>&_t=<ms>
POST /overseas-pcb-order/v1/smtOrder/querySmtComponent   {"smtOrderNum": "<UUID>"}
```

**`smtOrderNum` is a UUID, not the SMT order code.** It comes from
`selectPersonOrder` -> `myOrdersRecord.orderNum` (equal to `orderDetailNum`) on the
orderType-4 entry. Passing `SMT0260511...` returns `code 500`.

`getSmtOrderDetail` returns `smtBomResult[]` — JLC's OWN BOM for the order, which
is the only place that says **who supplied each part**:

| field | meaning |
|---|---|
| `componentSource` | **`preSale`** = drawn from YOUR consigned library; **`shop`** = JLC supplied it from their stock and charged you; **`preSaleAndShop`** = partly each |
| `unitPrice` / `extPrice` | what JLC charged. **0.0 for `preSale`** — already paid on the POB order |
| `componentNum` / `componentRealCount` | per PANEL / total — an independent check on the panel factor |
| `lossNumber` | attrition JLC actually incurred, per part |
| `componentLibraryType` | `base` / `expand` |
| `designator`, `footPrint`, `assemblyProcess`, `matchType` | placement detail |

Real distribution on SMT026051162772: 20 `preSale`, 1 `shop`
(TS3625A, 2002 pcs @ 0.0283 = $56.66), 1 `preSaleAndShop` (C7223, $0.61).

**This resolves the "phantom shortage" class of error.** A part JLC supplied from
their shop must NOT be drawn from the pool — it never entered it — yet a BOM
forecast will happily consume it, and the pool then reads a shortage of stock that
was never touched. `componentSource` is the authoritative signal; inferring it from
"drawn but not purchased" is guesswork and gets packaging wrong.

`serviceRecordVos[]` on the same response itemises the assembly fee
(`childItemNameEn`, `calMoney`) — the per-step breakdown for `cost_steps`.

`querySmtComponent` returns `{consignedList, previouslyList, smtOrderCode}`;
`previouslyList` duplicates the invoice's `presaleDetailResultVOList`, and
`consignedList` covers parts the customer physically shipped in (empty for this
account). It adds nothing over the invoice — prefer `getSmtOrderDetail`.

### 3.4 Parts orders — **settled purchase truth**

```
POST /overseas-smt-component-order-platform/v1/overseasSmtComponentOrder/presaleOrder/selectPresaleOrderList
{pageNum, pageSize, orderType: null, keyword: "", orderStatus: ""}
```

`orderStatus`: `paySuccess | waitPay | cancelled | completed | ""`.

Returns `data.list[]` keyed by `orderBatchNo` (POB…), each with **four parallel
sub-order lists that must ALL be read**: `stockList`, `buyList`,
`overseasShopList`, `idleOrderList`. Reading only `stockList` silently drops
every part JLC sourced for you — which is exactly the set carrying a fee.

Sub-order: `presaleOrderNo`, `orderStatus` (10 unpaid, 20 in-progress,
30 completed, **40 cancelled**), `payStatus`, `paidMoney`, `presaleType`
(**`stock`** = from JLC's shelf, **`buy`** = JLC sourced it for you),
`presaleGoodsRecords[]`.

Goods row: `componentCode`, `componentModel`, `componentBrand`, `description`,
`presaleNumber` (ordered), **`settlePresaleNumber` (settled — the lot size)**,
`goodsPrice`, `goodsMoney`, **`goodsPaidMoney`**, `goodsStatus`,
`presaleGoodsKeyId`.

### 3.5 Parts invoice

```
POST .../presaleOrder/getInvoiceInfo
{"addressType": "billing", "orderBatchAccessId": "null", "orderBatchNo": "POB..."}
```

`componentGoodsVOList[]` plus `advanceChargeMoney`, `totalPayment`,
`totalOperateFee`, `totalTariffFee`, `totalCarriageFee`, `paidMoney`.

**Do not price lots from here** — see *Traps*.

### 3.6 Private library stock

```
GET .../myLibrary/getCustomerComponentStock?pageNum&pageSize&keyWord&_t=<ms>
GET .../myLibrary/exportCustomerComponentStock?keyWord=      (file download)
```

Richer than the official `getPrivateComponentLibrary` (adds brand, type,
description) but still a **balance, not a ledger**.

### 3.7 Billing

```
POST /overseas-pcb-order/v1/billing/queryBillingBatchNumList
     {pageNum, pageSize, queryTimeType, batchNum, startTime, endTime}
POST /overseas-pcb-order/v1/billing/queryBillingDetail
     {bizId, tradeId, useSelected, paymentType, batchNum}
```

`queryBillingDetail` returns `orderFeeInfo[]` with `componentCode`, `quantity`,
`unitPrice`, `totalPrice` — component-level receipt lines.

### 3.8 Invoice PDF — **UNRESOLVED**

```
GET /overseas-pcb-order/v1/newOrder/downInvoicePDF     ← exists, parameters unknown
```

Returns 200 (not 404), so the route is real, but every parameter shape tried
returns `{"code": 500, "message": "System error"}`: `batchNum`, `+language`,
`+type`, `invoiceNo`, `batchNum+invoiceNo`, `+orderPay`.

Related, also unexplored: `/v1/newOrder/invoice`, `/v1/newOrder/invoiceLayout`,
`/v1/fileCommon/downloadInvoiceGerman`, `/balance/downLoadTransferInvoice`.

UI strings ("It will take about 30 seconds to generate the stamp", "The invoice
download failed. Please try again or print the invoice directly.") indicate a
server-side **stamped** PDF, so a real file should be obtainable.

**To resolve:** in the browser, open an invoice, click **Download Invoice**, and
copy that request as cURL. One capture settles the parameter shape.

---

## 4. Traps

Each of these silently produces a wrong number. All were hit for real.

### `number` / `allPatchNum` is PANELS, not devices, and `pasteNumber` is not assembled
There is no panelisation field on the invoice at all. Taking `number` as a device
count understated a batch **4×** and inflated every per-device cost by the same
factor. Get the factor from §3.2, or derive it from the BOM (each part votes
`consumed / (number × bom_per_device)`; the votes are unanimous when the run is
right). Never assume 1.

### A `buy` lot is paid at an advance and re-settled later
`goodsPaidMoney` is the ADVANCE paid at order time. Once the supplier quotes,
JLC re-settles the sub-order: it refunds the difference (`partRefundMoney`,
`refundStatus` 30, reason *"the estimated price paid … is higher than the actual
price quoted by the supplier"*) or charges a supplement (`supplementStatus` 2).
The lot-level `settleGoodsPaidMoney` carries a refund but NOT a supplement
(lot 768185: $6.24 there, $46.80 settled). The sub-order's `settlePaidMoney`
carries both, every sub-order holds exactly one lot (285 of 285), and the sum
over an order equals the parts invoice's `paidMoney` on all 20 orders
(2026-09-24). Until then the platform booked the advance: $1,185.74 of refunds
as cost (the ESP32 at $2.82/pc, settled $2.2146) and $376.96 of refunded
cancellations as fees, once misread as a "$1,623.23 sourcing fee". The refund is
real money back: the user confirmed the $635.67 ESP32 refund on
POB0202407240206550 arrived (2026-09-24).

**A lot's landed unit cost is the sub-order's `settlePaidMoney / settlePresaleNumber`.**

### `settlePresaleNumber` can be 0
A cancelled sub-order (`orderStatus=40`) settles zero parts. Four real rows paid
advances of $349.39, $16.01, $8.20 and $3.36 and JLC REFUNDED all four in full
(`settlePaidMoney` 0, `refundStatus` 40): they are no line at all. Only a
cancelled sub-order that settled with money kept (lot 754166, $19.78) is a
**fee against no lot**. Dividing by the settled quantity is a division by zero;
using `presaleNumber` invents stock that never arrived.

### The invoice total is settled; its lines are not itemised
The parts invoice's `paidMoney` equals the sum of the sub-orders'
`settlePaidMoney` on all 20 orders (2026-09-24), so it IS the settled figure.
It prints no per-lot price, so **take lot quantity and price from the order
page** and check the total against the invoice. Two cases once read here as
"the invoice shows the pre-settlement figure" were supplements read backwards:
$52.80 → $61.20 on lot 1369417 (unit 0.0176 → 0.0204) and $6.24 → $46.80 on lot
768185 (0.0031 → 0.0234). The settled figures are the higher ones, and the
invoices bill them. `totalPayment` is the goods alone; `paidMoney` adds the invoice's
`totalOtherFee`. On POB0202502102244558 that is $11.16 + $0.50 = $11.66. The
fee sits in each sub-order as `paidMoney - advanceChargeMoney` ($0.23 + $0.27)
and inside its `settlePaidMoney`, so the lots carry it as landed cost. JLC names
it only "other fee"; the order is the one of 20 paid by `ADYEN_APPLE_PAY`, so a
payment surcharge is likely but unconfirmed. `paidMoney` is the figure to match.

### `presaleMoney` is INSIDE the line total
An assembly line reading $7,038.51 already contains $5,896.42 of prepaid
components; the remaining $1,142.09 is the assembly work. Adding it as a separate
line inflated one invoice by **$5,726.80**.

### `presaleDetailResultVOList` arrives as `null`
Not absent, not `[]` — JSON `null` on any invoice with no private-library
consumption (bare-PCB and stencil-only orders). Treating null as "field missing"
wrongly rejected 8 legitimate invoices worth $785. **Key absent** = renamed field
(dangerous); **present but null** = normal. The real invariant is an *iff*:
consumption rows exist if and only if `presaleMoney > 0`.

### Header charges do not equal the sum of line charges
Per-line freight summed to 251.88 where the header said 264.42. Freight, tariff,
service charge and discount are **header** figures.

### FX fields are traps
`settleExchangeRate` is **1.0** on every invoice because the account settles in
USD — it converts *into* the settle currency and carries no information while
billing stays USD. `exchangeRate` (7.00 → 6.75 → 6.70) is **CNY per USD**, JLC's
internal RMB conversion. `euroExchangeRate` was frozen at 0.9595 across invoices
eight months apart, i.e. dead data. Store the raw values; use none of them for
costing.

---

## 5. Arithmetic that holds exactly

Verified on all 35 invoices — use as import gates. A payload failing any of these
was not understood and must not be booked.

```
totalMoney = productMoney + carriageMoney + tariffChargesMoney
             + serviceCharges - discount
subTotalMoney = productMoney + carriageMoney - discount
productMoney  = Σ invoiceListResponseList[].totalMoney

Σ presaleDetailResultVOList[].componentMoney = presaleMoney
Σ invoiceListResponseList[].presaleMoney     = presaleMoney

totalMoney - presaleMoney = the batch's CHARGED total
                            (= payUnionSecondVO.totalFee from §3.1, exactly)
```

The last identity is the prepaid-components rule: the invoice **includes** them,
the batch charge **excludes** them because they were already paid on the POB
order. Verified to the cent: `9216.42 − 5896.42 = 3320.00` and
`11732.16 − 7072.03 = 4660.13`.

Per assembly order, its consumption rows sum to that order line's `presaleMoney`;
a consumption row whose `smtOrderCode` matches no money line is an **orphan** and
must be reported, never attached to the first order.

---

## 6. Joins

```
purchase goods row  (presaleGoodsKeyId, settled qty/price from the ORDER page)
        │  presaleGoodsKeyId          ← verified 50/50, componentCode agreed on all 50
consumption row     (componentNum drawn for a given smtOrderCode)
        │  smtOrderCode
assembly order line (invoiceListResponseList, orderCode = "SMT…-<board>")
        │  produceOrderCode → PCB order → panelX × panelY
devices built
```

Split `orderCode` with `rsplit("-", 1)` to recover the SMT code and board code;
`orderFileName` carries the design name (`DC_GPS_V2_Y84`).

**One invoice bills several assembly orders for different boards**, so any link
to a production run must be per assembly order — a single reference on the
document cannot express it.

---

## 7. Operational notes

- **Sync must stage, never write.** A scrape of an unversioned API must not move
  money unattended.
- **A shrinking batch count is an error, not an empty queue.** A broken read
  returns zero batches, which is byte-identical to "nothing new". Compare against
  the highest previously seen and refuse a drop.
- **Keep the raw payload.** It is the only evidence of what a field meant on the
  day it was read.
- Cookies expire; `last_ok_at` distinguishes *configured* from *working*.
