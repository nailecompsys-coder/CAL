# Partner True-Cost Breakdown — CAL · RVU · Snap

**Prepared for:** MFSA partnership discussion (payback or buy-in credit)  
**Prepared by:** Don / IT Store  
**As of:** 2026-07-14  
**Build window credited:** Early February 2026 → present (~5.5 months)

---

## 1. Executive one-pager

### Who built and hosts what

| Role | Fact |
|------|------|
| **App development** | Don personally designed and built **CAL**, **RVU**, and **Snap (SSS)** |
| **Company** | Don **owns IT Store** |
| **Hosting** | IT Store owns the **Dell PowerEdge R730** and carries monthly power, ISP, and tool costs |
| **Practice use** | All three apps are live / SaaS-shaped for MFSA day-to-day operations |

### The ask (same dollars, two structures)

| Option | Structure |
|--------|-----------|
| **A — Cash / payback** | Practice pays Don (or IT Store) for software value; hosting continues as IT Store service at documented OpEx |
| **B — Buy-in credit** | Same dollar figure applies toward Don’s partnership equity / buy-in |

### Headline numbers (ask basis)

| Layer | Amount | Notes |
|-------|--------|-------|
| **Software replacement (mid)** | **$607,000** | Precise module sum (CAL $270k + RVU $172k + Snap $165k) |
| **Software range** | $425k – $865k | Low / high bands |
| **IT Store OpEx carry (since Early Feb)** | **~$3,245** | $590/mo × 5.5 months |
| **IT Store OpEx ongoing** | **$590/mo** (~$7,080/yr) | Power + ISP + tools |
| **Dell R730 (IT Store capital)** | **~$1,500** used-market mid | Replace with actual IT Store purchase price when known |
| **Don sweat equity (proof)** | **$90,000** | 450 hrs × $200/hr (mid); see §4 |

**Recommended partner number to lead with:** **$607,000** software replacement (mid), plus ongoing **$590/mo** hosting, with **$90,000** sweat equity shown as *proof of who built it* (not stacked on top of full replacement unless partners prefer a blended ask).

**Blended package (if partners want one all-in figure):**  
$607,000 + $3,245 OpEx to date + $1,500 R730 ≈ **$611,745**, plus ongoing $590/mo, with $90k sweat documented as supporting evidence.

---

## 2. Software replacement cost (by app)

Market bands assume a US specialty / healthcare SaaS shop (senior fullstack + native mobile), mid-2026. **Mid column is the ask basis.**

### CAL — Surgical / practice scheduling

| Module | Low | Mid | High |
|--------|-----|-----|------|
| Admin portal (schedules, call, clinic, days off, meetings, settings, rules) | $70,000 | $95,000 | $130,000 |
| Conflict / rules engine | $15,000 | $22,000 | $35,000 |
| Native iOS SwiftUI (OTP, Face ID, Day/Week/Month, time off, coverage, patients, push) | $45,000 | $60,000 | $85,000 |
| Android (Expo bridge + Compose target) | $25,000 | $35,000 | $50,000 |
| Block OR + scheduler lane (portal + mobile assign, overrides, digest) | $25,000 | $35,000 | $50,000 |
| Auth, OTP, SSO shared with RVU, deploy/DR | $15,000 | $23,000 | $35,000 |
| **CAL subtotal** | **$195,000** | **$270,000** | **$385,000** |

### RVU — Capture / insight (SSO with CAL)

| Module | Low | Mid | High |
|--------|-----|-----|------|
| Backend API + admin/portal | $35,000 | $50,000 | $70,000 |
| Scan / capture pipeline + data model | $20,000 | $30,000 | $45,000 |
| Native iOS SwiftUI | $35,000 | $45,000 | $65,000 |
| Android Jetpack Compose | $25,000 | $35,000 | $50,000 |
| CAL JWT SSO + device/auth alignment | $8,000 | $12,000 | $18,000 |
| **RVU subtotal** | **$123,000** | **$172,000** | **$248,000** |

### Snap (SSS / SnapSendSeen) — Clinical photo workflow

| Module | Low | Mid | High |
|--------|-----|-----|------|
| Node/Express API + auth/contracts | $25,000 | $40,000 | $55,000 |
| Staff portal + patient portal + referring office | $45,000 | $65,000 | $90,000 |
| Mobile web surface | $15,000 | $25,000 | $35,000 |
| Desktop snip helper | $12,000 | $20,000 | $30,000 |
| Multi-host prod topology (API/portal/patient/mobile) | $10,000 | $15,000 | $22,000 |
| **Snap subtotal** | **$107,000** | **$165,000** | **$232,000** |

### Software total

| | Low | Mid (ask) | High |
|--|-----|-----------|------|
| **CAL + RVU + Snap** | **$425,000** | **$607,000** | **$865,000** |

**Headline mid ask:** **$607,000** software replacement.

---

## 3. IT Store infrastructure (Don-owned company)

### Capital

| Asset | Basis | Amount | Notes |
|-------|--------|--------|-------|
| Dell PowerEdge R730 | Used-market mid (placeholder) | **$1,500** | Paid by **IT Store**. Replace with actual purchase invoice when available. |

### Monthly OpEx (actuals from Don)

| Line | Monthly | × 5.5 mo (since Early Feb) | Annual |
|------|---------|----------------------------|--------|
| Power | $150 | $825 | $1,800 |
| ISP | $140 | $770 | $1,680 |
| IDE / libraries / Expo / scripts | $300 | $1,650 | $3,600 |
| Protection (if separate) | — | — | TBD |
| **Total** | **$590** | **$3,245** | **$7,080** |

**Payer:** IT Store / Don (not reimbursed by MFSA partners to date).  
**Allocation:** 100% attributed to CAL + RVU + Snap hosting/dev stack for this ask.

### Ongoing hosting

Practice should expect **$590/mo** (or a formal IT Store MSA) as long as apps stay on Don’s R730/DC — separate from software buy-in credit.

---

## 4. Sweat equity (Don personal)

| Scenario | Hours (all 3 apps) | @ $175/hr | @ $200/hr | @ $250/hr |
|----------|-------------------|-----------|-----------|-----------|
| Conservative | 300 | $52,500 | $60,000 | $75,000 |
| **Mid (default)** | **450** | $78,750 | **$90,000** | $112,500 |
| Aggressive | 650 | $113,750 | $130,000 | $162,500 |

**Default proof line:** Early Feb → Jul 2026, **~450 hours**, **$200/hr founder/architect rate** → **$90,000**.

### Provisional hour split

| App | Share | Hours (mid) | @ $200/hr |
|-----|-------|-------------|-----------|
| CAL | 40% | 180 | $36,000 |
| RVU | 30% | 135 | $27,000 |
| Snap | 30% | 135 | $27,000 |
| **Total** | 100% | **450** | **$90,000** |

Sweat equity documents *who built it*. It is usually **not** added on top of full shop replacement ($607k) unless partners choose a blended deal.

---

## 5. Package options for partners

### Option 1 — Clean (recommended)

1. **Buy-in credit or cash:** **$607,000** (software replacement mid)  
2. **Hosting:** IT Store continues at **$590/mo** (or MSA)  
3. **Evidence:** $90,000 sweat + $3,245 OpEx carried + R730 on IT Store books  

### Option 2 — Blended all-in to date

**$607,000 + $3,245 + $1,500 ≈ $611,745**, then **$590/mo** ongoing.

### Option 3 — Floor (if partners reject shop rates)

Use sweat + OpEx + gear only: **$90,000 + $3,245 + $1,500 ≈ $94,745** + $590/mo — *undervalues* live multi-app SaaS; use only as negotiation floor, not fair value.

---

## 6. What partners are getting (capability summary)

| App | Live value to MFSA |
|-----|-------------------|
| **CAL** | Practice scheduling SSOT: admin portal, iOS app, Android in progress, Block OR, call coverage, time off, rules, OTP; surgeon PWA retired in favor of native |
| **RVU** | RVU capture/insight with portal + native apps; SSO with CAL login |
| **Snap** | Clinical photo / snap workflow: API, portals, mobile, desktop helper; production multi-host |

---

## 7. SaaS-ready vs multi-tenant product (important caveat)

| Already true (practice asset) | Not yet (external SaaS sale) |
|------------------------------|------------------------------|
| Multi-role auth, mobile + portal, APIs, production hosting | True multi-tenant isolation for other practices |
| MFSA-live workflows, OTP, push paths | Public billing, self-serve onboarding, SLA product packaging |
| Shared CAL↔RVU SSO | Marketplace / white-label |

**This sheet values MFSA production assets Don built and hosts — not a venture-style multi-tenant SaaS valuation.** Selling the same stack to other practices would require additional tenancy/billing work and could *increase* replacement/upside later.

---

## 8. Partner paragraph (paste-ready)

> I own IT Store. IT Store owns the Dell R730 that hosts our practice apps and carries about $590/month in power, ISP, and development tooling. I personally built CAL, RVU, and Snap from early February through now — hundreds of hours of design and engineering. These systems are live for Mid-Florida Surgical day-to-day operations. A fair shop replacement cost for equivalent software is about **$607,000** (mid). I am asking that this amount be recognized either as **cash/payback** or as **credit toward my partnership buy-in**, with hosting remaining an IT Store responsibility at documented cost. The $90,000 sweat-equity figure is evidence of who built the systems, not an add-on unless we agree on a blended deal.

---

## 9. Open items (optional polish)

- [ ] Replace R730 **$1,500** placeholder with IT Store purchase invoice  
- [ ] Add protection / UPS line if billed separately  
- [ ] Confirm hour total closer to 300 / 450 / 650 if desired  
- [ ] Decide Option 1 vs 2 vs 3 for the partner meeting  
- [ ] Legal/CPA review of buy-in credit structure (out of scope here)

---

*Not tax, legal, or formal appraisal advice. Figures are transparent market-replacement and documented OpEx/sweat for partnership negotiation.*
