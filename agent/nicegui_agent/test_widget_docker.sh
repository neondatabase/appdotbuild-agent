#!/bin/bash
# Test widget system in Docker container

echo "Building Docker image..."
cd template
docker build -t widget-test .

echo "Running widget test..."
docker run --rm widget-test python -c "
import sys
import os

from app.database import create_tables
from app.widget_models import Widget, WidgetType, WidgetSize
from app.widget_service import WidgetService

print('Testing Widget System...')

# Create tables
create_tables()
print('✓ Database tables created')

# Initialize default widgets
WidgetService.initialize_default_widgets()
print('✓ Default widgets initialized')

# Get widgets
widgets = WidgetService.get_widgets_for_page('dashboard')
print(f'✓ Found {len(widgets)} default widgets')

# Create test widget
test_widget = WidgetService.create_widget(
    name='Test Widget',
    type=WidgetType.METRIC,
    size=WidgetSize.SMALL,
    config={'title': 'Test Metric', 'value': 42, 'icon': 'check'}
)
print(f'✓ Created test widget: {test_widget.name}')

# List all widgets
widgets = WidgetService.get_widgets_for_page('dashboard')
print(f'\\nTotal widgets: {len(widgets)}')
for w in widgets:
    print(f'  - {w.name} ({w.type.value})')

print('\\n✅ Widget system working correctly!')
"