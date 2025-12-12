# TypeScript Patterns for Web Apps

## State Management

Always define state with an interface:

```typescript
interface AppState {
    items: Item[];
    selectedId: string | null;
    isLoading: boolean;
}

const state: AppState = {
    items: [],
    selectedId: null,
    isLoading: false
};
```

## Event Handlers

Type your event handlers:

```typescript
function handleClick(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    // ...
}

function handleInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    const value = input.value;
    // ...
}
```

## DOM Updates

Use type-safe DOM queries:

```typescript
const button = $<HTMLButtonElement>('#submit');
if (button) {
    button.addEventListener('click', handleClick);
}
```

## Local Storage

Type your storage operations:

```typescript
interface StoredData {
    items: Item[];
    lastUpdated: string;
}

function saveToStorage(data: StoredData): void {
    localStorage.setItem('app-data', JSON.stringify(data));
}

function loadFromStorage(): StoredData | null {
    const raw = localStorage.getItem('app-data');
    if (!raw) return null;
    return JSON.parse(raw) as StoredData;
}
```

## Array Operations

Use typed array methods:

```typescript
interface Item {
    id: string;
    name: string;
    completed: boolean;
}

const items: Item[] = [];

// find with type
const found = items.find((item): item is Item => item.id === targetId);

// filter
const completed = items.filter(item => item.completed);

// map
const names = items.map(item => item.name);
```

## Null Handling

Always handle null cases:

```typescript
const element = $<HTMLElement>('#target');
if (!element) {
    console.error('Element not found');
    return;
}
// now element is guaranteed to exist
```
