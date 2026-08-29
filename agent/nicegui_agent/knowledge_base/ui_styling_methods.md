# NiceGUI Component Styling Methods

Use Tailwind CSS classes as your primary styling method for layout, spacing, and visual design: `ui.button('Save').classes('bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded')`. This approach provides consistency, responsiveness, and follows modern CSS utility patterns.

Use Quasar props for component-specific features that aren't available through Tailwind: `ui.button('Delete').props('color=negative outline')`. Props access the underlying Quasar component's native functionality and are essential for complex component behaviors.

Reserve CSS styles for custom properties and advanced styling needs: `ui.card().style('background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)')`. Use this method sparingly and only when Tailwind classes and Quasar props cannot achieve the desired effect.
