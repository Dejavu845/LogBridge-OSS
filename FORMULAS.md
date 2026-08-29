# OCIO Builtins (M1 lock)

config.ocio uses BuiltinTransform for LogC4, S-Log3 (SG3 / SG3.Cine / Venice), V-Log, and Log3G10. The curve constants below remain the Linux/no-OCIO reference and the 18% unit-test source. They match the Builtins on documented 18% grey to well under 0.5%. Do not invent replacement constants.

F-Log2 and N-Log have no standard Builtin.

# Formula verification (M1)

Public white papers were fetched where possible. **No manufacturer constant from the research notes was replaced.** Gaps that the notes left as “official segment” were filled from the same papers.

## Unchanged vs research notes

- **ARRI LogC4** decode for `in >= 0` matches the 2025-01-23 spec CTL. `a=(2**18-16)/117.45`, `b=(1023-95)/1023`, `c=95/1023`. AWG4 xy confirmed. 18% grey → 0.2784 (ARRI table).
- **Sony S-Log3** log segment matches. `cut = 171.2102946929/1023`.
- **Panasonic V-Log** decode matches. V-Gamut xy confirmed (R 0.730/0.280, G 0.165/0.840, B 0.100/−0.030, D65). 18% → 433/1023.
- **Fujifilm F-Log2** `a=5.555556` (not F-Log’s `0.555556`). Decode `(10**((in-d)/c))/a - b/a` confirmed in the F-Log2 / GFX ETERNA white paper. 18% → 400/1023.
- **Nikon N-Log** `x` is 10-bit code 0–1023. Do not divide by 1023. 18% → ~372.
- **RED Log3G10** decode matches 915-0187 Rev-C. 18% → 1/3. RWG xy confirmed.

## Filled in (not a constant change)

1. **LogC4 negatives** — research: “linear extension”. Implemented official `s`, `t` from the spec CTL (`E' * s + t` for `E' < 0`; encode uses `Escene < t`).
2. **S-Log3 shadow** — research: “else the official shadow linear segment”. Decode: `(in*1023-95)*0.01125/(171.2102946929-95)`. Encode uses `in >= 0.01125` for the log piece. 0% → 95/1023, 90% → 598/1023.
3. **V-Log encode** — `cut1=0.01`: `5.6*in+0.125` else `c*log10(in+b)+d`.
4. **F-Log2 encode** — `cut1=0.000889`: `e*in+f` else `c*log10(a*in+b)+d`.
5. **N-Log inverse** — spec `log` is **natural log** (pairs with `exp` in decode): `x = 150*ln(y)+619` above the cut.
6. **Log3G10 encode** — white-paper C: `x = lin + c`; if `x < 0` then `x*g` else `a*log10(x*b+1)`.
7. **S-Gamut3 primaries** — Sony states they match conventional S-Gamut: (0.73, 0.28), (0.14, 0.855), (0.10, −0.05). **S-Gamut3.Cine** from the widely used colour-science / ACES set: (0.766, 0.275), (0.225, 0.800), (0.089, −0.087). Sony has not published Cine xy in the Technical Summary; these are community-standard, **implemented (unverified)**. Never the S-Log3 default.

Third-party pages sometimes list F-Log2 `a=0.555556` (that is F-Log). LogBridge keeps `a=5.555556`.


# HDR ODT (M2-start)

Rec.2100 HLG and Rec.2100 PQ are **ACES Output Transform / BT.2100** OCIO BuiltinTransform paths in Python / Resolve export. Do not invent homemade HLG/PQ constants or a DIY Rec.2100 OETF like the Rec.709 preview curve. Apply only via OCIO (`ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - HDR-VIDEO-1000nits-15nits-HLG_1.1` + `DISPLAY - CIE-XYZ-D65_to_REC.2100-HLG`, and the ST2084 / Rec.2100-PQ pair). macOS preview is ColorSync `itur_2100_HLG` / `itur_2100_PQ` (system BT.2100 transfer) — not an ACES Output Transform, not OCIO, not a homemade curve. Implemented (unverified).


# Exposure (ACES2065-1 linear)

User-facing control is **stops**. After IDT, in ACES2065-1 (AP0) scene-linear:

    rgb_out = rgb_in * (2 ** stops)

- 0 stops is identity (`gain = 1`).
- +1 stop doubles scene-linear RGB.
- Do **not** add or subtract from camera-log or ACEScct code values.
- Then WB / CAT in the same linear AP0 domain. Uniform gain and CAT commute; the locked order is still IDT → Exposure → WB.
- Rec.709 / HLG / PQ remain preview only. ACEScct / EXR is the deliverable.

# Second-batch IDTs (implemented, unverified)

Public papers / ACES CTL. **No invented constants.** C-Log2 negative toe is the ACES CTL inverse, not a homemade mirrored toe.

## Canon C-Log2 (ACES CTL / Canon v1.2)

Prefer OCIO `CURVE - CANON_CLOG2_to_LINEAR` / `CANON_CLOG2-CGAMUT_to_ACES2065-1`.

- `in >= 0.092864125`: `lin = 0.9*(10**((in-0.092864125)/0.24136077)-1)/87.099375`
- else (ACES CTL): `lin = -0.9*(10**((0.092864125-in)/0.24136077)-1)/87.099375`
- Cinema Gamut xy: R 0.74/0.27, G 0.17/1.14, B 0.08/-0.10, D65
- 18% grey → ~0.39825
- Two pairs: Cinema Gamut and BT.2020. Never default C-Log2 to Cinema Gamut.
  C-Log2+BT.2020 has no full IDT Builtin — handwritten C-Log2 curve + BT.2020→AP0.

## Canon C-Log3 (ACES / Canon v1.2, three segments)

Prefer OCIO `CURVE - CANON_CLOG3_to_LINEAR` / `CANON_CLOG3-CGAMUT_to_ACES2065-1`.

- `< 0.097465473`: negative log, coeffs 0.36726845 / 14.98325 (offset 0.12783901)
- `0.097465473–0.15277891`: linear (`(in-0.12512219)/1.9754798`)
- `> 0.15277891`: positive log (offset 0.12240537)
- Reflectance: IRE × 0.9
- 18% grey → ~0.34339
- Two pairs: Cinema Gamut and BT.2020. Never default C-Log3 to Cinema Gamut.

## Apple Log 1 (Apple Log Profile White Paper, Sept 2023)

Prefer OCIO `APPLE_LOG_to_ACES2065-1` / `CURVE - APPLE_LOG_to_LINEAR`.

- `R0=-0.05641088; Rt=0.01; c=47.28711236; β=0.00964052; γ=0.08550479; δ=0.69336945`
- `Pt=c*(Rt-R0)**2`
- `P>=Pt`: `lin=2**((P-δ)/γ)-β`
- `0≤P<Pt`: `sqrt(P/c)+R0`
- `P<0`: `R0`
- BT.2020 / D65. 18% grey → ~0.48827
- Apple Log 2 is a separate pair: same curve + Apple Wide Gamut (not BT.2020).

## ARRI LogC3 EI800 + AWG3 (ACES CSC / ARRI 2017-03)

Prefer OCIO `ARRI_ALEXA-LOGC-EI800-AWG_to_ACES2065-1`. EI800 + ALEXA Wide Gamut 3 only. Not a generic LogC3. EI>1600 has no closed form (Hermite). Do not add other EI/AWG pairs.

- Curve: ACES `Lib.Arri.LogC3` / `CSC.Arri.LogCv3-EI800_to_ACES.ctl` at EI=800
- AWG3 xy: R 0.68400/0.31300, G 0.22100/0.84800, B 0.08610/−0.10200, D65 (ACES `ARRI_ALEXA_WG_PRI`)
- AWG3→AP0 uses CAT02 (same CSC / OCIO Builtin)
- 18% grey encodes to 0.391
- Status: implemented (unverified)

## Apple Log 2 + Apple Wide Gamut (ACES CSC)

No `APPLE_LOG2` OCIO Builtin. Reuse the Apple Log 1 curve (`CURVE - APPLE_LOG_to_LINEAR`).

- Gamut: Apple Wide Gamut from `CSC.Apple.AppleLog2_to_ACES.ctl`: R 0.725/0.301, G 0.221/0.814, B 0.068/−0.076, D65
- AWG→AP0 is the CTL default Bradford matrix (same as other handwritten IDTs)
- Do not attach Apple Log 2 to BT.2020
- Status: implemented (unverified)

## DJI D-Log + D-Gamut (2017-10-10 white paper)

No standard Builtin.

- `in>0.14`: `lin=(10**(3.89616*in-2.27752)-0.0108)/0.9892`
- else: `(in-0.0929)/6.025`
- D-Gamut xy: R 0.71/0.31, G 0.21/0.88, B 0.09/-0.08, D65
- 18% grey → ~0.39876
- D-Log M is unsupported.



# As-shot white balance (linear AP0 CAT)

Log IDTs assume the image is **already white-balanced** (neutrals are
neutral after IDT). Camera CCT/tint is **UI only**. Default CAT is identity.

1. Read CCT + tint from camera-private metadata (ARRI MXF, Sony Acquisition,
   Canon vendor, RED RMD, Apple/DJI). Never QuickTime nclc / nclx / colr.
2. Fill the WB knobs as “as-shot”. Do **not** treat as-shot 5600/6504 as an
   illuminant and CAT toward D65 again (double WB).
3. Apply AP0 CAT **only** when the user moves CCT/tint away from the as-shot
   values, or applies a grey-card override.
   User move is **relative**: `CAT(user→D65)·inv(CAT(as→D65))` ==
   `CAT(user→as)`. 3200→5600 warms (in-camera Kelvin). Not `CAT(as→user)`,
   not `CAT(user→D65)` alone.
   First manually typed CCT with no as-shot is a **label**, not an
   illuminant — identity until there is a reference (as-shot or grey).
4. Grey-card / pick-neutral: sample preview linear RGB (post-IDT, post-exposure
   AP0) → invert the same daylight/Planckian locus used by `cct_to_xy` →
   CCT + tint (1e-3 uv). This overrides metadata and **is** a real
   **absolute** CAT of that sampled white to D65 / working white
   (identity only if the sample is D65).
5. If CCT cannot be read and the user has not picked grey: knobs empty /
   pending, identity CAT. Do **not** guess 5600 K.

6504 K (D65) CAT math is identity when a caller *explicitly* sets that CCT
(user move or grey-card). Missing CCT is not filled in as 5600 or 6504.



# As-shot / grey-card WB (ACES2065-1 AP0)

As-shot writes **only** the existing linear AP0 CAT node (`color/wb.py` Bradford/CAT02). Never CAT on camera-log or ACEScct-encoded values.

- Camera-private CCT/tint → `SerialGraph.wb_cct` / `wb_tint` knobs (UI only). QuickTime nclc is ignored. Default CAT is identity.
- Do not treat as-shot 5600/6504 as an illuminant and CAT toward D65 (double WB).
- Apply CAT only when the user moves CCT/tint away from as-shot, or on a grey-card override.
- User move: `white_balance_matrix(src_cct=as-shot, dst_cct=user)` =
  `CAT(user→D65)·inv(CAT(as→D65))` == `CAT(user→as)`. 3200→5600 warms.
  As-shot / unmoved = identity.
- First typed CCT with no as-shot = label, identity. Do not CAT(user→D65) on first fill.
- Missing CCT/tint → **pending / identity** (knobs empty). Do not guess 5600 or 6504. `cct is None` returns `I` from `white_balance_matrix`.
- Grey-card pick: mean of the post-IDT ACES2065-1 (AP0) linear patch → XYZ → xy → invert `cct_to_xy` (locus search + 1e-3 uv tint). Overrides metadata; that is an **absolute** CAT of the sampled white to D65 (identity only if sampled D65). Implemented (unverified).
- Resolve WB node stays bypassable (`graph.xml` `bypassable="true"`; DCTL **Bypass WB**). Implemented (unverified).


# Auto WB estimate (not calibration)

Engineering lock, not a white paper. Label: **白平衡（估计）**. Implemented (unverified).

1. Input is post-IDT ACES2065-1 (AP0) linear. Convert to linear ACEScg for the statistic. Never Rec.709 pixels, never ACEScct, never camera-log.
2. Shades-of-Gray Minkowski mean, `p=6`, on pixels with AP1 Y ≥ 0.02 and no channel > 8.
3. Empty (no 5600 guess) when: residual angle vs ACEScg (1,1,1) < 2°; 3×3 tile max angle > 5° (mixed light); valid pixels < 15%.
4. Confirm writes an **absolute** AP0 CAT of the estimated white to D65 (same class as grey-card). Not relative to as-shot.
5. Propose does not write CAT. Grey-card overrides the estimate. As-shot default stays identity.
