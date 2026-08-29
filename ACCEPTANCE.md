# LogBridge M1 + M2-start acceptance gates

Nothing below is claimed as passing. IDTs and HDR OTs are **implemented (unverified)**.

Default language is **ACEScct** / **ACES2065-1**. Rec.709 is preview only. Rec.2100 HLG / PQ are ACES Output Transform / BT.2100 (unverified). WB is ACES2065-1 (AP0) scene-linear. Implemented (unverified). Not supported. Not 一键精准.

## Golden grey-card samples (per log)

Shoot or obtain a grey card (18% reflectance) in each encoding, exposed to the manufacturer’s documented mid-grey code value. Decode with `color/` and confirm ACES scene-linear RGB ≈ 0.18, 0.18, 0.18 after IDT.

| Encoding | Documented 18% code | Gate |
| --- | --- | --- |
| ARRI LogC4 | 0.2784 (table: 27.84% IRE / 12-bit full 1140) | pending golden |
| Sony S-Log3 | 420 / 1023 (IRE 20%) | pending golden |
| Panasonic V-Log | 433 / 1023 (IRE 42%) | pending golden |
| Fujifilm F-Log2 | 400 / 1023 | pending golden |
| Nikon N-Log | ~372 / 10-bit (IRE ~35%; 452 is the breakpoint) | pending golden |
| RED Log3G10 | 1/3 | pending golden |
| Canon C-Log2 | ~0.39825 | pending golden |
| Canon C-Log3 | ~0.34339 | pending golden |
| Apple Log 1 | ~0.48827 | pending golden |
| Apple Log 2 | ~0.48827 (same curve; Apple Wide Gamut) | pending golden |
| ARRI LogC3 EI800 | 0.391 | pending golden |
| DJI D-Log | ~0.39876 | pending golden |

Sony: one grey card in **S-Gamut3** and one in **S-Gamut3.Cine**. Do not treat Cine as the default.

Unit tests already assert these encodings mathematically. Golden files are a different gate.

## Rec.709 tagged preview

- **ODT / processed pane only:** Metal/AppKit layer `colorspace` is `CGColorSpace.itur_709`.
- **Source pane is not Rec.709-tagged.** It stays camera/log or working-space / untagged so the split is a real comparison.
- Rec.709 ODT pixels are not blit into an untagged (Display P3) surface, and are not shown in the source pane.

Both preview panes overlay **预览·非成片**. 8-bit thumbnail is not a deliverable.

Gate: screenshot or Instruments/Core Image probe showing the *ODT* drawable color space is BT.709 and the source drawable is not. Overlay badge text includes 预览·非成片.

## Serial node graph (M1 + M2-start ODT)

- UI shows four serial slots: IDT → Exposure → WB → ODT (`color/graph.py` `SerialGraph`).
- Locked order: IDT → Exposure (stops) → WB → ACEScct → preview ODT (709 / HLG / PQ).
- Exposure is stops (default 0). Internally after IDT, in ACES2065-1 linear: `rgb * (2 ** stops)`. Not a log-code add. Bypassable / zeroable. Own export node (1D / gain) — not baked into IDT or WB when stops=0.
- ODT selector: Off (ACEScct deliverable) | Rec.709 preview | Rec.2100 HLG | Rec.2100 PQ. Default Off.
- Right inspector is Exposure + WB. Click a node in **高级** to see the serial graph. WB / Exposure / ODT are bypassable; IDT is not.
- WB off = IDT → Exposure → ACEScct, no bake in preview and in Resolve export (`graph.xml` `enabled="false"`).
- WB CAT runs in ACES2065-1 (AP0) scene-linear, never on ACEScct-encoded values. Preview cache stores post-IDT linear; exposure + WB apply in linear.
- **As-shot writes only the existing linear AP0 CAT node** (knobs / UI only). Camera-private CCT + tint (ARRI MXF, Sony Acquisition, Canon vendor, RED RMD, Apple/DJI if present). Not QuickTime nclc. Never a CAT on camera-log or ACEScct-encoded values. Log IDTs assume already white-balanced; **default CAT is identity**. Do not treat as-shot 5600/6504 as an illuminant (double WB). Apply CAT only when the user moves CCT/tint away from as-shot, or on a grey-card override. User can still change CCT/tint or bypass WB.
- **Missing CCT/tint → knobs empty / pending / identity.** Do not guess 5600 or 6504.
- **Grey-card pick** samples **after IDT in ACES2065-1 (AP0) linear**, sets CCT/tint, and **that is a real CAT** (override; identity only if sampled D65). Implemented (unverified).
- Rec.709 ODT is preview only, off by default. Off = ACEScct deliverable. UI must not imply grading on the 709 pane as a finished picture (预览·非成片).
- Rec.2100 HLG / PQ: macOS preview is ColorSync `itur_2100_HLG` / `itur_2100_PQ` (AP0 linear → existing Rec.2020 matrix → system BT.2100). Not an ACES Output Transform. Not OCIO. No homemade HLG/PQ curve. Fail closed: **HDR 预览建不出** (empty right pane, never 709). No-EDR display: **屏幕无 EDR，预览被压到 SDR**. 预览·非成片. Implemented (unverified). Not supported.
- Not a general node editor. No sat / unlisted grade nodes.

## Resolve export — WB toggle

- Export is a Resolve-importable graph (`graph.xml` / `graph.dot`) plus `01_IDT_*.cube`, `02_Exposure.{cube,dctl}`, `03_WB.{cube,cdl,ccc,dctl}`, `04_ODT_Rec709.cube` — not a prose sidecar only.
- **Locked paired-IDT clips only** (session package). Pending stay listed with **先选择成对 IDT** / **先选择 Log 与色域**. Never guess an IDT or 5600/6504. Python: `export_locked_resolve_bundle`. Swift: `ResolveExporter.export` on `lockedClips`.
- **Exposure is its own 1D/gain node** (Color page serial node 2). **WB is its own corrector/node** (Color page serial node 3). Disable it, or tick DCTL **Bypass WB**, or skip `03_WB.cube` / the CDL.
- **WB off = identity / no-op bake.** Do not write a CAT into the DCTL / cube / CDL when WB is bypassed (`graph.xml` `enabled="false"`; cube/DCTL are identity).
- WB is a linear AP0 Bradford/CAT02 3×3 (or DI-free DCTL on ACES2065-1 / ACEScct-decoded-to-linear), not baked into the IDT or Rec.709 cubes.
- Standard deliverable is **ACEScct or ACES2065-1 EXR / ACES workflow** (**导出 ACEScct / EXR**). Rec.709 cube is **709 预览** (DIY BT.709 OETF, no RRT) — never an ACES Output Transform. 预览·非成片. Rec.2100 HLG/PQ are optional ACES/BT.2100 OT (unverified). Remaining graph when WB is off: IDT → ACEScct, no bake.

Gate: open the export in Resolve; bypassing the WB node must restore uncorrected camera linear (after IDT). Implemented (unverified).

## HDR OT via ACES/BT.2100 (M2-start)

- Rec.2100 HLG and Rec.2100 PQ are declared ODT paths using OCIO **ACES Output Transform / BT.2100** naming (`ACES-OUTPUT … HLG_1.1` / `… ST2084_1.1` + `DISPLAY … REC.2100-*`, or ACES 2.0 Rec.2100 styles if the registry has them; config-aces aliases `Output - Rec.2100-HLG - 1000 nit` / `Output - Rec.2100-Rec.2020-ST2084 - 1000 nit`).
- Prefer OCIO Builtin / ACES OT for Resolve / Python apply. Do not invent a homemade HLG/PQ curve.
- **macOS preview pixels** are ColorSync `CGColorSpace.itur_2100_HLG` / `itur_2100_PQ` (graded AP0 linear → existing BT.2020→AP0 inverse → system BT.2100). Not an ACES Output Transform. Not OCIO. rgba16Float. Layer `wantsExtendedDynamicRangeContent = true`.
- Fail closed: if the color space cannot be created, ColorSync cannot convert, or the layer cannot enable EDR — empty right-hand HDR pane and status **HDR 预览建不出**. Do not show 709 pixels. Do not guess.
- If the display has no EDR: still produce HDR-encoded pixels; status **屏幕无 EDR，预览被压到 SDR**.
- Status: **implemented (unverified)** until golden samples. Not “supported”. Not 一键精准.
- Applying HDR without OCIO must not fall back to a DIY transfer or to Rec.709.

## Other gates

- Detection ignores QuickTime `nclc` for S-Log3 / LogC4 and for as-shot CCT/tint.
- S-Log3 without gamut metadata requires the paired IDT picker (never silent Cine, never two dropdowns). Venice pairs appear only if Venice is detected.
- Nikon path does not divide 10-bit codes by 1023 before the white-paper curve.
- C-Log2 negative toe is OCIO / ACES CTL (not an invented mirrored toe).
- C-Log2 without gamut requires the paired picker (never silent Cinema Gamut).
- C-Log3 without gamut requires the paired picker (never silent Cinema Gamut).
- D-Log M stays unsupported. Apple Log 2 is Apple Wide Gamut (not BT.2020). LogC3 is EI800+AWG3 only.
- `ocio/config.ocio` names BuiltinTransform styles; Linux 18% tests use reference curves only.

## Pending IDT / process lock

- Clips without a locked curve+gamut pair stay **pending**.
- **处理已锁定片段** / **Apply graph** write one **ACES2065-1 AP0 proxy EXR sequence** (`{stem}_ACES2065-1_proxy/frame_000000.exr`) per locked clip. **整段代理，不是全精度成片.** Movie write decode uses source 10-bit / native-depth Y′CbCr → float (matrix-only; matrix and full/video from nclc/colr/vui; missing tags fail 「无法读取片源 Y′CbCr 矩阵/范围，未写出」; no silent 709-video default; video-range 10-bit is 64/876 not /1023; not the preview 8-bit path promoted to float). Movie preview first-frame unpack shares that nclc/colr/vui matrix+range helper (no transfer; missing tags fail the same Chinese; no silent 709-video default), then displays 8-bit / long-edge 1920. Stills (TIFF / DPX / EXR) stay ImageIO — already RGB, no Y′CbCr unpack. Write is source pixels 1:1 and source-native bit depth. 16384 is a refuse ceiling (「片源边长超过 16384，未写出」), not a downsample. Do not scale export to 16384 or 1920. 8-bit Y′CbCr is only the fallback. Still a proxy, not camera-original. Not ACEScct. Not a Rec.709 .mov/.mp4. Pending / unlocked stay in the list with **先选择 Log 与色域** or **先选择成对 IDT** and produce no folder. Never guessed.
- Primary button is **处理已锁定片段** — never 一键还原. Shown only when locked-clip count > 0. Status: **N 条已锁定 / M 条待选**. After the batch, **N 条已写出代理 / M 条待选跳过 / K 条失败** plus 失败原因 (not a preview refresh; not a second process button). Status copy must include **整段代理，不是全精度成片**. Before writing, estimate dest disk from locked clips only (frames × pixels × 12-byte uncompressed float32 RGB, plus a small margin). Unknown frames use duration×fps or a conservative 24 fps × 60 s guess (said in the note). If free space is short, do not write. Status: **磁盘空间不足，未写出** + **整段代理，不是全精度成片**. The folder picker may show the estimate. While writing, status shows **写出代理 i/N · frame k** (k/total when known). The same button becomes **取消**. Escape while writing is that same **取消** (no extra button); idle Escape does nothing. Cancel removes the in-progress `{stem}_ACES2065-1_proxy` folder so a half sequence is not a finished deliverable; completed clips stay. Status after cancel says **已取消** and still **整段代理，不是全精度成片**. Partial output is 不是成片. After a successful write, status includes the dest path (short) and **在 Finder 中显示**. Locked sidebar rows show **已写出代理** (or a short Chinese error). Clicking a written row or its **已写出代理** chip reveals that clip's `{stem}_ACES2065-1_proxy/` from the last dest. Pending / failed / cancelled do not reveal. Pending stay **待选** / **先选择 Log 与色域** / **先选择成对 IDT**. A cancelled in-progress clip is not 已写出; completed clips keep 已写出代理. Re-export clears or refreshes the chip. The next folder picker starts at the last dest (UserDefaults / AppSettings). Cancelled runs do not treat a deleted half-folder as success. After each locked write, count EXRs in `{stem}_ACES2065-1_proxy/` against source duration × metadata fps (off-by-one allowed: inclusive last frame). Missing fps is **读不到帧率，未核对**; missing duration is **读不到时长，未核对** — this check never guesses 24 or 30 fps and does not reuse the dest-disk 24 fps × 60 s guess. A count mismatch is **帧数对不上**; that folder is removed so it is not **已写出代理**. When the batch finishes (including cancel / disk abort / frame-check failures), status is one Chinese summary: **N 条已写出代理 / M 条待选跳过 / K 条失败** plus 失败原因 (existing chips only). The summary does not reuse the dest-disk 24 fps × 60 s guess.
- Locked-clip export works when other clips in the session are still pending. Do not require the whole bin to be locked. **导出 ACEScct / EXR** in **高级** is the same locked-only rule (behind **高级**).
- Main path: drop → lock IDT → exposure/WB → 处理已锁定片段 (writes proxy EXR sequence). One primary process button. Full-precision / camera-original bit-depth is later.
- WB inspector shows three states: 机内 as-shot / 白平衡（估计） / 灰卡. Estimate chip lights only after confirm. Grey-card overrides.
- HDR preview titles say 预览·非成片 and 未匹配 709. Do not present HLG/PQ as matched to Rec.709.
- IDT picker is one paired list (S-Log3 + S-Gamut3 vs S-Log3 + S-Gamut3.Cine), not two dropdowns.
- Venice pairs appear only if a Venice body is detected.

## As-shot white balance

- As-shot CCT + tint from camera-private metadata fills the WB knobs (UI only).
- Default CAT is identity. Log IDTs assume the image is already white-balanced.
- Do **not** treat as-shot 5600/6504 as an illuminant and CAT toward D65 (double WB).
- Apply AP0 CAT only when the user moves CCT/tint away from as-shot, or on a grey-card override.
- User move is relative: `CAT(user→D65)·inv(CAT(as→D65))` == `CAT(user→as)` in AP0. 3200→5600 warms. Not `CAT(as→user)`, not `CAT(user→D65)` alone. First typed CCT with no as-shot is a label (identity).
- Missing CCT does **not** apply 5600 K. Knobs empty / pending / identity.
- Grey-card / pick-neutral overrides as-shot and **is** an absolute CAT of the sampled white to D65 (identity only if sampled D65). Golden grey-card samples are still required. Labels stay **implemented (unverified)**.
- Auto WB is **白平衡（估计）**, not 精准 / 一键校准. SoG p=6 in linear ACEScg after IDT; confirm writes an absolute AP0 CAT. Residual <2°, mixed-light tile angle >5°, or valid pixels <15% stay empty. Never guess 5600. Never read Rec.709 pixels. Grey-card overrides the estimate. As-shot default stays identity.

## Media (no manufacturer demos)

- LogBridge does **not** ship camera manufacturer demo clips (no ARRI / Sony / RED / Panasonic / Nikon / Fujifilm sample reels).
- The user drops their own Log files or folders. Empty-state copy: **把混源文件夹拖进来**.


## Preview performance (Apple silicon)

- Movie decode is **AVAssetReader + Y′CbCr**, matrix-only to RGB. Do not let VT/nclc emit Rec.709 display values before IDT. No `copyCGImage` color convert. Stills use ImageIO. No Core Image Display P3.
- Metal applies the same locked matrices / DIY 709 OETF as CPU. Algorithm numbers do not change.
- IDT + exposure + WB stay in a graded linear cache. Scrub / ODT switch re-runs ODT only.
- Source pane stays untagged. Rec.709 tag only on the 709 preview pane.
- Linux cannot archive a .app. Frame-rate numbers need a Mac.

## Media compatibility (containers)

Decode policy only. No color-number changes. Do **not** write 全格式已支持.

- **Tried:** MOV/MP4 ProRes (422 family + 4444/XQ), H.264, HEVC 8/10-bit (422 depends on the machine). Decode is still **AVAssetReader + Y′CbCr**, matrix-only. No `copyCGImage`. No `AVVideoColorPropertiesKey` Rec.709.
- **Stills:** TIFF / DPX / EXR via ImageIO.
- **MXF:** try only if the system recognizes ProRes / AVC / HEVC. **ARRI MXF：暂不支持，请导出 MOV ProRes 再拖入.** Unrecognized MXF is skipped.
- **Refused (same R3D line):** R3D / BRAW / CRM / X-OCN / N-RAW / ProRes RAW / CinemaDNG / .ari / .arx — **R3D / BRAW：暂不支持，请在相机软件转 ProRes / EXR**. Unknown fourcc (e.g. r210) is refused with a separate line, not the R3D copy.
- Empty camera-private metadata → paired IDT picker (**先选择 Log 与色域**). Do not guess an IDT or 5600 K.
- D-Log M stays unsupported (IDT scope, not a container claim). Apple Log 2 / LogC3 EI800+AWG3 are implemented (unverified).

## Chinese settings

- Settings page is Chinese. Items: **默认预览** (Rec.709 / HLG / PQ), **导入后提示估计白平衡**, **未锁 IDT 挡住处理**.
- Default preview is Rec.709 (DIY OETF, 预览·非成片). Not a deliverable. Export stays ACEScct / EXR.
- Prompt estimate WB after import defaults **off**. When on, prompt only — do not write CAT, do not guess 5600. Confirm still required. Grey-card overrides.
- Block process when IDT is unlocked **cannot be turned off**.
- No 精准 / 一键还原 / 全自动校准. Color numbers do not change.

## UI (Chinese, one path)

- Center: source / preview + paired IDT picker pinned under the preview (not buried in **高级**). Preview panes fill the center; inspector / chrome recede. One paired list, not two dropdowns. Unlocked IDT skips process.
- Sidebar rows: **待选** vs **已锁定** are two visual states (type, weight, chip, left accent). No extra lock button. Existing paired-IDT picker stays the lock flow. Up/Down in the main window moves the selected clip. Mid-write does not change selection. Delete/Backspace removes the selected clip from the session only — does not delete, trash, or move the source file, and does not delete an already-written `_proxy` folder. After remove, select next, else previous. Mid-write ignores Delete (does not change selection, does not cancel; Escape is **取消**). Inspector text / numeric / search fields keep Delete. No extra button. No confirm sheet. Empty list keeps **把混源文件夹拖进来**. Escape while writing is the existing **取消** (`cancelLockedDeliverables`). Idle Escape does nothing (does not clear selection, does not quit). Sheets / alerts / settings keep Escape. Inspector text / numeric / search fields keep their arrows. No extra button.
- Right inspector: thinner Exposure + WB three states only (机内 as-shot / 白平衡（估计） / 灰卡). Estimate chip lights only after confirm.
- Node strip (输入 → 曝光 → 白平衡 → 输出) and Resolve export sit behind **高级** (hidden by default). Serial graph is not removed.
- Badge overlay is only **预览·非成片**. HDR titles may still say they are not matched to 709.
- One primary process button. Estimate WB is two steps (估计 then 确认). A single tap does not write CAT.

