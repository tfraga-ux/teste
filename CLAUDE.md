# CLAUDE.md — TB Capital Website

This file provides guidance for AI assistants working on this codebase.

## Project Overview

This is a **static single-file website** for **TB Capital**, a Brazilian investment fund manager. The entire application lives in one self-contained HTML file with embedded CSS, JavaScript, and base64-encoded assets.

- **File:** `tbcapital-v3 (1).html`
- **Language:** Portuguese (pt-BR)
- **Type:** Static HTML/CSS/JS — no build tools, no package manager, no dependencies
- **Hosting:** Can be served from any static file host or opened directly in a browser

## Architecture

### Single-Page Application Pattern

The site simulates multi-page navigation using a **show/hide page pattern**. There is no routing library; pages are toggled via `display: none / block` through CSS class manipulation.

**Pages (by HTML id):**

| ID | Nav Label | Description |
|----|-----------|-------------|
| `page-home` | Home | Fund overview and disclaimer cards |
| `page-documentos` | Documentos | Regulatory documents list |
| `page-investir` | Como Investir | How-to-invest guide and fund card |
| `page-investor` | Área do Investidor | Protected investor area (monthly sheets, letters, events) |
| `page-contato` | Contato | Contact information |

### Navigation

Navigation is handled by the `showPage(page)` function in the inline `<script>` block at the bottom of the file. It:
1. Removes the `.active` class from all `.page` divs
2. Adds `.active` to `#page-<name>`
3. Updates `active-link` class on nav anchors
4. Scrolls window to top

### Login / Investor Area

A modal (`#loginModal`) gates the investor area. Functions:
- `openModal()` — shows modal
- `closeModal()` — hides modal
- `handleLogin()` — closes modal and navigates to `page-investor`

The login is **not connected to any backend** — `handleLogin()` simply redirects to the investor page unconditionally. This is a UI prototype.

### Scroll Animations

An `IntersectionObserver` is used to fade-in cards and items as they enter the viewport. Elements start with `opacity: 0; transform: translateY(16px)` and transition to visible when observed.

## Styling Conventions

### Design System (CSS Custom Properties)

Defined in `:root`:

```css
--bg: #F7F5F0          /* Page background — warm off-white */
--bg-warm: #EDE9E0     /* Slightly warmer background */
--text: #1A1A18        /* Primary text — near black */
--text-muted: #6B6760  /* Secondary text */
--text-light: #9C978E  /* Tertiary / labels */
--accent: #2C3E2D      /* Forest green — brand accent */
--accent-light: #3D5A3E
--border: #D8D3C8      /* Warm gray border */
--white: #FEFDFB       /* Pure warm white */
--serif: 'Cormorant Garamond', Georgia, serif
--sans: 'DM Sans', -apple-system, sans-serif
```

Always use these variables; never hard-code color values.

### Typography

- **Headings:** `font-family: var(--serif)` — Cormorant Garamond, typically `font-weight: 300` or `400`
- **Body / UI:** `font-family: var(--sans)` — DM Sans, typically `font-weight: 300` or `400`
- **Labels:** `font-size: 11px; text-transform: uppercase; letter-spacing: 0.12em`
- **Body text:** `font-size: 15px; line-height: 1.7–1.85`

### Layout

- Fixed navbar height: `72px` — pages pad `padding-top: 72px` (or `160px` for hero sections)
- Horizontal padding: `48px` on desktop, `24px` on mobile (media query at `768px`)
- Max widths: `640–820px` for content sections
- Responsive: mobile class `.hide-mobile` hides non-essential nav links below `768px`

### Component Patterns

- **Cards:** White background (`var(--white)`), `border: 1px solid var(--border)`, `border-radius: 2px`, padding `32–36px`
- **Buttons / CTA links:** `border-radius: 2px`, thin `1px` borders, minimal hover states
- **Hover animations:** Prefer subtle transitions — `opacity`, `color`, `padding-left` — not scale or heavy transforms
- **SVG icons:** Inline SVGs with `stroke: var(--accent); fill: none; stroke-width: 1.5`

## Content Structure

### Home Page

Stacked `.card-group` with `.home-card` items (icon + paragraph text explaining the fund). Followed by a `.disclaimer-card` with regulatory disclaimers.

### Documentos

A list of `.doc-item` rows (document name + file size metadata). Currently static placeholder data.

### Como Investir

Prose paragraphs in `.invest-content` followed by a `.fund-card` showing fund details in a 2-column grid (`.fund-details`).

### Área do Investidor

Three sections separated by `.section-divider` labels:
- **Lâmina Mensal** — monthly performance sheets (`.letters-grid` items grouped by year via `.year-group`)
- **Cartas** — investor letters (same grid pattern with `.year-header` toggling via `toggleYear()`)
- **Eventos** — events list (`.content-section > .content-item`)

### Contato

Contact blocks (`.contact-block`) with address, phone, and email, plus CNPJ information.

## Key Conventions for Editing

1. **Keep everything in one file.** Do not split into separate CSS/JS files unless explicitly asked.
2. **Use CSS variables.** Never introduce new hard-coded color values.
3. **Preserve the warm minimalist aesthetic.** The design is intentionally refined and restrained — avoid heavy shadows, bright colors, or aggressive animations.
4. **Portuguese language throughout.** All user-facing text must remain in pt-BR.
5. **No external JS libraries.** The site is intentionally vanilla — do not add jQuery, Bootstrap, or similar.
6. **Inline SVGs only** for icons — do not use icon fonts or external icon libraries.
7. **Border-radius stays at 2px** — this is a deliberate low-radius design choice.
8. **No backend integration exists.** The login is purely presentational. Do not add server-side logic without a full architectural discussion.

## File Naming

The source file has a space in its name (`tbcapital-v3 (1).html`). When referencing it in shell commands, always quote the path:

```bash
open "tbcapital-v3 (1).html"
python3 -m http.server  # then open http://localhost:8000/tbcapital-v3%20(1).html
```

## Development Workflow

### Viewing the Site

No build step required. Open the HTML file directly in a browser, or serve it locally:

```bash
# Python (from repo root)
python3 -m http.server 8000

# Node (if npx available)
npx serve .
```

Then navigate to `http://localhost:8000/tbcapital-v3%20(1).html`.

### Making Changes

1. Edit `tbcapital-v3 (1).html` directly.
2. Refresh browser to preview.
3. Test all five pages (Home, Documentos, Como Investir, Área do Investidor, Contato).
4. Test the login modal flow.
5. Test on mobile viewport (768px breakpoint).

### Testing Checklist

- [ ] All five pages render without errors
- [ ] Login modal opens, closes (click outside or button), and redirects to investor area
- [ ] Scroll animations trigger on card/item elements
- [ ] Navbar border appears on scroll
- [ ] Mobile: nav hides `.hide-mobile` links; layout adapts to 24px padding
- [ ] No console errors in browser DevTools

### Committing

```bash
git add "tbcapital-v3 (1).html" CLAUDE.md
git commit -m "your descriptive message"
git push -u origin <branch-name>
```

## Git Branches

- `master` — legacy default branch name
- `main` / `origin/main` — main integration branch
- Feature branches follow the pattern `claude/<description>-<id>`

Always develop on a dedicated feature branch and open a PR to `main`.
