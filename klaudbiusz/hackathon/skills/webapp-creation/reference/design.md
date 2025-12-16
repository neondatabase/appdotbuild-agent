# UI Design Reference

Available CSS classes and patterns for styling. PicoCSS provides base styling; these extend it.

## Color Variables

```css
--primary-color: #3b82f6;   /* blue - primary actions */
--primary-hover: #2563eb;   /* darker blue - hover states */
--secondary-color: #6b7280; /* gray - secondary elements */
--success-color: #10b981;   /* green - success/positive */
--danger-color: #ef4444;    /* red - danger/destructive */
--warning-color: #f59e0b;   /* amber - warnings */
```

## Components

### Card

Centered, elevated container for focused content:

```html
<div class="card">
    <h2>Title</h2>
    <p>Content goes here</p>
</div>
```

### Display Value

Large text for numbers, stats, counters:

```html
<div class="centered">
    <span class="display-value">42</span>
    <p class="label">Total items</p>
</div>
```

### Button Variants

```html
<button>Default</button>
<button class="btn-success">Confirm</button>
<button class="btn-danger">Delete</button>
<button class="btn-warning">Warning</button>
```

### Progress Bar

```html
<div class="progress-bar">
    <div class="progress-bar-fill" style="width: 60%"></div>
</div>
```

For dynamic width with Alpine.js:
```html
<div class="progress-bar">
    <div class="progress-bar-fill" :style="`width: ${percent}%`"></div>
</div>
```

## Layout Patterns

### Centered Card Layout

Good for: login forms, single-item views, confirmation dialogs

```html
<main class="container">
    <div class="card centered">
        <h1>Welcome</h1>
        <form method="post">
            <!-- form fields -->
        </form>
    </div>
</main>
```

### List with Actions

Good for: item lists, tables with row actions

```html
<table>
    <thead>
        <tr><th>Name</th><th>Actions</th></tr>
    </thead>
    <tbody>
        <tr id="item-1">
            <td>Item name</td>
            <td>
                <a href="/1/edit">Edit</a>
                <button class="btn-danger" hx-delete="/1" hx-target="#item-1" hx-swap="outerHTML">
                    Delete
                </button>
            </td>
        </tr>
    </tbody>
</table>
```

## HTMX Loading States

PicoCSS has built-in `aria-busy` support:

```html
<button hx-post="/action" hx-disabled-elt="this">
    Submit
</button>
```

For custom loading indicator:
```html
<button hx-get="/data" hx-indicator="#spinner">
    Load
    <span id="spinner" class="htmx-indicator" aria-busy="true"></span>
</button>
```

## Dark Mode

PicoCSS auto-detects system preference. Force a mode:

```html
<html data-theme="light">  <!-- or "dark" -->
```
