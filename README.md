# LogBridge

Public OSS iteration repo — develop here going forward.

macOS batch tool: mixed-camera Log → ACES2065-1 (IDT) → Exposure (stops, linear gain) → WB in ACES2065-1 linear (AP0) → ACEScct timeline / optional ODT (Rec.709 preview | Rec.2100 HLG | Rec.2100 PQ).

M1 is a **serial node graph** (IDT → Exposure → WB → selectable ODT), not a general node editor and not a Resolve-like grade. Every IDT and ODT is **implemented (unverified)** until golden grey-card samples are measured. This project does not describe cameras or HDR outputs as “supported”. There is no 一键精准.

M2-start adds optional **Rec.2100 HLG** and **Rec.2100 PQ** ODT nodes via **ACES Output Transform / BT.2100** (OCIO BuiltinTransform, or config-aces names if present). Prefer those Builtins over any handwritten transfer. There is no homemade HLG/PQ curve. HDR OT is unverified — not a one-click accurate path.

Internal working encoding: **ACEScct** (AP1 log). Scene-linear interchange / `roles.scene_linear`: **ACES2065-1** (Linear AP0). `roles.color_timing`: ACEScct. White balance is Bradford (or CAT02) chromatic adaptation in ACES2065-1 (AP0) scene-linear only — never a CAT on ACEScct. DaVinci Wide Gamut Intermediate is **not** the default internal or deliverable.

## Usability

- **Empty state:** drag-and-drop a folder of mixed clips is the primary action (big drop zone, short copy: “把混源文件夹拖进来”). Choosing files is secondary. **No bundled camera manufacturer demo clips** — drop your own files.
- **Paired IDT picker:** when metadata cannot lock a curve+gamut pair, the UI shows locked pairs — e.g. `S-Log3 + S-Gamut3` and `S-Log3 + S-Gamut3.Cine` — **not** two independent dropdowns (curve vs gamut).
- **Block process:** a clip is processable only when its paired IDT is locked. **处理已锁定片段** appears only when locked-clip count > 0 and writes one **ACES2065-1 (AP0 linear) proxy EXR sequence** (`{stem}_ACES2065-1_proxy/frame_000000.exr`) per locked clip. **整段代理，不是全精度成片.** Movie write decode uses source 10-bit / native-depth Y′CbCr → float (matrix-only; matrix and full/video from nclc/colr/vui; missing tags fail 「无法读取片源 Y′CbCr 矩阵/范围，未写出」; no silent 709-video default; video-range 10-bit is 64/876 not /1023; not the preview 8-bit path promoted to float). Movie preview first-frame unpack shares that nclc/colr/vui matrix+range helper (no transfer; missing tags fail the same Chinese; no silent 709-video default), then displays 8-bit / long-edge 1920. Stills (TIFF / DPX / EXR) stay ImageIO — already RGB, no Y′CbCr unpack. Write is source pixels 1:1 and source-native bit depth. 16384 is a refuse ceiling (「片源边长超过 16384，未写出」), not a downsample. Do not scale export to 16384 or 1920. 8-bit Y′CbCr is only the fallback. Still a proxy, not camera-original. Not ACEScct. Not a Rec.709 .mov/.mp4. Pending / unlocked stay in the list with **先选择 Log 与色域** or **先选择成对 IDT** and produce **no** output folder. Status: **N 条已锁定 / M 条待选**. After the batch, **N 条已写出代理 / M 条待选跳过 / K 条失败** plus 失败原因 (not a preview refresh; not a second process button). A mixed bin is allowed — do not require every clip locked. No silent IDT. Never guess.
- **S-Log3:** never silently default to S-Gamut3.Cine. Both pairs are offered; the user must pick one.
- **C-Log2 / C-Log3:** never silently default to Cinema Gamut. Both Cinema Gamut and BT.2020 pairs are offered; the user must pick one.
- **Venice:** `S-Log3 + S-Gamut3 (Venice)` and `S-Log3 + S-Gamut3.Cine (Venice)` appear **only if** a Venice body is detected.
- **Copy / badges:** “implemented (unverified)” — never “supported”, never 一键精准.
- **WB default:** as-shot CCT + tint from camera-private metadata fills the knobs (UI only). **Not** QuickTime nclc. Log IDTs assume already white-balanced; **default CAT is identity** — do not CAT as-shot 5600/6504 toward D65 (double WB). User move away from as-shot is **relative** `CAT(user→D65)·inv(CAT(as→D65))` == `CAT(user→as)` in AP0; 3200→5600 warms. Not `CAT(as→user)`, not `CAT(user→D65)` alone. First typed CCT with no as-shot is a label (identity). Grey-card is an absolute CAT. If CCT cannot be read and the user has not picked grey: knobs empty / identity / **as-shot unknown** — do **not** guess 5600 K. User can still change CCT/tint or bypass WB.
- **Auto WB:** **白平衡（估计）** only. SoG p=6 in linear ACEScg after IDT; user confirm writes an absolute AP0 CAT. Low confidence stays empty (no 5600 guess, no Rec.709 sample). Grey-card overrides. As-shot default stays identity. Not 精准 / 一键校准. Implemented (unverified).
- **Graph:** serial IDT → Exposure (stops, default 0) → bypassable WB → ODT selector: **Off (ACEScct deliverable)** | Rec.709 preview | Rec.2100 HLG | Rec.2100 PQ. Default Off. Rec.709 / HLG / PQ panes are 预览·非成片 — not a finished picture. Node strip + Resolve export sit behind **高级** (hidden by default) so they do not compete with preview / IDT / process.
- **Primary button:** **处理已锁定片段** (never 一键还原). Shown only when locked-clip count > 0. Writes an ACES2065-1 AP0 proxy EXR sequence — **整段代理，不是全精度成片.** Not ACEScct. Unlocked clips are skipped. **Apply graph** is the same batch, not a second button. Before writing, estimate dest disk from **locked clips only** (frame count × pixels × 12 bytes, uncompressed float32 RGB, plus a small margin). Unknown frame count uses duration×fps or a conservative 24 fps × 60 s guess (said in the note). If free space is short, do not write; status is **磁盘空间不足，未写出** + **整段代理，不是全精度成片**. The folder picker may show the estimate. While writing, the same button becomes **取消** and status shows **写出代理 i/N · frame k**. Escape while writing is that same **取消** (no extra button); idle Escape does nothing. Cancel removes the in-progress `_proxy` folder (half sequence is 不是成片); completed clips stay. Status after cancel says **已取消** and still **整段代理，不是全精度成片**. After a successful write, status shows the dest folder (short) and **在 Finder 中显示** (opens `{stem}_ACES2065-1_proxy/`). Locked sidebar rows show **已写出代理** (or a short Chinese error). Clicking a written row or its **已写出代理** chip reveals that clip's `{stem}_ACES2065-1_proxy/` from the last dest. Pending / failed / cancelled do not reveal. Pending stay **待选** / **先选择 Log 与色域** / **先选择成对 IDT**. A cancelled in-progress clip is not 已写出; completed clips keep 已写出代理. Re-export clears or refreshes the chip. The folder picker remembers the last dest (UserDefaults). Cancel does not treat a deleted half-folder as success. After each locked write, count EXRs in `{stem}_ACES2065-1_proxy/` against source duration × metadata fps (off-by-one allowed: inclusive last frame). Missing fps is **读不到帧率，未核对**; missing duration is **读不到时长，未核对** — this check never guesses 24 or 30 fps and does not reuse the dest-disk 24 fps × 60 s guess. A count mismatch is **帧数对不上**; that folder is removed so it is not **已写出代理**. When the batch finishes (including cancel / disk abort / frame-check failures), status is one Chinese summary: **N 条已写出代理 / M 条待选跳过 / K 条失败** plus 失败原因 (existing chips only). The summary does not reuse the dest-disk 24 fps × 60 s guess.
- **设置:** 默认预览 Rec.709（预览·非成片）；导入后提示估计 WB 默认关（只提示，不写入）；未锁 IDT 挡住处理不能关。
- **Preview badge:** **预览·非成片**
- **Export:** **导出 ACEScct / EXR**

## OpenColorIO

Mac OpenColorIO uses **BuiltinTransform** styles named in `ocio/config.ocio` (`ARRI_LOGC4_to_ACES2065-1`, `ARRI_ALEXA-LOGC-EI800-AWG_to_ACES2065-1`, `SONY_SLOG3-SGAMUT3_to_ACES2065-1`, `SONY_SLOG3-SGAMUT3.CINE_to_ACES2065-1`, `PANASONIC_VLOG-VGAMUT_to_ACES2065-1`, `RED_LOG3G10-RWG_to_ACES2065-1`, `CANON_CLOG2-CGAMUT_to_ACES2065-1`, `CANON_CLOG3-CGAMUT_to_ACES2065-1`, `APPLE_LOG_to_ACES2065-1`). Venice Builtins are detect-only, never a silent S-Log3 default. There is no `APPLE_LOG2` Builtin — Apple Log 2 is `CURVE - APPLE_LOG_to_LINEAR` + Apple Wide Gamut.

Linux tests use `color/` white-paper **reference encode/decode for 18% codes only**. They do not require PyOpenColorIO. F-Log2, N-Log, C-Log2+BT.2020, C-Log3+BT.2020, D-Log, and Apple Log 2 have no full IDT Builtin — those papers / ACES CSC stay handwritten (C-Log2+BT.2020 is handwritten C-Log2 curve + BT.2020→AP0 if no Builtin). C-Log2+Cinema Gamut / C-Log3+Cinema Gamut / Apple Log 1 / LogC3 EI800+AWG3 use BuiltinTransform when present.

Rec.2100 HLG / PQ colorspaces in `ocio/config.ocio` name ACES Output Transform BuiltinTransform styles (`ACES-OUTPUT - ACES2065-1_to_CIE-XYZ-D65 - HDR-VIDEO-1000nits-15nits-HLG_1.1` + `DISPLAY - CIE-XYZ-D65_to_REC.2100-HLG`, and the ST2084 / Rec.2100-PQ pair) plus config-aces aliases (`Output - Rec.2100-HLG - 1000 nit`, `Output - Rec.2100-Rec.2020-ST2084 - 1000 nit`). Applying HDR requires OCIO. No homemade HLG/PQ LUT. HDR OT via ACES/BT.2100 is **implemented (unverified)**.

Python curves in `color/` are the source of truth for 18% tests. Regenerating OCIO assets:

```bash
python3 scripts/generate_ocio_assets.py
```

## Open in Xcode (macOS)

1. Copy this tree to a Mac.
2. Open `macos/LogBridge/LogBridge.xcodeproj` in Xcode 15+ (macOS 14 deployment target).
3. Select the **LogBridge** scheme, destination **My Mac**, and Run.

Layout: empty-state drop zone (folder of mixed clips) → clip list (LazyVStack; **待选** / **已锁定** are two visual states — type, weight, chip, left accent; no extra lock button; Up/Down in the main window moves the selected clip, ignored while writing; Delete/Backspace removes the selected clip from the session only — does not delete the source file or an already-written `_proxy` folder; ignored while writing; text / numeric fields keep Delete; no extra button, no confirm sheet; Escape while writing is the same 取消, idle Escape does nothing; no extra button) | split preview (dominates) + paired IDT + **处理已锁定片段** | thinner Exposure / WB inspector. Node strip + **导出 ACEScct / EXR** are behind **高级**.

Split preview: the **source** pane is camera/log (untagged working-space dump) and is **not** tagged Rec.709. Rec.709 ODT tags `CGColorSpace.itur_709` only on the 709 path (8-bit u8 / Metal OETF unchanged). HLG/PQ preview is ColorSync `itur_2100_HLG` / `itur_2100_PQ` (AP0 linear → existing Rec.2020 matrix → system BT.2100 transfer, rgba16Float, `wantsExtendedDynamicRangeContent`). Not an ACES Output Transform. Not OCIO. If ColorSync / the EDR layer cannot be built: empty right pane and **HDR 预览建不出** — do not fall back to 709. If the display has no EDR: still show HDR-tagged pixels and **屏幕无 EDR，预览被压到 SDR**. 预览·非成片. 未验证.

## Run tests (Linux or macOS)

```bash
python3 -m pip install -e ".[test]"
python3 -m pytest -q
```

Or without install:

```bash
python3 -m pip install numpy pytest
PYTHONPATH=. python3 -m pytest -q
```

CI: `.github/workflows/test.yml` 在 Ubuntu 上跑 pytest；另有 `macos-15` job 编现有 LogBridge scheme 并跑同一套 pytest。Metal GPU、Finder 显示、真机写出 / 真机导出 在 Actions 上测不了，仍靠人在 Mac 上点。没有真机 CI。

## Input IDTs (M1)

| IDT | Curve | Gamut | 18% grey (spec) | Status |
| --- | --- | --- | --- | --- |
| ARRI LogC4 / AWG4 | LogC4 | AWG4 / D65 | 0.2784 normalized | implemented (unverified) |
| Sony S-Log3 / S-Gamut3 | S-Log3 | S-Gamut3 / D65 | 420 / 1023 | implemented (unverified) |
| Sony S-Log3 / S-Gamut3.Cine | S-Log3 | S-Gamut3.Cine / D65 | 420 / 1023 | implemented (unverified) |
| Panasonic V-Log / V-Gamut | V-Log | V-Gamut / D65 | 433 / 1023 | implemented (unverified) |
| Fujifilm F-Log2 / BT.2020 | F-Log2 | BT.2020 / D65 | 400 / 1023 | implemented (unverified) |
| Nikon N-Log / BT.2020 | N-Log | BT.2020 / D65 | ~372 / 10-bit | implemented (unverified) |
| RED Log3G10 / REDWideGamutRGB | Log3G10 | RWG / D65 | 1/3 | implemented (unverified) |
| Canon C-Log2 / Cinema Gamut | C-Log2 | Cinema Gamut / D65 | ~0.39825 | implemented (unverified) |
| Canon C-Log2 / BT.2020 | C-Log2 | BT.2020 / D65 | ~0.39825 | implemented (unverified) |
| Canon C-Log3 / Cinema Gamut | C-Log3 | Cinema Gamut / D65 | ~0.34339 | implemented (unverified) |
| Canon C-Log3 / BT.2020 | C-Log3 | BT.2020 / D65 | ~0.34339 | implemented (unverified) |
| Apple Log / BT.2020 | Apple Log 1 | BT.2020 / D65 | ~0.48827 | implemented (unverified) |
| Apple Log 2 / Apple Wide Gamut | Apple Log (same curve) | Apple Wide Gamut / D65 | ~0.48827 | implemented (unverified) |
| ARRI LogC3 EI800 / AWG3 | LogC3 EI800 | AWG3 / D65 | 0.391 | implemented (unverified) |
| DJI D-Log / D-Gamut | D-Log (2017) | D-Gamut / D65 | ~0.39876 | implemented (unverified) |

Canon C-Log2 and C-Log3 are each **two locked pairs**. Metadata or the user picks **Cinema Gamut** vs **BT.2020**. LogBridge never defaults C-Log2 or C-Log3 to Cinema Gamut.

**Explicitly unsupported:** DJI D-Log M. LogC3 is the EI800 + AWG3 pair only (not a generic LogC3; no EI>1600). Apple Log 2 is Apple Wide Gamut, not BT.2020.

Sony S-Log3 is **two locked pairs**. Metadata or the user picks a **paired IDT** (S-Log3 + S-Gamut3 vs S-Log3 + S-Gamut3.Cine) — not two dropdowns. LogBridge never defaults S-Log3 to S-Gamut3.Cine. Clips without a locked pair stay **pending**. **处理已锁定片段** / **Apply graph** write an ACES2065-1 AP0 proxy EXR sequence for locked clips only and skip the rest (reason: **先选择 Log 与色域** / **先选择成对 IDT**). **整段代理，不是全精度成片.** Pending clips in the same bin do **not** block locked writes. The primary button is never 一键还原. Venice pairs appear only if a Venice body is detected.

Nikon N-Log white-paper `x` is a **10-bit code value 0–1023**. Do not divide by 1023 before the curve. 452 is the breakpoint, not 18% grey (~372). The OCIO LUT is sampled on 0–1 = code/1023 so image buffers stay normalized; the Python API takes 10-bit codes.

Fujifilm F-Log2 uses Data Sheet 1.0 + BT.2020 (`a=5.555556`). Not an F-Log1 LUT.

## Detection order

1. Camera-private metadata (ARRI MXF, Sony Acquisition, Canon vendor, RED RMD)
2. Filename / model hint
3. User picker (paired IDTs; clip stays pending until chosen)

QuickTime `nclc` / `nclx` / `colr` is **never** used to identify S-Log3 or LogC4, and is **never** used as as-shot CCT/tint.

As-shot white balance (CCT + tint) is read from the same camera-private boxes when present and written **only** into the existing linear AP0 CAT WB knobs (UI only). Default CAT is identity — do not treat as-shot 5600/6504 as an illuminant (double WB). Missing CCT/tint is **pending / identity** — do not guess 5600 or 6504. Grey-card pick samples **after IDT in ACES2065-1 (AP0) linear** and that is a real CAT (override). Implemented (unverified).

## Node workflow (serial only)

Visible graph, four slots — `color/graph.py` `SerialGraph`, used by `color/pipeline.py` and Resolve export.

Locked order: **IDT → Exposure → WB → ACEScct → preview ODT (709 / HLG / PQ)**.

1. **IDT** (`01_IDT`) — locked curve+gamut pair → ACES2065-1. Preview cache stores this AP0 linear buffer. Not bypassable.
2. **Exposure** (`02_Exposure`) — user-facing **stops** (default 0). After IDT, in ACES2065-1 linear: `rgb * (2 ** stops)`. Not a log-code add. **Bypassable / zeroable.** Own 1D / gain export node — not baked into IDT or WB when stops=0. Preview applies exposure in linear on the cached post-IDT buffer.
3. **WB** (`03_WB`) — Bradford/CAT02 in **ACES2065-1 (AP0)** scene-linear, CCT + green-magenta tint. As-shot writes **only** this existing linear AP0 CAT node (never a CAT on camera-log or ACEScct-encoded values). Camera-private CCT/tint (not nclc) fills the knobs (UI only). **Default CAT is identity** — Log IDTs assume already white-balanced; do not CAT as-shot 5600/6504 toward D65 (double WB). User move is relative: `white_balance_matrix(src_cct=as-shot, dst_cct=user)` = `CAT(user→D65)·inv(CAT(as→D65))` == `CAT(user→as)` in AP0; 3200→5600 warms (not CAT(as→user), not CAT(user→D65) alone). First typed CCT with no as-shot is a label (identity). Grey-card pick samples **after IDT in ACES2065-1 (AP0) linear** and that is an **absolute** CAT of the sampled white to D65. Missing CCT/tint = **pending / identity** — **do not guess 5600 or 6504**. **Bypassable.** User can still change CCT/tint. WB off = IDT → Exposure → ACEScct, no bake (XML `enabled="false"`; DCTL **Bypass WB**). Export WB is a linear AP0 3×3 (or DI-free DCTL on ACES2065-1 / ACEScct-decoded-to-linear). Implemented (unverified). Uniform gain and CAT commute; the order is still locked.
4. **ODT** (`04_ODT`) — selector, default **Off** (ACEScct deliverable / ACES2065-1 EXR):
   - **Off** — ACEScct timeline deliverable.
   - **Rec.709 preview** — DIY BT.709 OETF, no RRT. Preview only, unverified. Tags `CGColorSpace.itur_709` only in this mode.
   - **Rec.2100 HLG** — ACES Output Transform / BT.2100 (`ACES-OUTPUT … HLG_1.1` + `DISPLAY … REC.2100-HLG`, or ACES 2.0 Rec.2100-HLG style if present). Implemented (unverified).
   - **Rec.2100 PQ** — ACES Output Transform / BT.2100 (`ACES-OUTPUT … ST2084_1.1` + `DISPLAY … REC.2100-REC2020-ST2084`). Implemented (unverified).
   - HLG/PQ are **not** “supported” and not 一键精准. No homemade HLG/PQ curve.

The right inspector is Exposure + WB (three states: 机内 as-shot / 白平衡（估计） / 灰卡). Paired IDT stays under the preview — not inside **高级**. Node strip + Resolve export live in **高级**. No sat / extra grade nodes. The Rec.709 pane is 预览·非成片 — do not treat it as a finished picture.

Python: `from color.graph import SerialGraph`. Swift: `SerialGraph` + `NodeSlot` in `Models/NodeGraph.swift`. Status: implemented (unverified).

### Resolve export — bypass WB

Export writes a serial **node graph**, not a prose sidecar: `graph.xml`, `graph.dot`, `01_IDT_<idt>.cube`, `02_Exposure.cube` / `.dctl`, `03_WB.cube` / `.cdl` / `.ccc` / `.dctl`, `04_ODT_Rec709.cube`, `README_RESOLVE.md`.

Export default: **ACEScct** timeline / **ACES2065-1**. **处理已锁定片段** writes `{stem}_ACES2065-1_proxy/frame_000000.exr` (ACES2065-1 AP0 linear proxy sequence; source 10-bit / native-depth Y′CbCr → float, not preview 8-bit promoted) — **整段代理，不是全精度成片.** It does **not** write ACEScct. **导出 ACEScct / EXR** in **高级** is the Resolve graph (LUT/XML/DCTL/cube), not a movie. Rec.709 ODT is **709 预览** (DIY BT.709 OETF, not an ACES Output Transform), off by default. 预览·非成片. Rec.2100 HLG/PQ are optional ACES/BT.2100 OT nodes (unverified). Locked clips write even when other clips are still pending. WB off writes an identity CAT (no bake). Implemented (unverified).

Python: `from color.resolve_export import export_locked_resolve_bundle` (locked clips only; pending keep **先选择成对 IDT** / **先选择 Log 与色域**) or `export_resolve_bundle` (pass `graph=` or `include_wb=`). Swift: `ResolveExporter.export(to:clips:...)` on locked clips. Status: implemented (unverified).

## Preview vs full render

The macOS split preview is **not** a full-resolution render. Both panes show a **预览·非成片** badge (8-bit thumbnail is not a deliverable).

- One downscaled frame per clip (long edge ≤ 1920). Movies: `AVAssetReader` Y′CbCr (ProRes / H.264 / HEVC in MOV/MP4; MXF only if the system recognizes those codecs). Stills: ImageIO (TIFF / DPX / EXR). No `copyCGImage`. **ARRI MXF / R3D / BRAW are refused.** Not 全格式已支持.
- Cached per clip: decoded camera/log buffer + IDT **ACES2065-1 linear** buffer (post-IDT, no exposure). IDT change invalidates linear; exposure + WB apply in linear on that AP0 buffer. Clip change reuses the decode if the URL is unchanged.
- Color apply runs off the main thread. 8-bit thumbnails are a viewing proxy — do not judge IDT accuracy from the preview.
- Source pane is untagged camera/log. Rec.709 ODT pane is tagged `CGColorSpace.itur_709` only when the ODT node is on.
- Clip list is a `LazyVStack` (virtualized).

**处理已锁定片段** writes `{stem}_ACES2065-1_proxy/frame_000000.exr` per locked clip (whole-clip loop; source pixels 1:1; 16384 is a refuse ceiling, not a downsample; source 10-bit / native-depth Y′CbCr → float, then 8-bit 420/422 fallback). **整段代理，不是全精度成片.** Preview/scrub stays 8-bit-first (movie unpack shares nclc/colr/vui matrix+range; stills ImageIO thumbnail; display 8-bit / 1920). Not ACEScct. Not a Rec.709 .mov/.mp4. After the batch, **N 条已写出代理 / M 条待选跳过 / K 条失败** plus 失败原因 is those proxy sequences (or per-clip write errors), not the preview pane. Progress is **写出代理 i/N · frame k**; cancel removes the current half folder. Dest disk is estimated from locked clips (float32 RGB uncompressed) and a short volume aborts with **磁盘空间不足，未写出**. After write, EXR count must match duration × metadata fps only; missing fps/duration or a mismatch is a Chinese failure and the folder is removed. This check does not reuse the dest-disk 24 fps × 60 s guess. Full-precision / camera-original encode is later. The Resolve graph in **高级** is a separate LUT/XML export (P1), not a second process button.

## Verification status

No golden samples have been measured. Do not claim accuracy. See `ACCEPTANCE.md`.

## Out of scope (M1)

- Full node editor / grading (serial four-slot graph only: IDT → Exposure → WB → ODT)
- Treating the DIY Rec.709 OETF as a standard deliverable (it is preview only)
- Homemade HLG/PQ curves (HDR OT is ACES/BT.2100 Builtin only)
- DJI D-Log M (explicitly unsupported). Other EI/AWG LogC3 pairs. Apple Log 2 attached to BT.2020.
- ARRI MXF (ARRIRAW), R3D, BRAW, AVI, MKV, CinemaDNG (containers refused)
- Claiming 全格式已支持
- Inventing a C-Log2 mirrored toe (use OCIO `CURVE - CANON_CLOG2_to_LINEAR` / `CANON_CLOG2-CGAMUT_to_ACES2065-1` / ACES CTL)
- Camera-protocol reverse engineering, marketplace integrations
- Treating QuickTime nclc as log identity or as-shot CCT
- Guessing 5600 K when as-shot CCT is missing
- Using the preview as a substitute for a full render
- 一键还原 / claiming a one-click restore (primary action is 处理已锁定片段; unlocked clips stay 先选择 Log 与色域 / 先选择成对 IDT)

## Layout

```
color/          Python source of truth (curves, WB, serial graph, pipeline, detection)
tests/          pytest (must pass on Linux)
ocio/           config.ocio (BuiltinTransform) + handwritten F-Log2 / N-Log LUTs
macos/LogBridge Xcode / SwiftUI (preview + IDT + process; node strip in 高级)
scripts/        LUT/config generator
```

## 许可证 / License

本项目以 MIT License 发布。详见根目录 `LICENSE`。

