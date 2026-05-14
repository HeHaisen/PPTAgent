---
name: PPTAgent V3
description: Multi-agent presentation generation system — a quiet, confident tool for creating professional slides
colors:
  warm-linen: "#f3ede3"
  surface-warm: "#fffcf6"
  surface-strong: "#fffdf8"
  deep-navy: "#162534"
  slate-mist: "#5f6e7a"
  quiet-teal: "#0d6b62"
  deep-teal: "#0a554f"
  seafoam: "#e6f5f1"
  seafoam-strong: "#d8efe8"
  ink-soft: "#ebf0f4"
  warm-peach: "#f6e6d3"
  status-blue: "#eef4fb"
  teal-bright: "#138779"
typography:
  display:
    fontFamily: "'IBM Plex Sans', 'Source Han Sans SC', 'Noto Sans SC', 'PingFang SC', sans-serif"
    fontSize: "clamp(2rem, 3vw, 3.1rem)"
    fontWeight: 300
    lineHeight: 1.02
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "'IBM Plex Sans', 'Source Han Sans SC', 'Noto Sans SC', 'PingFang SC', sans-serif"
    fontSize: "1.4rem"
    fontWeight: 700
    lineHeight: 1.2
  title:
    fontFamily: "'IBM Plex Sans', 'Source Han Sans SC', 'Noto Sans SC', 'PingFang SC', sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: "'IBM Plex Sans', 'Source Han Sans SC', 'Noto Sans SC', 'PingFang SC', sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.7
  label:
    fontFamily: "'IBM Plex Sans', 'Source Han Sans SC', 'Noto Sans SC', 'PingFang SC', sans-serif"
    fontSize: "0.78rem"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "0.08em"
    textTransform: "uppercase"
rounded:
  sm: "10px"
  md: "18px"
  lg: "24px"
  xl: "28px"
  pill: "999px"
spacing:
  xs: "5px"
  sm: "10px"
  md: "14px"
  lg: "18px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.quiet-teal}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
    padding: "14px 28px"
    size: "1rem"
    height: "52px"
  button-primary-hover:
    backgroundColor: "{colors.deep-teal}"
  button-secondary:
    backgroundColor: "rgba(255, 255, 255, 0.70)"
    textColor: "{colors.deep-navy}"
    rounded: "{rounded.pill}"
    padding: "10px 16px"
  button-secondary-hover:
    backgroundColor: "#ffffff"
  button-disabled:
    backgroundColor: "#e7edf2"
    textColor: "#768492"
  card:
    backgroundColor: "{colors.surface-warm}"
    rounded: "{rounded.lg}"
    padding: "{spacing.lg}"
  input:
    backgroundColor: "rgba(255, 255, 255, 0.66)"
    rounded: "20px"
    padding: "{spacing.md}"
  chip:
    backgroundColor: "linear-gradient(180deg, rgba(255,255,255,0.82), rgba(232, 244, 239, 0.86))"
    rounded: "16px"
    padding: "12px 14px"
  tab:
    backgroundColor: "rgba(232, 240, 248, 0.92)"
    textColor: "#1f3850"
    rounded: "{rounded.sm}"
  tab-active:
    backgroundColor: "{colors.quiet-teal}"
    textColor: "#ffffff"
---

# Design System: PPTAgent V3

## 1. Overview

**Creative North Star: "The Quiet Studio"**

This is a tool that earns trust through restraint. The surface is warm but not cozy, confident but not loud. Every visual choice serves the user's primary task: provide a prompt, watch slides form, download the result. The interface should feel like a well-lit workspace with good materials at hand, not a showcase or a dashboard competing for attention.

The system rejects the generic Gradio look: the default gray backgrounds, flat inputs, and visual poverty that make every AI demo look interchangeable. It equally rejects the over-designed SaaS dashboard: cream-on-cream card stacks, gradient accent blobs, and the hero-metric-3-cards template. This is not a Notion clone, not a marketing site, not a terminal. It is a precise, warm, confident tool.

**Key Characteristics:**
- Warmth through material quality (translucent layers, soft gradients, considered spacing), not through copy or decoration
- Confidence through typographic hierarchy and deliberate color restraint
- Depth through layered translucency, not through heavy shadows or dark surfaces
- Friction-free primary flow: zero extra clicks between prompt and result
- Progressive disclosure: powerful configuration exists but does not clutter the main path

**Layout: The Two-Panel Split**

The interface uses an asymmetric two-column layout: a compact input panel (scale 3, min 420px) on the left, and an expansive result panel (scale 7, min 600px) on the right. The result side gets roughly twice the horizontal space because the primary output, slide previews, needs room to breathe. The input side is a working surface: dense, structured, no wasted vertical space.

Within the left panel, content is layered through progressive disclosure. The primary flow (attachments, instruction, send button) is always visible. Configuration (page count, output type, template) lives in a grouped control shell. Advanced settings and session history are collapsed into accordions by default. Each layer has a clear subsection title with a one-line description so the user never has to guess what a control does.

The right panel is output-dominant. Status and download sit in a compact toolbar row at the top. The remaining space is devoted to the preview area (slide gallery or PDF viewer), which should fill the available height. Tabs separate slide preview, PDF preview, and execution logs without nesting further panels.

**Information Hierarchy and Density**

The interface has exactly three levels of visual weight: section kickers (Label style, Deep Teal, uppercase), section headings (Headline style), and body text. No fourth level. If something feels like it needs a fourth, merge it into body or remove it.

Vertical rhythm is tight. Panel padding is 18px. Gaps between internal elements are 10px. Subsection titles sit 10px above their controls. The spacing scale (5/10/14/18/24px) is used deliberately, not uniformly: tighter gaps within a group, wider gaps between groups. Same padding everywhere is monotony.

Component density follows the principle: one screen, one job. The left panel's job is "configure and submit." The right panel's job is "show the result." Neither panel should try to do the other's job. Controls that don't directly serve the primary path are hidden by default.

**The Asymmetric Split Rule.** The result panel takes ~65% of the width; the input panel takes ~35%. This ratio is not negotiable. A slide preview at 50% width is too small to read; an input form at 50% width wastes space on empty fields.

## 2. Colors: The Warm Linen Palette

The palette is built on a warm beige ground with a deep teal accent. The neutrals carry the atmosphere; the accent carries the action.

### Primary
- **Quiet Teal** (#0d6b62): The accent. Used on interactive elements, active states, and the primary action button. Appears on less than 15% of any screen. Its restraint is the point; when it appears, it means "this is actionable."
- **Deep Teal** (#0a554f): Hover and emphasis variant of the primary. Used for button hover states, kicker labels, and strong accent text.
- **Teal Bright** (#138779): Used only in gradients where the primary needs slight lift (the send button gradient). Never as a flat surface color.

### Neutral
- **Warm Linen** (#f3ede3): The ground. The background of the entire interface. Tinted warm; never pure white, never gray.
- **Surface Warm** (rgba(255, 252, 246, 0.92) / #fffcf6): Panel and card backgrounds. Translucent, allowing the Warm Linen ground to breathe through. Always paired with backdrop-filter: blur(12px).
- **Surface Strong** (#fffdf8): The opaque variant of surface. Used where translucency would cause readability issues (status areas, dependency panels).
- **Deep Navy** (#162534): Primary text color. Dark but not black; the blue undertone keeps it from feeling harsh against Warm Linen.
- **Slate Mist** (#5f6e7a): Secondary text. Descriptions, captions, muted content. Always readable against Warm Linen at WCAG AA.
- **Ink Soft** (#ebf0f4): Light blue-gray for subtle backgrounds (status areas, inactive regions).

### Accent Soft
- **Seafoam** (#e6f5f1): Soft background tint for composer areas and search panels. Communicates "input zone" without a hard border.
- **Seafoam Strong** (#d8efe8): The deeper variant for hover states within soft zones.
- **Warm Peach** (#f6e6d3): Warm accent for note chips and informational callouts. Balances the teal with warmth.
- **Status Blue** (#eef4fb): Status and dependency check panels. Cool and informational, distinct from the warm palette.

### Named Rules

**The Quiet Accent Rule.** The primary teal appears on interactive elements only: buttons, active tabs, selected states, links. It is never a background color, never decorative. When you see teal, you can click it.

**The Warm Ground Rule.** Every surface sits on or tints from Warm Linen. No cool grays, no pure whites, no blue backgrounds (except Status Blue for system feedback). The warmth is non-negotiable.

**The Translucency Rule.** Surface panels use rgba with backdrop-filter: blur(12px). The ground breathes through. This is how depth works here: not with opaque layers stacked with shadows, but with translucent layers revealing what's beneath.

## 3. Typography

**Display Font:** IBM Plex Sans (with Source Han Sans SC, Noto Sans SC, PingFang SC for CJK)
**Body Font:** IBM Plex Sans (same stack)

**Character:** IBM Plex Sans is a humanist sans with enough warmth to feel approachable and enough structure to feel technical. The pairing is a single-family system; hierarchy comes entirely from scale, weight, and letter-spacing, not from font-family switching. The CJK fallback chain ensures Chinese text renders with consistent weight and metrics across platforms.

### Hierarchy
- **Display** (300, clamp(2rem, 3vw, 3.1rem), 1.02): Hero headlines only. The hero banner h1. Light weight with tight tracking creates an airy, confident feel at large sizes.
- **Headline** (700, 1.4rem, 1.2): Section headings. Panel titles. Bold and tight, anchoring each panel.
- **Title** (600, 1rem, 1.4): Subsection headings. Card titles. Strong enough to separate from body, quiet enough not to compete with headline.
- **Body** (400, 1rem, 1.7): All running text. Max line length 72ch. Comfortable leading for reading.
- **Label** (700, 0.78rem, 1.4, 0.08em tracking, uppercase): Kicker labels, category tags, metadata. The uppercase + wide tracking creates a subtle institutional voice.

### Named Rules

**The One-Family Rule.** IBM Plex Sans everywhere. No font-family switching for emphasis. Hierarchy is scale and weight only.

**The Kicker Convention.** Section kickers use the Label style: uppercase, 700 weight, 0.08em tracking, colored in Deep Teal. This pattern repeats across hero badges, section headings, and download cards to create a consistent structural language.

## 4. Elevation: Layered Translucency

This system conveys depth through layered translucency and ambient shadows, not through opaque surfaces with drop shadows. The background (Warm Linen) is always visible through the surface layers, creating a sense of material lightness.

The resting state has visible depth: panels float above the ground with ambient shadows and translucent surfaces. Depth is structural, not interactive; hover states add a subtle lift (translateY) but the shadow vocabulary does not change between resting and active states.

### Shadow Vocabulary
- **Ambient Panel** (`0 20px 60px rgba(16, 33, 47, 0.10)`): The default panel shadow. Wide, soft, low-opacity. Used on `.panel-card` and `.hero-banner`. Creates a gentle float above the Warm Linen ground.
- **Accent Lift** (`0 14px 34px rgba(13, 107, 98, 0.22)`): Teal-tinted shadow for the primary action button. The color tint reinforces the accent identity.
- **Subtle Lift** (`0 12px 28px rgba(13, 107, 98, 0.18)`): Slightly tighter variant for download links and secondary interactive elements.
- **Inset Highlight** (`inset 0 1px 0 rgba(255,255,255,0.7)`): Top-edge inner glow on chat containers and status areas. Simulates a light source from above, adding dimension to recessed surfaces.

### Named Rules

**The Layered Depth Rule.** Every visual layer has both a translucent background and an ambient shadow. Neither alone creates depth; together they separate planes clearly while keeping the Warm Linen ground visible.

**The No Flat Resting State Rule.** Panels are never fully opaque at rest. Surface backgrounds use rgba with 0.66-0.92 opacity. The ground always breathes through.

## 5. Components

### Panel Cards
- **Shape:** Generously rounded (24px radius). The large radius communicates calm and approachability.
- **Background:** Translucent warm white (rgba(255, 252, 246, 0.92)) with backdrop-filter: blur(12px). The ground tints through.
- **Shadow:** Ambient Panel shadow. Always present at rest.
- **Border:** 1px solid rgba(23, 42, 58, 0.12). Near-invisible; the shadow does the separation work.
- **Internal Padding:** 18px. Consistent across all panels.

### Buttons
- **Shape:** Pill (999px radius). The pill shape is the system's signature: calm, confident, no hard corners.
- **Primary:** Quiet Teal (#0d6b62) background, white text, 700 weight, 52px min-height. Gradient from Quiet Teal to Teal Bright on the send button for emphasis. Accent Lift shadow.
- **Hover:** Background shifts to Deep Teal (#0a554f). Subtle translateY(-1px) lift. Transition: 0.18s ease.
- **Secondary:** Translucent white background (rgba(255,255,255,0.70)), Deep Navy text, 1px border at 0.12 opacity.
- **Disabled:** Cool gray (#e7edf2) background, muted text (#768492). pointer-events: none.

### Chips / Note Cards
- **Shape:** 16px radius. Slightly tighter than panels to create visual variety.
- **Background:** Warm-tinted gradient (linear from white 82% to seafoam 86%). Not translucent; these are informational, not structural.
- **Border:** 1px solid rgba(13, 107, 98, 0.10). Teal-tinted to connect to the accent system.
- **Content:** Bold title (0.92rem) + muted description (0.86rem). Two-line maximum.

### Inputs / Composer
- **Shape:** 20px radius. Rounded but not pill-shaped; inputs need to feel like fields, not buttons.
- **Background:** Translucent white (rgba(255,255,255,0.66)). Less opaque than panels to signal "you fill this."
- **Border:** 1px solid var(--dp-border). Subtle.
- **Focus:** No dramatic focus ring. Border color shifts slightly; the input area becomes slightly more opaque.

### Tabs (Preview)
- **Shape:** 10px radius. Tighter than other components; tabs are compact controls.
- **Default:** Cool blue-gray background (rgba(232, 240, 248, 0.92)), Deep Navy text, 1px border.
- **Active:** Quiet Teal background, white text, Deep Teal border. The active tab is the only place tabs use the accent.
- **Hover:** Slightly darker blue-gray. No dramatic shift.

### Download Cards
- **Shape:** 18px radius. Between chips (16px) and panels (24px).
- **Background:** Teal-tinted gradient (white to seafoam). Communicates "this is ready to use."
- **Empty State:** Dashed border, cool gray gradient. Signals "nothing here yet" without being heavy.
- **Actions:** Pill-shaped links. Primary download in Quiet Teal; secondary in translucent white.

## 6. Do's and Don'ts

### Do:
- **Do** use Warm Linen (#f3ede3) as the ground for every surface. No cool grays, no pure whites as backgrounds.
- **Do** use translucent surfaces (rgba + backdrop-filter: blur(12px)) for structural panels. The ground must breathe through.
- **Do** reserve Quiet Teal (#0d6b62) for interactive elements only. Its scarcity is the point.
- **Do** use the Kicker Convention (uppercase, 700, 0.08em tracking, Deep Teal) for section labels and metadata.
- **Do** use pill-shaped (999px radius) buttons as the default button shape.
- **Do** maintain the Layered Depth Rule: every panel has both translucency and an ambient shadow.
- **Do** use IBM Plex Sans for all text. Hierarchy through scale and weight, never font-family switching.
- **Do** keep body text at max 72ch line length for readability.
- **Do** use WCAG AA contrast ratios for all text against its background.
- **Do** preserve all existing functionality in every design change. New features are additive only. Report what changed after each edit.
- **Do** give the result panel roughly twice the horizontal space of the input panel. Previews need room; controls need structure.
- **Do** collapse secondary controls (advanced settings, history, logs) into accordions. The primary path must be visible without scrolling.
- **Do** use subsection titles with one-line descriptions above every control group. Never present a cluster of controls without a label.
- **Do** keep gaps within a control group tight (10px) and gaps between groups wider (14-18px). The spacing differential is what creates visual hierarchy without borders.

### Don't:
- **Don't** use the generic Gradio look. PRODUCT.md names this as the primary anti-reference. Every surface must have intentional color, radius, and shadow.
- **Don't** use over-designed SaaS dashboard patterns. PRODUCT.md explicitly rejects cream-on-cream card stacks, gradient accent blobs, and the hero-metric-3-cards template.
- **Don't** use dark mode or terminal aesthetics. The mixed user base includes non-developers.
- **Don't** use side-stripe borders (border-left/right > 1px as colored accent). Never intentional; rewrite with full borders, background tints, or nothing.
- **Don't** use gradient text (background-clip: text). Decorative, never meaningful.
- **Don't** use glassmorphism as default. Blurs are structural (backdrop-filter on panels), not decorative.
- **Don't** use identical card grids. Same-sized cards with icon + heading + text, repeated endlessly, is the SaaS template.
- **Don't** use modals as first thought. Exhaust inline and progressive alternatives first.
- **Don't** use em dashes anywhere in copy. Use commas, colons, semicolons, periods, or parentheses.
- **Don't** animate CSS layout properties. Use transform and opacity only, with ease-out curves.
- **Don't** use pure black (#000) or pure white (#fff) anywhere. Every neutral is tinted toward Warm Linen.
- **Don't** give the input and result panels equal width. Equal splits make both sides feel cramped. The result side dominates.
- **Don't** show all configuration at once. If a control isn't needed on every generation, collapse it. Visible means "always relevant."
- **Don't** use uniform spacing. Same padding on every element flattens the hierarchy. Tight within groups, wider between groups.
- **Don't** nest panels inside panels. One level of card depth per surface. Accordions and tabs are the exception, not additional card layers.
