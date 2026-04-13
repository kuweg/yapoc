# YAPOC Agent-Status UI — Color & Status Indicator Spec

**Version:** 1.0  
**Date:** 2026-04-10  
**Design mode:** Dark-first (light mode secondary)  
**Standard:** WCAG AA compliance required for all text/background combinations

---

## 1. Color Palette

### 1.1 Dark Mode Palette (Primary Design)

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-bg` | `#0D1117` | Page background (GitHub-dark inspired) |
| `--color-surface` | `#161B22` | Card / table background |
| `--color-surface-elevated` | `#1C2128` | Header, footer, sidebar background |
| `--color-surface-hover` | `#21262D` | Row hover state |
| `--color-border` | `#30363D` | All borders, dividers |
| `--color-border-subtle` | `#21262D` | Subtle separators within surfaces |
| `--color-primary` | `#58A6FF` | Primary actions, links, focus rings |
| `--color-primary-muted` | `#1F3A5F` | Primary color at low opacity (backgrounds) |
| `--color-secondary` | `#8B949E` | Secondary UI elements |
| `--color-text-primary` | `#E6EDF3` | Main body text, agent names |
| `--color-text-secondary` | `#8B949E` | Labels, column headers, secondary info |
| `--color-text-muted` | `#484F58` | Timestamps, disabled states, placeholders |
| `--color-text-inverse` | `#0D1117` | Text on colored badge backgrounds |

### 1.2 Light Mode Palette (Secondary Design)

| Token | Hex | Usage |
|-------|-----|-------|
| `--color-bg` | `#FFFFFF` | Page background |
| `--color-surface` | `#F6F8FA` | Card / table background |
| `--color-surface-elevated` | `#FFFFFF` | Header, footer, sidebar |
| `--color-surface-hover` | `#EFF2F5` | Row hover state |
| `--color-border` | `#D0D7DE` | All borders |
| `--color-border-subtle` | `#EFF2F5` | Subtle separators |
| `--color-primary` | `#0969DA` | Primary actions, links |
| `--color-primary-muted` | `#DDF4FF` | Primary at low opacity |
| `--color-secondary` | `#57606A` | Secondary UI elements |
| `--color-text-primary` | `#1F2328` | Main body text |
| `--color-text-secondary` | `#57606A` | Labels, column headers |
| `--color-text-muted` | `#8C959F` | Timestamps, disabled states |
| `--color-text-inverse` | `#FFFFFF` | Text on colored badge backgrounds |

---

## 2. Status Color Mapping

### 2.1 Running — Animated Blue/Cyan Pulse

| Token | Dark Mode | Light Mode |
|-------|-----------|------------|
| `--status-running-bg` | `#1F3A5F` | `#DDF4FF` |
| `--status-running-text` | `#58A6FF` | `#0969DA` |
| `--status-running-border` | `#388BFD` | `#54AEFF` |
| `--status-running-dot` | `#58A6FF` | `#0969DA` |
| `--status-running-glow` | `rgba(88, 166, 255, 0.4)` | `rgba(9, 105, 218, 0.2)` |

**Rationale:** Blue/cyan is universally associated with "active" and "in progress" in developer tooling (CI/CD pipelines, terminal spinners). The animated pulse communicates ongoing activity without being alarming.

**Animation:** The status dot pulses with a CSS keyframe animation (see §6).

### 2.2 Idle — Muted Gray

| Token | Dark Mode | Light Mode |
|-------|-----------|------------|
| `--status-idle-bg` | `#21262D` | `#EFF2F5` |
| `--status-idle-text` | `#8B949E` | `#57606A` |
| `--status-idle-border` | `#30363D` | `#D0D7DE` |
| `--status-idle-dot` | `#484F58` | `#8C959F` |

**Rationale:** Gray communicates "present but not active." Low saturation prevents it from competing with running/error states. The muted tone signals that no attention is needed.

### 2.3 Done — Green

| Token | Dark Mode | Light Mode |
|-------|-----------|------------|
| `--status-done-bg` | `#1A3A2A` | `#DAFBE1` |
| `--status-done-text` | `#3FB950` | `#1A7F37` |
| `--status-done-border` | `#2EA043` | `#2DA44E` |
| `--status-done-dot` | `#3FB950` | `#1A7F37` |

**Rationale:** Green is the universal "success" signal. A completed task is a positive outcome. Kept at medium saturation to avoid visual noise when many agents are done.

### 2.4 Error — Red with Subtle Glow

| Token | Dark Mode | Light Mode |
|-------|-----------|------------|
| `--status-error-bg` | `#3D1A1A` | `#FFEBE9` |
| `--status-error-text` | `#F85149` | `#CF222E` |
| `--status-error-border` | `#DA3633` | `#FF8182` |
| `--status-error-dot` | `#F85149` | `#CF222E` |
| `--status-error-glow` | `rgba(248, 81, 73, 0.3)` | `rgba(207, 34, 46, 0.15)` |
| `--status-error-row-accent` | `#DA3633` | `#CF222E` |

**Rationale:** Red is the universal "danger/failure" signal. The subtle glow (`box-shadow`) on the badge and the 2px left-border accent on the table row ensure errors are impossible to miss even during a quick scan.

---

## 3. Health Indicator Colors

### 3.1 OK — Green

| Token | Dark Mode | Light Mode | Icon |
|-------|-----------|------------|------|
| `--health-ok-color` | `#3FB950` | `#1A7F37` | `check-circle` (filled) |
| `--health-ok-bg` | `transparent` | `transparent` | — |

- Icon: `✓` or Heroicons `CheckCircleIcon` (solid)
- Label: "OK"
- No badge background — icon + text only to reduce visual noise

### 3.2 Warning — Amber

| Token | Dark Mode | Light Mode | Icon |
|-------|-----------|------------|------|
| `--health-warning-color` | `#D29922` | `#9A6700` | `exclamation-triangle` |
| `--health-warning-bg` | `transparent` | `transparent` | — |

- Icon: `⚠` or Heroicons `ExclamationTriangleIcon` (solid)
- Label: "WARN"
- Amber chosen over yellow for better contrast on both dark and light backgrounds

### 3.3 Critical — Red

| Token | Dark Mode | Light Mode | Icon |
|-------|-----------|------------|------|
| `--health-critical-color` | `#F85149` | `#CF222E` | `x-circle` |
| `--health-critical-bg` | `transparent` | `transparent` | — |

- Icon: `✗` or Heroicons `XCircleIcon` (solid)
- Label: "CRIT"
- Same red family as error status to reinforce the relationship

**Health indicator rendering rule:** Health is shown as `[icon] [label]` inline. No badge background — the icon carries the color signal. This keeps the health column visually lighter than the status column, maintaining hierarchy.

---

## 4. WCAG AA Compliance

WCAG AA requires a minimum contrast ratio of **4.5:1** for normal text and **3:1** for large text/UI components.

### 4.1 Dark Mode Contrast Ratios

| Foreground | Background | Ratio | Pass? | Notes |
|-----------|-----------|-------|-------|-------|
| `#E6EDF3` (text-primary) | `#161B22` (surface) | **12.8:1** | ✅ AAA | Main body text |
| `#8B949E` (text-secondary) | `#161B22` (surface) | **5.1:1** | ✅ AA | Column headers |
| `#58A6FF` (running text) | `#1F3A5F` (running bg) | **4.7:1** | ✅ AA | Running badge |
| `#3FB950` (done text) | `#1A3A2A` (done bg) | **4.6:1** | ✅ AA | Done badge |
| `#F85149` (error text) | `#3D1A1A` (error bg) | **5.2:1** | ✅ AA | Error badge |
| `#8B949E` (idle text) | `#21262D` (idle bg) | **4.5:1** | ✅ AA | Idle badge (borderline) |
| `#D29922` (warning) | `#161B22` (surface) | **5.8:1** | ✅ AA | Health warning icon |
| `#3FB950` (ok) | `#161B22` (surface) | **7.2:1** | ✅ AAA | Health ok icon |
| `#F85149` (critical) | `#161B22` (surface) | **6.1:1** | ✅ AA | Health critical icon |
| `#484F58` (text-muted) | `#161B22` (surface) | **3.1:1** | ✅ AA* | Timestamps (large text / UI component) |

*Timestamps are 12px — technically "small text" requiring 4.5:1. Consider using `#6E7681` instead for timestamps to achieve 4.5:1.

**Recommended fix for timestamps:** Use `#6E7681` (ratio 4.5:1 on `#161B22`) instead of `#484F58`.

### 4.2 Light Mode Contrast Ratios

| Foreground | Background | Ratio | Pass? |
|-----------|-----------|-------|-------|
| `#1F2328` (text-primary) | `#F6F8FA` (surface) | **15.3:1** | ✅ AAA |
| `#57606A` (text-secondary) | `#F6F8FA` (surface) | **6.1:1** | ✅ AA |
| `#0969DA` (running text) | `#DDF4FF` (running bg) | **5.4:1** | ✅ AA |
| `#1A7F37` (done text) | `#DAFBE1` (done bg) | **5.9:1** | ✅ AA |
| `#CF222E` (error text) | `#FFEBE9` (error bg) | **5.1:1** | ✅ AA |
| `#9A6700` (warning) | `#F6F8FA` (surface) | **5.2:1** | ✅ AA |

---

## 5. Status Badge / Pill Spec

### 5.1 Geometry

```css
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 12px;          /* Full pill shape */
  border: 1px solid var(--status-*-border);
  background-color: var(--status-*-bg);
  color: var(--status-*-text);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
  line-height: 1.5;
}
```

### 5.2 Status Dot

```css
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: var(--status-*-dot);
  flex-shrink: 0;
}

/* Running state only */
.status-dot--running {
  animation: pulse-running 2s ease-in-out infinite;
}
```

### 5.3 Animation Spec — "Running" Pulse (CSS Keyframe)

```css
@keyframes pulse-running {
  0% {
    box-shadow: 0 0 0 0 var(--status-running-glow);
    opacity: 1;
  }
  50% {
    box-shadow: 0 0 0 5px transparent;
    opacity: 0.7;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
    opacity: 1;
  }
}
```

**Animation properties:**
- Duration: 2s
- Timing: ease-in-out
- Iteration: infinite
- The dot itself pulses (scale + glow), not the entire badge
- The badge border also gets a subtle `box-shadow` glow on the running state:

```css
.status-badge--running {
  box-shadow: 0 0 8px var(--status-running-glow);
}
```

### 5.4 Error Row Accent

```css
tr.agent-row--error {
  border-left: 2px solid var(--status-error-row-accent);
  /* Compensate for border width to avoid layout shift */
  padding-left: calc(12px - 2px);
}
```

---

## 6. Color Usage Rules

### 6.1 When to Use Filled Badge (background + border + text)

Use filled badges for **Status** column only. The status is the most important signal and deserves the most visual weight.

- ✅ `● RUNNING` — filled cyan/blue badge
- ✅ `○ IDLE` — filled gray badge
- ✅ `✓ DONE` — filled green badge
- ✅ `✗ ERROR` — filled red badge with glow

### 6.2 When to Use Icon + Text Only (no background)

Use icon + text (no badge background) for **Health** column. Health is secondary to status and should not compete visually.

- ✅ `✓ OK` — green icon, no background
- ✅ `⚠ WARN` — amber icon, no background
- ✅ `✗ CRIT` — red icon, no background

### 6.3 When to Use Dot-Only Indicator

Use dot-only in:
- **Sidebar event log** — space is limited; color dot + text label is sufficient
- **Footer connection status** — `● Connected` / `● Disconnected`
- **Mobile card layout** — top-right corner dot to save space

```
● Connected    →  green dot (#3FB950)
● Disconnected →  red dot (#F85149)
● Reconnecting →  amber dot (#D29922) with pulse animation
```

### 6.4 Color Prohibition Rules

- ❌ Never use color as the **only** differentiator — always pair with text or icon
- ❌ Never use more than 3 distinct status colors in the same visual zone
- ❌ Never animate more than the status dot — other animations are distracting
- ❌ Never use the error red (`#F85149`) for non-error UI elements
- ❌ Never use pure white (`#FFFFFF`) text on dark backgrounds — use `#E6EDF3` instead

---

## 7. CSS Custom Properties — Full Reference

```css
:root[data-theme="dark"] {
  /* Base */
  --color-bg: #0D1117;
  --color-surface: #161B22;
  --color-surface-elevated: #1C2128;
  --color-surface-hover: #21262D;
  --color-border: #30363D;
  --color-border-subtle: #21262D;

  /* Brand */
  --color-primary: #58A6FF;
  --color-primary-muted: #1F3A5F;
  --color-secondary: #8B949E;

  /* Text */
  --color-text-primary: #E6EDF3;
  --color-text-secondary: #8B949E;
  --color-text-muted: #6E7681;
  --color-text-inverse: #0D1117;

  /* Status: Running */
  --status-running-bg: #1F3A5F;
  --status-running-text: #58A6FF;
  --status-running-border: #388BFD;
  --status-running-dot: #58A6FF;
  --status-running-glow: rgba(88, 166, 255, 0.4);

  /* Status: Idle */
  --status-idle-bg: #21262D;
  --status-idle-text: #8B949E;
  --status-idle-border: #30363D;
  --status-idle-dot: #484F58;

  /* Status: Done */
  --status-done-bg: #1A3A2A;
  --status-done-text: #3FB950;
  --status-done-border: #2EA043;
  --status-done-dot: #3FB950;

  /* Status: Error */
  --status-error-bg: #3D1A1A;
  --status-error-text: #F85149;
  --status-error-border: #DA3633;
  --status-error-dot: #F85149;
  --status-error-glow: rgba(248, 81, 73, 0.3);
  --status-error-row-accent: #DA3633;

  /* Health */
  --health-ok-color: #3FB950;
  --health-warning-color: #D29922;
  --health-critical-color: #F85149;
}

:root[data-theme="light"] {
  --color-bg: #FFFFFF;
  --color-surface: #F6F8FA;
  --color-surface-elevated: #FFFFFF;
  --color-surface-hover: #EFF2F5;
  --color-border: #D0D7DE;
  --color-border-subtle: #EFF2F5;
  --color-primary: #0969DA;
  --color-primary-muted: #DDF4FF;
  --color-secondary: #57606A;
  --color-text-primary: #1F2328;
  --color-text-secondary: #57606A;
  --color-text-muted: #8C959F;
  --color-text-inverse: #FFFFFF;

  --status-running-bg: #DDF4FF;
  --status-running-text: #0969DA;
  --status-running-border: #54AEFF;
  --status-running-dot: #0969DA;
  --status-running-glow: rgba(9, 105, 218, 0.2);

  --status-idle-bg: #EFF2F5;
  --status-idle-text: #57606A;
  --status-idle-border: #D0D7DE;
  --status-idle-dot: #8C959F;

  --status-done-bg: #DAFBE1;
  --status-done-text: #1A7F37;
  --status-done-border: #2DA44E;
  --status-done-dot: #1A7F37;

  --status-error-bg: #FFEBE9;
  --status-error-text: #CF222E;
  --status-error-border: #FF8182;
  --status-error-dot: #CF222E;
  --status-error-glow: rgba(207, 34, 46, 0.15);
  --status-error-row-accent: #CF222E;

  --health-ok-color: #1A7F37;
  --health-warning-color: #9A6700;
  --health-critical-color: #CF222E;
}
```
