# Product

## Register

product

## Users

Mixed audience of researchers/academics and business professionals. Researchers arrive with papers, notes, or a topic and need conference talks, lecture slides, or thesis defenses. Business professionals arrive with data, reports, or product briefs and need Q4 reviews, pitches, or internal docs. Both share the same context: they have content but lack time to design. They open the WebUI, provide a prompt and optional attachments, and expect a polished presentation in minutes, not hours.

## Product Purpose

PPTAgent V3 is a multi-agent system that automatically generates professional PowerPoint presentations from natural language prompts, documents, or reference materials. It orchestrates research, design, and template-editing agents through an MCP tool chain in a Docker sandbox. The WebUI is the control surface: users configure generation, monitor progress in real time, preview slides inline, and download the final .pptx. Success means the user gets a presentation that looks intentionally designed, not auto-generated.

## Brand Personality

**Precise, warm, confident.** The UI communicates technical competence without coldness. It trusts the user to know what they want and gets out of the way. Warmth comes from tactile details (spacing, color, typography) not from copy or decoration. Confidence means the interface never apologizes for itself or over-explains.

## Anti-references

- **Generic Gradio look.** The default Gradio theme is the primary anti-reference. Cookie-cutter inputs, gray backgrounds, no visual hierarchy, indistinguishable from every other Gradio demo. PPTAgent should feel like a purpose-built tool, not a framework default.
- **Over-designed SaaS dashboards.** Avoid cream-on-cream card stacks, gradient accent blobs, and the "hero metric + 3 feature cards" template. The tool should not look like a Notion clone.
- **Dev-tool dark mode.** Not a terminal, not an IDE. The mixed user base includes non-developers; a dark monospace aesthetic would be intimidating and off-brand.

## Design Principles

1. **Practice what you preach.** A presentation tool that generates beautiful slides must itself look intentional. The WebUI is the first impression of quality.
2. **Show, don't explain.** Live previews, inline slide images, and real-time progress replace lengthy descriptions. The user sees the result as it forms.
3. **Expert defaults, simple surface.** Expose powerful configuration (aspect ratio, language, template choice, offline mode) without cluttering the primary flow. Progressive disclosure over flat complexity.
4. **Friction-free primary path.** The main flow (prompt in, slides out) should require zero scrolling, zero extra clicks, and zero reading of instructions.
5. **Earned confidence.** Every visual choice (color, spacing, type) should feel deliberate and calm, not decorative or trendy. The interface should make users trust the output.
6. **Non-destructive iteration.** Design changes preserve all existing functionality. New features are additive only. Every change is reported clearly so the user always knows what moved.

## Accessibility & Inclusion

WCAG AA compliance. Sufficient contrast ratios for all text and interactive elements. Keyboard navigable primary flow. No reliance on color alone to convey status. Consider reduced-motion preferences for any animations.
