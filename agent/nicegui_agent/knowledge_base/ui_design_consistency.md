# Design Consistency Guidelines

Maintain consistent spacing using Tailwind's design system: `p-2` (8px) for tight spacing, `p-4` (16px) for default component padding, `p-6` (24px) for card padding, `gap-4` (16px) for space between elements, and `mb-4` (16px) for bottom margins. This creates visual rhythm and professional appearance.

Implement a consistent color theme throughout your application. Set up a modern color palette with `ui.colors()`: professional blue for primary, subtle gray for secondary, success green for positive actions, and proper error/warning colors. Avoid pure white/black backgrounds - use `bg-gray-50` or `bg-gray-100` for better visual comfort.

Avoid common design mistakes: inconsistent spacing with arbitrary values (`margin: 13px`), missing hover states on interactive elements, inconsistent shadow usage, and cramped layouts without proper spacing. Always include focus states for keyboard navigation and use semantic color names rather than arbitrary color values.
