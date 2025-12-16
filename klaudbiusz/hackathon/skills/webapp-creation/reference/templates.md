# Frontend Templates

## Askama Basics

Every template needs a corresponding Rust struct:

```rust
#[derive(Template)]
#[template(path = "index.html")]
struct IndexTemplate {
    tasks: Vec<Task>,
}

#[derive(Template)]
#[template(path = "edit.html")]
struct EditTemplate {
    task: Task,
}
```

### Base Template

`templates/base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}App{% endblock %}</title>
    <link rel="stylesheet" href="https://unpkg.com/@picocss/pico@2/css/pico.min.css">
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <script defer src="https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js"></script>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
    <nav class="container">
        <ul><li><a href="/"><strong>App</strong></a></li></ul>
    </nav>
    <main class="container">{% block content %}{% endblock %}</main>
</body>
</html>
```

### List Template

```html
{% extends "base.html" %}

{% block content %}
<h1>Tasks</h1>
<a href="/new" role="button">+ New Task</a>

<table>
    <thead>
        <tr><th>Title</th><th>Status</th><th>Actions</th></tr>
    </thead>
    <tbody>
        {% for task in tasks %}
        <tr id="task-{{ task.id }}">
            <td>{{ task.title }}</td>
            <td>{% if task.completed %}Done{% else %}Pending{% endif %}</td>
            <td>
                <a href="/{{ task.id }}/edit">Edit</a>
                <button hx-delete="/{{ task.id }}" hx-target="#task-{{ task.id }}" hx-swap="outerHTML" hx-confirm="Delete?">Delete</button>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}
```

### Create Form

```html
{% extends "base.html" %}

{% block content %}
<h1>New Task</h1>

<form method="post" action="/" x-data="{ title: '' }">
    <label>
        Title
        <input type="text" name="title" x-model="title" required>
    </label>
    <button type="submit" :disabled="!title.trim()">Create</button>
</form>

<a href="/">Cancel</a>
{% endblock %}
```

### Edit Form

```html
{% extends "base.html" %}

{% block content %}
<h1>Edit Task</h1>

<form hx-post="/{{ task.id }}" hx-target="body" x-data="{ title: '{{ task.title }}' }">
    <label>
        Title
        <input type="text" name="title" x-model="title" required>
    </label>
    <button type="submit">Save</button>
</form>

<a href="/">Cancel</a>
{% endblock %}
```

## HTMX Patterns

### Inline Delete

```html
<button
    hx-delete="/{{ id }}"
    hx-target="#item-{{ id }}"
    hx-swap="outerHTML"
    hx-confirm="Are you sure?"
>Delete</button>
```

### Form with Redirect

```html
<form hx-post="/" hx-target="body">
    <!-- HTMX follows redirect automatically -->
</form>
```

### Partial Update

```html
<input type="search" id="search" name="q" hx-get="/search" hx-target="#results" hx-trigger="keyup changed delay:300ms">
<div id="results"></div>
```

### Loading Indicator

```html
<button hx-get="/slow" hx-indicator="#spinner">
    Load
    <span id="spinner" class="htmx-indicator" aria-busy="true">Loading...</span>
</button>
```

## Alpine.js Patterns

### Form Validation

```html
<form x-data="{ email: '', valid: false }" @submit.prevent="valid && $el.submit()">
    <input type="email" x-model="email" @input="valid = email.includes('@')">
    <button :disabled="!valid">Submit</button>
</form>
```

### Toggle State

```html
<div x-data="{ open: false }">
    <button @click="open = !open">Toggle</button>
    <div x-show="open">Content</div>
</div>
```

### Conditional Classes

```html
<div :class="{ 'completed': task.completed }">Status</div>
```

## Checkbox Handling

Checkboxes don't send value when unchecked. Use hidden field:

```html
<input type="hidden" name="completed" value="false">
<input type="checkbox" name="completed" value="true" {% if task.completed %}checked{% endif %}>
```

## PicoCSS

Classless styling - semantic HTML is styled automatically:
- `<nav>`, `<main>`, `<article>`, `<section>`, `<footer>`
- `<table>`, `<form>`, `<input>`, `<button>`
- Use `class="container"` for centered content with max-width
