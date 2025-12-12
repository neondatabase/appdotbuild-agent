// type definitions for app state
interface AppState {
    // define your state shape here
}

// initial state
const state: AppState = {};

// DOM helper: query single element with null check
function $<T extends HTMLElement>(selector: string): T | null {
    return document.querySelector<T>(selector);
}

// DOM helper: query all elements
function $$<T extends HTMLElement>(selector: string): NodeListOf<T> {
    return document.querySelectorAll<T>(selector);
}

// DOM helper: create element with attributes
function createElement<K extends keyof HTMLElementTagNameMap>(
    tag: K,
    attrs?: Record<string, string>,
    children?: (HTMLElement | string)[]
): HTMLElementTagNameMap[K] {
    const el = document.createElement(tag);
    if (attrs) {
        Object.entries(attrs).forEach(([key, value]) => {
            el.setAttribute(key, value);
        });
    }
    if (children) {
        children.forEach(child => {
            if (typeof child === 'string') {
                el.appendChild(document.createTextNode(child));
            } else {
                el.appendChild(child);
            }
        });
    }
    return el;
}

// render function: update DOM based on state
function render(): void {
    const main = $<HTMLElement>('#main');
    if (!main) return;

    // implement your render logic here
    main.innerHTML = '<p>App loaded. Implement your UI here.</p>';
}

// initialize app
document.addEventListener('DOMContentLoaded', (): void => {
    console.log('App initialized');
    render();
});
